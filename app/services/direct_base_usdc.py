"""Buyer-broadcast Base USDC EIP-3009 settlement verification.

The buyer signs and broadcasts USDC transferWithAuthorization and pays gas.
AION never signs or broadcasts a money-moving transaction. AION only reads
Base mainnet and releases the prepared result after the purchase-bound EIP-3009
authorization, Transfer event, receipt and safe-block evidence all agree.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import os
import re

from . import economic_kernel
from .paid_route_intelligence import configured_route_intelligence_plan
from .safe_http import FetchPolicy, fetch_json
from .x402_payment_offer import (
    ASSET_CODE_ENV,
    ASSET_DECIMALS_ENV,
    ASSET_ENV,
    NETWORK_ENV,
    PAY_TO_ENV,
)


DIRECT_ENABLE_ENV = "AION_DIRECT_BASE_USDC_ENABLED"
DIRECT_PAYMENT_METHOD = "direct_base_usdc_eip3009_buyer_broadcast"
BASE_RPC_URL = "https://mainnet.base.org"
BASE_NETWORK = "eip155:8453"
BASE_CHAIN_ID = 8453
BASE_CHAIN_ID_HEX = "0x2105"
BASE_USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BASE_USDC_DECIMALS = 6
USDC_TOKEN_NAME = "USD Coin"
USDC_TOKEN_VERSION = "2"

# keccak256(
#   "transferWithAuthorization(address,address,uint256,uint256,uint256,"
#   "bytes32,uint8,bytes32,bytes32)"
# )[0:4]
TRANSFER_WITH_AUTHORIZATION_SELECTOR = "0xe3ee160e"
ERC20_TRANSFER_TOPIC0 = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)
AUTHORIZATION_USED_TOPIC0 = (
    "0x98de503528ee59b575ef0c0a2576a824"
    "97bfc029a5685b209e9ec333479b10a5"
)

_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_BYTES32 = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX_QUANTITY = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
_TOPIC = re.compile(r"^0x[0-9a-fA-F]{64}$")
_CALLDATA = re.compile(r"^0x[0-9a-fA-F]+$")

_RPC_POLICY = FetchPolicy(
    timeout_seconds=10.0,
    max_response_bytes=128_000,
    max_attempts=2,
    max_resolved_addresses=8,
    user_agent="AION-Base-USDC-Verify/0.8.0",
)


def _aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _address(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value if _EVM_ADDRESS.fullmatch(value) else None


def _configured_decimals() -> int | None:
    raw = (os.getenv(ASSET_DECIMALS_ENV) or "").strip()
    if not raw.isdigit():
        return None
    value = int(raw)
    return value if 0 <= value <= 18 else None


def _base_units(amount: str, decimals: int) -> str | None:
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return None
    scaled = value * (Decimal(10) ** decimals)
    if scaled <= 0 or scaled != scaled.to_integral_value():
        return None
    return str(int(scaled))


def configured_direct_base_usdc_offer() -> dict | None:
    """Return a direct offer only for buyer-broadcast native-USDC on Base."""
    if os.getenv(DIRECT_ENABLE_ENV) != "1":
        return None
    plan = configured_route_intelligence_plan()
    if plan is None:
        return None

    network = (os.getenv(NETWORK_ENV) or "").strip()
    asset = _address(ASSET_ENV)
    asset_code = (os.getenv(ASSET_CODE_ENV) or "").strip()
    decimals = _configured_decimals()
    pay_to = _address(PAY_TO_ENV)

    if network != BASE_NETWORK:
        return None
    if asset is None or asset.lower() != BASE_USDC_ADDRESS:
        return None
    if asset_code != "USDC" or asset_code != plan.currency:
        return None
    if decimals != BASE_USDC_DECIMALS or pay_to is None:
        return None

    atomic_amount = _base_units(plan.customer_price, decimals)
    if atomic_amount is None:
        return None

    return {
        "payment_method": DIRECT_PAYMENT_METHOD,
        "network": BASE_NETWORK,
        "chain_id": BASE_CHAIN_ID,
        "asset": asset.lower(),
        "asset_code": "USDC",
        "asset_decimals": BASE_USDC_DECIMALS,
        "token_name": USDC_TOKEN_NAME,
        "token_version": USDC_TOKEN_VERSION,
        "pay_to": pay_to.lower(),
        "atomic_amount": atomic_amount,
        "quote_amount": plan.customer_price,
        "quote_currency": plan.currency,
        "buyer_pays_gas": True,
        "aion_broadcasts_transaction": False,
        "facilitator_required": False,
        "rpc_endpoint": BASE_RPC_URL,
    }


def direct_base_usdc_readiness() -> dict:
    plan = configured_route_intelligence_plan()
    offer = configured_direct_base_usdc_offer()
    reasons: list[str] = []

    if plan is None:
        reasons.append("route_intelligence_quote_not_configured")
    if os.getenv(DIRECT_ENABLE_ENV) != "1":
        reasons.append("direct_base_usdc_disabled")
    if (os.getenv(NETWORK_ENV) or "").strip() != BASE_NETWORK:
        reasons.append("direct_payment_network_not_base_mainnet")
    asset = _address(ASSET_ENV)
    if asset is None or asset.lower() != BASE_USDC_ADDRESS:
        reasons.append("direct_payment_asset_not_native_base_usdc")
    if (os.getenv(ASSET_CODE_ENV) or "").strip() != "USDC":
        reasons.append("direct_payment_asset_code_not_usdc")
    if _configured_decimals() != BASE_USDC_DECIMALS:
        reasons.append("direct_payment_asset_decimals_not_6")
    if _address(PAY_TO_ENV) is None:
        reasons.append("pay_to_address_invalid")

    activation_ready_except_master_gate = bool(offer is not None)
    if not economic_kernel.REAL_MONEY_EXECUTION_ENABLED:
        reasons.append("real_money_execution_disabled")

    return {
        "product_sku": "aion.verified.route_intelligence.v1",
        "payment_method": DIRECT_PAYMENT_METHOD,
        "payment_flow": "upfront",
        "transfer_method": "eip3009_transferWithAuthorization",
        "network": BASE_NETWORK,
        "chain_id": BASE_CHAIN_ID,
        "asset": BASE_USDC_ADDRESS,
        "asset_code": "USDC",
        "buyer_pays_gas": True,
        "aion_pays_gas": False,
        "aion_broadcasts_transaction": False,
        "facilitator_required": False,
        "facilitator_credentials_required": False,
        "purchase_bound_nonce_required": True,
        "pay_to_address_configured": _address(PAY_TO_ENV) is not None,
        "payment_offer_configured": offer is not None,
        "real_money_execution_enabled": bool(
            economic_kernel.REAL_MONEY_EXECUTION_ENABLED
        ),
        "activation_ready_except_master_gate": activation_ready_except_master_gate,
        "launch_ready": bool(
            activation_ready_except_master_gate
            and economic_kernel.REAL_MONEY_EXECUTION_ENABLED
        ),
        "blocking_reasons": list(dict.fromkeys(reasons)),
        "rpc_endpoint": BASE_RPC_URL,
        "proof_headers": {
            "purchase_id": "X-AION-PURCHASE-ID",
            "transaction_hash": "X-AION-PAYMENT-TX",
        },
        "truth_boundaries": {
            "buyer_signs_and_broadcasts_payment": True,
            "buyer_or_buyer_selected_broadcaster_pays_gas": True,
            "aion_only_reads_chain_in_payment_verifier": True,
            "transaction_hash_is_not_payment_until_chain_verification": True,
            "purchase_identity_is_bound_into_signed_eip3009_nonce": True,
            "safe_block_required_before_result_release": True,
            "one_transaction_can_entitle_at_most_one_purchase": True,
        },
    }


def purchase_authorization_nonce(purchase_id: str, result_digest: str) -> str:
    """Derive a 32-byte purchase-bound EIP-3009 nonce.

    UUIDv4 purchase identity plus the frozen result digest gives each purchase a
    distinct authorization identity. SHA-256 is used only as deterministic
    nonce derivation; USDC itself verifies the EIP-712 signature on-chain.
    """
    material = (
        "aion-direct-base-usdc-eip3009-v1|"
        + str(purchase_id or "").strip().lower()
        + "|"
        + str(result_digest or "").strip().lower()
    ).encode("ascii")
    return "0x" + hashlib.sha256(material).hexdigest()


def _authorization_window(
    prepared_at: datetime, expires_at: datetime
) -> tuple[int, int]:
    prepared = int(_aware(prepared_at).timestamp())
    expires = int(_aware(expires_at).timestamp())
    return max(0, prepared - 30), expires


def direct_payment_requirements(
    *,
    purchase_id: str,
    result_digest: str,
    prepared_at: datetime,
    expires_at: datetime,
) -> dict:
    offer = configured_direct_base_usdc_offer()
    if offer is None:
        raise ValueError("direct Base USDC offer is not configured")

    nonce = purchase_authorization_nonce(purchase_id, result_digest)
    valid_after, valid_before = _authorization_window(prepared_at, expires_at)
    return {
        "payment_method": DIRECT_PAYMENT_METHOD,
        "payment_flow": "upfront",
        "transfer_method": "eip3009_transferWithAuthorization",
        "network": offer["network"],
        "chain_id": offer["chain_id"],
        "asset": offer["asset"],
        "asset_code": offer["asset_code"],
        "asset_decimals": offer["asset_decimals"],
        "amount": offer["atomic_amount"],
        "quote_amount": offer["quote_amount"],
        "quote_currency": offer["quote_currency"],
        "pay_to": offer["pay_to"],
        "buyer_pays_gas": True,
        "aion_broadcasts_transaction": False,
        "facilitator_required": False,
        "purchase_id": purchase_id,
        "prepared_result_digest": result_digest,
        "prepared_at": _aware(prepared_at).isoformat(),
        "expires_at": _aware(expires_at).isoformat(),
        "authorization": {
            "type": "TransferWithAuthorization",
            "domain": {
                "name": USDC_TOKEN_NAME,
                "version": USDC_TOKEN_VERSION,
                "chainId": BASE_CHAIN_ID,
                "verifyingContract": offer["asset"],
            },
            "message": {
                "from": "BUYER_EVM_ADDRESS",
                "to": offer["pay_to"],
                "value": offer["atomic_amount"],
                "validAfter": str(valid_after),
                "validBefore": str(valid_before),
                "nonce": nonce,
            },
            "contract_call": {
                "to": offer["asset"],
                "function": (
                    "transferWithAuthorization(address,address,uint256,uint256,"
                    "uint256,bytes32,uint8,bytes32,bytes32)"
                ),
                "selector": TRANSFER_WITH_AUTHORIZATION_SELECTOR,
                "caller_pays_gas": True,
            },
        },
        "submit_proof_with": {
            "purchase_id_header": "X-AION-PURCHASE-ID",
            "transaction_hash_header": "X-AION-PAYMENT-TX",
        },
    }


def _rpc(method: str, params: list) -> tuple[str, object | None]:
    result, data = fetch_json(
        "POST",
        BASE_RPC_URL,
        payload={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        policy=_RPC_POLICY,
    )
    if result.error or result.status != 200 or not isinstance(data, dict):
        return "transport_error", None
    if data.get("jsonrpc") != "2.0" or data.get("id") != 1:
        return "malformed_response", None
    if data.get("error") is not None:
        return "rpc_error", data.get("error")
    if "result" not in data:
        return "malformed_response", None
    return "ok", data.get("result")


def _topic_address(value: object) -> str | None:
    if not isinstance(value, str) or not _TOPIC.fullmatch(value):
        return None
    return "0x" + value[-40:].lower()


def _hex_int(value: object) -> int | None:
    if not isinstance(value, str) or not _HEX_QUANTITY.fullmatch(value):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _abi_address(word: str) -> str | None:
    if len(word) != 64 or word[:24] != "0" * 24:
        return None
    value = "0x" + word[-40:].lower()
    return value if _EVM_ADDRESS.fullmatch(value) else None


def _decode_transfer_with_authorization(value: object) -> dict | None:
    if not isinstance(value, str) or not _CALLDATA.fullmatch(value):
        return None
    raw = value.lower()
    # 4-byte selector + nine static 32-byte ABI words.
    if len(raw) != 2 + 8 + (9 * 64):
        return None
    if raw[:10] != TRANSFER_WITH_AUTHORIZATION_SELECTOR:
        return None
    payload = raw[10:]
    words = [payload[index : index + 64] for index in range(0, len(payload), 64)]
    if len(words) != 9:
        return None
    payer = _abi_address(words[0])
    pay_to = _abi_address(words[1])
    if payer is None or pay_to is None:
        return None
    try:
        amount = int(words[2], 16)
        valid_after = int(words[3], 16)
        valid_before = int(words[4], 16)
        v = int(words[6], 16)
    except ValueError:
        return None
    if v > 255:
        return None
    nonce = "0x" + words[5]
    if not _BYTES32.fullmatch(nonce):
        return None
    return {
        "payer": payer,
        "pay_to": pay_to,
        "amount": amount,
        "valid_after": valid_after,
        "valid_before": valid_before,
        "nonce": nonce.lower(),
        "v": v,
        "r": "0x" + words[7],
        "s": "0x" + words[8],
    }


def verify_direct_base_usdc_transfer(
    tx_hash: str,
    *,
    expected_asset: str,
    expected_pay_to: str,
    expected_atomic_amount: str,
    expected_authorization_nonce: str,
    expected_valid_after: int,
    expected_valid_before: int,
) -> dict:
    """Read Base and classify one buyer-broadcast EIP-3009 USDC payment.

    Successful USDC contract execution is the cryptographic signature check.
    This function never signs, broadcasts or pays gas.
    """
    normalized_tx = str(tx_hash or "").strip().lower()
    if not _TX_HASH.fullmatch(normalized_tx):
        return {"outcome": "rejected", "code": "payment_transaction_hash_invalid"}

    asset = str(expected_asset or "").lower()
    pay_to = str(expected_pay_to or "").lower()
    nonce = str(expected_authorization_nonce or "").lower()
    if (
        asset != BASE_USDC_ADDRESS
        or not _EVM_ADDRESS.fullmatch(pay_to)
        or not _BYTES32.fullmatch(nonce)
    ):
        return {"outcome": "rejected", "code": "direct_payment_expectation_invalid"}
    if not str(expected_atomic_amount).isdigit() or int(expected_atomic_amount) <= 0:
        return {"outcome": "rejected", "code": "direct_payment_amount_invalid"}
    if expected_valid_before <= expected_valid_after:
        return {"outcome": "rejected", "code": "direct_payment_window_invalid"}

    status, chain_id = _rpc("eth_chainId", [])
    if status != "ok":
        return {"outcome": "ambiguous", "code": "base_rpc_unavailable"}
    if str(chain_id).lower() != BASE_CHAIN_ID_HEX:
        return {"outcome": "ambiguous", "code": "base_rpc_chain_mismatch"}

    status, transaction = _rpc("eth_getTransactionByHash", [normalized_tx])
    if status != "ok":
        return {"outcome": "ambiguous", "code": "base_rpc_unavailable"}
    if transaction is None:
        return {"outcome": "pending", "code": "payment_transaction_not_found"}
    if not isinstance(transaction, dict):
        return {"outcome": "ambiguous", "code": "payment_transaction_malformed"}
    if str(transaction.get("hash") or "").lower() != normalized_tx:
        return {"outcome": "ambiguous", "code": "payment_transaction_hash_mismatch"}
    if str(transaction.get("to") or "").lower() != asset:
        return {"outcome": "rejected", "code": "payment_not_sent_to_usdc_contract"}

    authorization = _decode_transfer_with_authorization(transaction.get("input"))
    if authorization is None:
        return {
            "outcome": "rejected",
            "code": "payment_not_purchase_bound_eip3009_transfer",
        }
    if authorization["pay_to"] != pay_to:
        return {"outcome": "rejected", "code": "payment_recipient_mismatch"}
    if authorization["amount"] != int(expected_atomic_amount):
        return {"outcome": "rejected", "code": "payment_amount_mismatch"}
    if authorization["nonce"] != nonce:
        return {"outcome": "rejected", "code": "payment_purchase_nonce_mismatch"}
    if authorization["valid_after"] != int(expected_valid_after):
        return {"outcome": "rejected", "code": "payment_valid_after_mismatch"}
    if authorization["valid_before"] != int(expected_valid_before):
        return {"outcome": "rejected", "code": "payment_valid_before_mismatch"}

    status, receipt = _rpc("eth_getTransactionReceipt", [normalized_tx])
    if status != "ok":
        return {"outcome": "ambiguous", "code": "base_rpc_unavailable"}
    if receipt is None:
        return {"outcome": "pending", "code": "payment_transaction_not_mined"}
    if not isinstance(receipt, dict):
        return {"outcome": "ambiguous", "code": "payment_receipt_malformed"}
    if str(receipt.get("transactionHash") or "").lower() != normalized_tx:
        return {"outcome": "ambiguous", "code": "payment_receipt_hash_mismatch"}
    if str(receipt.get("status") or "").lower() != "0x1":
        return {"outcome": "rejected", "code": "payment_transaction_failed"}

    receipt_block_number = _hex_int(receipt.get("blockNumber"))
    receipt_block_hash = str(receipt.get("blockHash") or "").lower()
    if receipt_block_number is None or not _TX_HASH.fullmatch(receipt_block_hash):
        return {"outcome": "ambiguous", "code": "payment_receipt_block_invalid"}

    status, safe_block = _rpc("eth_getBlockByNumber", ["safe", False])
    if status != "ok" or not isinstance(safe_block, dict):
        return {"outcome": "ambiguous", "code": "base_safe_head_unavailable"}
    safe_number = _hex_int(safe_block.get("number"))
    if safe_number is None:
        return {"outcome": "ambiguous", "code": "base_safe_head_malformed"}
    if receipt_block_number > safe_number:
        return {"outcome": "pending", "code": "payment_not_safe_yet"}

    status, payment_block = _rpc(
        "eth_getBlockByNumber", [receipt.get("blockNumber"), False]
    )
    if status != "ok" or not isinstance(payment_block, dict):
        return {"outcome": "ambiguous", "code": "payment_block_unavailable"}
    if str(payment_block.get("hash") or "").lower() != receipt_block_hash:
        return {"outcome": "ambiguous", "code": "payment_block_hash_mismatch"}
    block_timestamp = _hex_int(payment_block.get("timestamp"))
    if block_timestamp is None:
        return {"outcome": "ambiguous", "code": "payment_block_timestamp_invalid"}
    if not (authorization["valid_after"] < block_timestamp < authorization["valid_before"]):
        return {"outcome": "rejected", "code": "payment_outside_authorization_window"}

    logs = receipt.get("logs")
    if not isinstance(logs, list):
        return {"outcome": "ambiguous", "code": "payment_receipt_logs_malformed"}

    transfers: list[dict] = []
    authorizations_used: list[dict] = []
    for log in logs:
        if not isinstance(log, dict):
            continue
        if str(log.get("address") or "").lower() != asset:
            continue
        topics = log.get("topics")
        if not isinstance(topics, list) or not topics:
            continue
        topic0 = str(topics[0] or "").lower()
        if topic0 == ERC20_TRANSFER_TOPIC0 and len(topics) >= 3:
            payer = _topic_address(topics[1])
            recipient = _topic_address(topics[2])
            raw_amount = log.get("data")
            if (
                payer is not None
                and recipient is not None
                and isinstance(raw_amount, str)
                and raw_amount.startswith("0x")
            ):
                try:
                    amount = int(raw_amount, 16)
                except ValueError:
                    continue
                transfers.append(
                    {"payer": payer, "recipient": recipient, "amount": amount}
                )
        elif topic0 == AUTHORIZATION_USED_TOPIC0 and len(topics) >= 3:
            authorizer = _topic_address(topics[1])
            used_nonce = str(topics[2] or "").lower()
            if authorizer is not None and _BYTES32.fullmatch(used_nonce):
                authorizations_used.append(
                    {"authorizer": authorizer, "nonce": used_nonce}
                )

    payer = authorization["payer"]
    exact_transfers = [
        item
        for item in transfers
        if item["payer"] == payer
        and item["recipient"] == pay_to
        and item["amount"] == int(expected_atomic_amount)
    ]
    if len(exact_transfers) != 1:
        return {
            "outcome": "rejected" if not exact_transfers else "ambiguous",
            "code": (
                "required_usdc_transfer_not_found"
                if not exact_transfers
                else "multiple_matching_usdc_transfers"
            ),
        }

    exact_authorizations = [
        item
        for item in authorizations_used
        if item["authorizer"] == payer and item["nonce"] == nonce
    ]
    if len(exact_authorizations) != 1:
        return {
            "outcome": "rejected" if not exact_authorizations else "ambiguous",
            "code": (
                "required_authorization_used_event_not_found"
                if not exact_authorizations
                else "multiple_matching_authorization_used_events"
            ),
        }

    broadcaster = str(transaction.get("from") or "").lower()
    if not _EVM_ADDRESS.fullmatch(broadcaster):
        broadcaster = None

    evidence = {
        "transaction": normalized_tx,
        "network": BASE_NETWORK,
        "chain_id": BASE_CHAIN_ID,
        "asset": asset,
        "pay_to": pay_to,
        "payer": payer,
        "broadcaster": broadcaster,
        "amount": str(expected_atomic_amount),
        "authorization_nonce": nonce,
        "authorization_valid_after": authorization["valid_after"],
        "authorization_valid_before": authorization["valid_before"],
        "block_number": receipt_block_number,
        "block_hash": receipt_block_hash,
        "block_timestamp": block_timestamp,
        "finality": "safe",
        "buyer_or_buyer_selected_broadcaster_paid_gas": True,
        "aion_broadcast_transaction": False,
        "facilitator_used": False,
    }
    return {"outcome": "settled", **evidence, "response": evidence}
