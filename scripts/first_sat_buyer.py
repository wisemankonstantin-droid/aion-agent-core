"""Buyer-funded AION direct Base USDC client; no broadcast without --execute."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import sys
import time
from urllib.parse import urlsplit

DEFAULT_URL = "https://aion-agent-core-live.onrender.com/commercial/route-intelligence/purchase"
DEFAULT_RPC = "https://mainnet.base.org"
BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
METHOD = "direct_base_usdc_eip3009_buyer_broadcast"
FUNCTION = "transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)"
ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
HEX32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
GAS_LIMIT = 220_000
L1_FEE_ESTIMATE_TX_BYTES = 1024  # Deliberately above this fixed-call transaction's encoded size.
GAS_ORACLE = "0x420000000000000000000000000000000000000F"


class BuyerError(Exception):
    def __init__(self, code: str, *, purchase_id: str | None = None, tx_hash: str | None = None):
        super().__init__(code)
        self.code = code
        self.purchase_id = purchase_id
        self.tx_hash = tx_hash


@dataclass(frozen=True)
class Offer:
    purchase_id: str
    result_digest: str
    amount: int
    recipient: str
    nonce: str
    valid_after: int
    valid_before: int
    buyer_address: str


def _required(condition: bool, code: str) -> None:
    if not condition:
        raise BuyerError(code)


def _atomic_usdc(value: str) -> int:
    try:
        amount = Decimal(value)
        atomic = amount * 1_000_000
    except (InvalidOperation, TypeError, ValueError):
        raise BuyerError("invalid_usdc_amount") from None
    _required(amount.is_finite() and atomic == atomic.to_integral_value() and atomic > 0, "invalid_usdc_amount")
    return int(atomic)


def _int_string(value: object) -> int:
    _required(isinstance(value, str) and value.isascii() and value.isdecimal(), "invalid_payment_integer")
    return int(value)


def validate_offer(body: object, buyer_address: str, *, max_usdc: str, now: int, timeout: int = 30) -> Offer:
    """Validate server payment instructions against hardcoded Base USDC invariants."""
    _required(isinstance(body, dict) and body.get("code") == "payment_required", "invalid_402_body")
    _required(body.get("payment_method") == METHOD, "unsupported_payment_method")
    _required(isinstance(buyer_address, str) and ADDRESS.fullmatch(buyer_address) is not None, "invalid_buyer_address")
    instruction, quote = body.get("payment_instructions"), body.get("quote")
    _required(isinstance(instruction, dict) and isinstance(quote, dict), "payment_instructions_missing")
    purchase, digest = body.get("purchase_id"), body.get("prepared_result_digest")
    _required(isinstance(purchase, str) and UUID.fullmatch(purchase) is not None, "purchase_id_invalid")
    _required(isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is not None, "result_digest_invalid")
    checks = (
        instruction.get("payment_method") == METHOD,
        instruction.get("payment_flow") == "upfront",
        instruction.get("transfer_method") == "eip3009_transferWithAuthorization",
        instruction.get("network") == "eip155:8453",
        instruction.get("chain_id") == 8453,
        str(instruction.get("asset", "")).lower() == BASE_USDC,
        instruction.get("asset_code") == "USDC",
        instruction.get("asset_decimals") == 6,
        instruction.get("quote_currency") == "USDC",
        instruction.get("buyer_pays_gas") is True,
        instruction.get("aion_broadcasts_transaction") is False,
        instruction.get("facilitator_required") is False,
        instruction.get("purchase_id") == purchase,
        instruction.get("prepared_result_digest") == digest,
        quote.get("currency") == "USDC",
        quote.get("asset_code") == "USDC",
        quote.get("network") == "eip155:8453",
        str(quote.get("asset", "")).lower() == BASE_USDC,
    )
    _required(all(checks), "payment_contract_mismatch")
    amount = _int_string(instruction.get("amount"))
    _required(amount > 0 and amount <= _atomic_usdc(max_usdc), "payment_amount_out_of_bounds")
    _required(quote.get("atomic_amount") == str(amount) and _atomic_usdc(quote.get("amount")) == amount, "quote_amount_mismatch")
    _required(_atomic_usdc(instruction.get("quote_amount")) == amount, "instruction_quote_mismatch")
    recipient = instruction.get("pay_to")
    _required(isinstance(recipient, str) and ADDRESS.fullmatch(recipient) is not None and int(recipient, 16) != 0, "recipient_invalid")
    auth = instruction.get("authorization")
    _required(isinstance(auth, dict) and auth.get("type") == "TransferWithAuthorization", "authorization_missing")
    domain, message, call = auth.get("domain"), auth.get("message"), auth.get("contract_call")
    _required(isinstance(domain, dict) and isinstance(message, dict) and isinstance(call, dict), "authorization_malformed")
    _required(domain == {"name": "USD Coin", "version": "2", "chainId": 8453, "verifyingContract": instruction["asset"]}, "eip712_domain_mismatch")
    _required(str(domain["verifyingContract"]).lower() == BASE_USDC, "eip712_token_mismatch")
    _required(message.get("from") in ("BUYER_EVM_ADDRESS", buyer_address, buyer_address.lower()), "authorization_payer_mismatch")
    _required(str(message.get("to", "")).lower() == recipient.lower(), "authorization_recipient_mismatch")
    _required(message.get("value") == str(amount), "authorization_amount_mismatch")
    valid_after, valid_before = _int_string(message.get("validAfter")), _int_string(message.get("validBefore"))
    _required(valid_after < int(now) and valid_before > int(now) + timeout + 30, "authorization_window_invalid")
    try:
        expires = datetime.fromisoformat(body["expires_at"])
        instruction_expires = datetime.fromisoformat(instruction["expires_at"])
        _required(expires.tzinfo is not None and instruction_expires.tzinfo is not None, "preparation_expiry_invalid")
        _required(int(expires.astimezone(timezone.utc).timestamp()) == valid_before and expires == instruction_expires, "preparation_expiry_mismatch")
    except (KeyError, TypeError, ValueError):
        raise BuyerError("preparation_expiry_invalid") from None
    expected_nonce = "0x" + hashlib.sha256(f"aion-direct-base-usdc-eip3009-v1|{purchase}|{digest}".encode("ascii")).hexdigest()
    nonce = message.get("nonce")
    _required(isinstance(nonce, str) and HEX32.fullmatch(nonce) is not None and nonce.lower() == expected_nonce, "purchase_nonce_mismatch")
    _required(str(call.get("to", "")).lower() == BASE_USDC and call.get("function") == FUNCTION and call.get("selector") == "0xe3ee160e" and call.get("caller_pays_gas") is True, "contract_call_mismatch")
    _required(instruction.get("submit_proof_with") == {"purchase_id_header": "X-AION-PURCHASE-ID", "transaction_hash_header": "X-AION-PAYMENT-TX"}, "proof_contract_mismatch")
    return Offer(purchase, digest, amount, recipient.lower(), expected_nonce, valid_after, valid_before, buyer_address)


def _metadata(offer: Offer, status: str, tx_hash: str | None = None) -> dict:
    return {"purchase_id": offer.purchase_id, "tx_hash": tx_hash, "amount": str(offer.amount), "recipient": offer.recipient, "network": "eip155:8453", "status": status}


def run(args, http, chain, *, now: int | None = None) -> dict:
    """One preparation, at most one broadcast, and at most one proof retry."""
    parsed = urlsplit(args.url)
    _required(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path == "/commercial/route-intelligence/purchase", "purchase_url_invalid")
    _required(isinstance(args.need, str) and 1 <= len(args.need.strip()) <= 128 and not any(ord(c) < 32 for c in args.need), "need_invalid")
    _required(args.candidate_identifier is None or isinstance(args.candidate_identifier, str) and 1 <= len(args.candidate_identifier) <= 240, "candidate_identifier_invalid")
    _required(isinstance(args.timeout, int) and 5 <= args.timeout <= 600, "timeout_invalid")
    expected_payee = getattr(args, "expected_payee", None)
    _required(expected_payee is None or isinstance(expected_payee, str) and ADDRESS.fullmatch(expected_payee) is not None and int(expected_payee, 16) != 0, "expected_payee_invalid")
    _required(not args.execute or expected_payee is not None, "expected_payee_required_for_execution")
    payload = {"need": args.need}
    if args.candidate_identifier is not None:
        payload["candidate_identifier"] = args.candidate_identifier
    try:
        first = http.post(args.url, json=payload)
    except Exception:
        raise BuyerError("purchase_request_failed") from None
    _required(first.status_code == 402, "expected_direct_payment_402")
    try:
        body = first.json()
    except Exception:
        raise BuyerError("invalid_402_json") from None
    checked = validate_offer(body, chain.address, max_usdc=args.max_usdc, now=int(time.time()) if now is None else now, timeout=args.timeout)
    _required(expected_payee is None or checked.recipient == expected_payee.lower(), "expected_payee_mismatch")
    try:
        _required(chain.chain_id == 8453, "rpc_wrong_chain")
        _required(chain.usdc_balance >= checked.amount, "insufficient_usdc")
        gas_budget = chain.gas_budget
        _required(gas_budget > 0 and chain.eth_balance >= gas_budget, "insufficient_eth_for_gas")
        try:
            gas_cap = Decimal(getattr(args, "max_gas_eth", "0.005")) * 10**18
            _required(gas_cap.is_finite() and gas_cap > 0 and gas_cap == gas_cap.to_integral_value(), "gas_cap_invalid")
        except (InvalidOperation, TypeError, ValueError):
            raise BuyerError("gas_cap_invalid") from None
        _required(gas_budget <= int(gas_cap), "gas_budget_exceeded")
        _required(not chain.is_authorization_used(checked), "authorization_already_used")
    except BuyerError:
        raise
    except Exception:
        raise BuyerError("balance_or_rpc_check_failed") from None
    if not args.execute:
        return _metadata(checked, "dry_run_validated")
    _required(checked.valid_before > int(time.time() if now is None else now) + args.timeout + 30, "authorization_window_invalid")
    try:
        tx = chain.broadcast(checked)
    except Exception:
        raise BuyerError("broadcast_outcome_unknown", purchase_id=checked.purchase_id) from None
    _required(isinstance(tx, str) and HEX32.fullmatch(tx) is not None, "transaction_hash_invalid")
    try:
        safe = chain.wait_safe(tx, time.monotonic() + args.timeout)
    except BuyerError as exc:
        raise BuyerError(exc.code, purchase_id=checked.purchase_id, tx_hash=tx) from None
    except Exception:
        raise BuyerError("payment_outcome_unknown", purchase_id=checked.purchase_id, tx_hash=tx) from None
    if not safe:
        raise BuyerError("payment_not_safe_before_timeout", purchase_id=checked.purchase_id, tx_hash=tx)
    try:
        second = http.post(args.url, json=payload, headers={"X-AION-PURCHASE-ID": checked.purchase_id, "X-AION-PAYMENT-TX": tx})
        data = second.json()
    except Exception:
        raise BuyerError("result_release_unknown", purchase_id=checked.purchase_id, tx_hash=tx) from None
    payment = data.get("payment") if isinstance(data, dict) else None
    if not (second.status_code == 200 and isinstance(data, dict) and data.get("purchase_id") == checked.purchase_id and data.get("prepared_result_digest") == checked.result_digest and data.get("state") == "entitled" and data.get("result") is not None and isinstance(payment, dict) and payment.get("method") == METHOD and isinstance(payment.get("transaction"), str) and payment["transaction"].lower() == tx.lower() and payment.get("atomic_amount") == str(checked.amount) and payment.get("network") == "eip155:8453"):
        raise BuyerError("result_release_unverified", purchase_id=checked.purchase_id, tx_hash=tx)
    return _metadata(checked, "result_released", tx)


def sign_authorization(offer: Offer, private_key: str) -> tuple[int, int, int]:
    """Sign only the checked native-USDC EIP-3009 typed message in memory."""
    from eth_account import Account

    fields = {"TransferWithAuthorization": [
        {"name": name, "type": kind} for name, kind in (
            ("from", "address"), ("to", "address"), ("value", "uint256"),
            ("validAfter", "uint256"), ("validBefore", "uint256"), ("nonce", "bytes32"),
        )
    ]}
    domain = {"name": "USD Coin", "version": "2", "chainId": 8453, "verifyingContract": BASE_USDC}
    message = {"from": offer.buyer_address, "to": offer.recipient, "value": offer.amount, "validAfter": offer.valid_after, "validBefore": offer.valid_before, "nonce": bytes.fromhex(offer.nonce[2:])}
    signed = Account.sign_typed_data(private_key, domain, fields, message)
    return signed.v, signed.r, signed.s


class BaseChain:
    """Buyer-owned Web3 adapter; broadcast() is its only money-moving call."""

    def __init__(self, rpc_url: str, private_key: str):
        from eth_account import Account
        from web3 import HTTPProvider, Web3

        parsed = urlsplit(rpc_url)
        _required(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment, "rpc_url_invalid")
        try:
            self.account = Account.from_key(private_key)
        except Exception:
            raise BuyerError("buyer_key_invalid") from None
        self.key = private_key
        self.address = self.account.address
        self.w3 = Web3(HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        self.contract = self.w3.eth.contract(address=Web3.to_checksum_address(BASE_USDC), abi=[
            {"name": "balanceOf", "type": "function", "stateMutability": "view", "inputs": [{"name": "account", "type": "address"}], "outputs": [{"type": "uint256"}]},
            {"name": "authorizationState", "type": "function", "stateMutability": "view", "inputs": [{"name": "authorizer", "type": "address"}, {"name": "nonce", "type": "bytes32"}], "outputs": [{"type": "bool"}]},
            {"name": "transferWithAuthorization", "type": "function", "stateMutability": "nonpayable", "inputs": [{"name": "from", "type": "address"}, {"name": "to", "type": "address"}, {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"}, {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"}, {"name": "v", "type": "uint8"}, {"name": "r", "type": "bytes32"}, {"name": "s", "type": "bytes32"}], "outputs": []},
        ])
        self.gas_oracle = self.w3.eth.contract(address=Web3.to_checksum_address(GAS_ORACLE), abi=[
            {"name": "getL1FeeUpperBound", "type": "function", "stateMutability": "view", "inputs": [{"name": "unsignedTxSize", "type": "uint256"}], "outputs": [{"type": "uint256"}]},
            {"name": "getOperatorFee", "type": "function", "stateMutability": "view", "inputs": [{"name": "gasUsed", "type": "uint256"}], "outputs": [{"type": "uint256"}]},
        ])
        self._gas_price: int | None = None

    @property
    def chain_id(self) -> int:
        return self.w3.eth.chain_id

    @property
    def usdc_balance(self) -> int:
        return self.contract.functions.balanceOf(self.address).call()

    @property
    def eth_balance(self) -> int:
        return self.w3.eth.get_balance(self.address)

    @property
    def gas_budget(self) -> int:
        self._gas_price = self.w3.eth.gas_price
        l1_fee_bound = self.gas_oracle.functions.getL1FeeUpperBound(L1_FEE_ESTIMATE_TX_BYTES).call()
        operator_fee = self.gas_oracle.functions.getOperatorFee(GAS_LIMIT).call()
        _required(all(isinstance(fee, int) and fee >= 0 for fee in (l1_fee_bound, operator_fee)), "gas_fee_estimate_invalid")
        return GAS_LIMIT * self._gas_price + l1_fee_bound + operator_fee

    def is_authorization_used(self, offer: Offer) -> bool:
        return self.contract.functions.authorizationState(self.address, bytes.fromhex(offer.nonce[2:])).call()

    def broadcast(self, offer: Offer) -> str:
        _required(self.chain_id == 8453, "rpc_wrong_chain")
        _required(self._gas_price is not None, "gas_not_checked")
        v, r, s = sign_authorization(offer, self.key)
        fn = self.contract.functions.transferWithAuthorization(
            self.address, offer.recipient, offer.amount, offer.valid_after,
            offer.valid_before, bytes.fromhex(offer.nonce[2:]),
            v, r.to_bytes(32, "big"), s.to_bytes(32, "big"),
        )
        tx = fn.build_transaction({
            "from": self.address, "chainId": 8453, "gas": GAS_LIMIT,
            "gasPrice": self._gas_price,
            "nonce": self.w3.eth.get_transaction_count(self.address, "pending"),
        })
        signed_tx = self.account.sign_transaction(tx)
        return self.w3.eth.send_raw_transaction(signed_tx.raw_transaction).hex()

    def wait_safe(self, tx: str, deadline: float) -> bool:
        from web3.exceptions import TransactionNotFound

        while time.monotonic() < deadline:
            try:
                receipt = self.w3.eth.get_transaction_receipt(tx)
            except TransactionNotFound:
                receipt = None
            if receipt is not None:
                if receipt["status"] != 1:
                    raise BuyerError("payment_transaction_failed")
                safe_block = self.w3.eth.get_block("safe")
                if safe_block["number"] >= receipt["blockNumber"]:
                    canonical = self.w3.eth.get_block(receipt["blockNumber"])
                    return canonical["hash"] == receipt["blockHash"]
            time.sleep(min(3, max(0, deadline - time.monotonic())))
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AION first-SAT buyer; dry-run unless --execute")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--need", required=True, help="Public bounded need; never include secrets")
    parser.add_argument("--candidate-identifier")
    parser.add_argument("--rpc-url", default=os.getenv("AION_BUYER_BASE_RPC_URL", DEFAULT_RPC))
    parser.add_argument("--max-usdc", required=True, help="Buyer-side USDC spending ceiling")
    parser.add_argument("--expected-payee", help="Independently verified recipient; required with --execute")
    parser.add_argument("--max-gas-eth", default="0.005", help="Buyer-side estimated gas budget ceiling")
    parser.add_argument("--timeout", type=int, default=180, help="Safe-head wait, 5-600 seconds")
    parser.add_argument("--execute", action="store_true", help="Sign and broadcast one real Base USDC payment")
    args = parser.parse_args(argv)
    key = os.getenv("AION_BUYER_PRIVATE_KEY")
    if not key:
        print('{"status":"error","code":"buyer_key_env_missing"}')
        return 2
    try:
        import httpx

        chain = BaseChain(args.rpc_url, key)
        with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as http:
            result = run(args, http, chain)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except BuyerError as exc:
        output = {"status": "error", "code": exc.code}
        if exc.purchase_id:
            output["purchase_id"] = exc.purchase_id
        if exc.tx_hash:
            output["tx_hash"] = exc.tx_hash
        print(json.dumps(output, separators=(",", ":")))
        return 2
    except Exception:
        print('{"status":"error","code":"unexpected_failure"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
