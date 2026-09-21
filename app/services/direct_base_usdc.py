"""Buyer-funded direct Base USDC settlement verification.

The buyer broadcasts and pays gas for the USDC transfer. AION never signs or
broadcasts a money-moving transaction in this path. AION only reads Base
mainnet, verifies a canonical USDC Transfer event, records settlement evidence,
and releases the prepared result after the payment is safe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
BASE_RPC_URL = "https://mainnet.base.org"
BASE_NETWORK = "eip155:8453"
BASE_CHAIN_ID_HEX = "0x2105"
BASE_USDC_ADDRESS = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
BASE_USDC_DECIMALS = 6
ERC20_TRANSFER_TOPIC0 = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)

_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX_QUANTITY = re.compile(r"^0x(?:0|[1-9a-fA-F][0-9a-fA-F]*)$")
_TOPIC = re.compile(r"^0x[0-9a-fA-F]{64}$")

_RPC_POLICY = FetchPolicy(
    timeout_seconds=10.0,
    max_response_bytes=128_000,
    max_attempts=2,
    max_resolved_addresses=8,
    user_agent="AION-Base-USDC-Verify/0.8.0",
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
    """Return a direct-payment offer only for the fixed Base native-USDC path."""
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
        "payment_method": "direct_base_usdc_transfer",
        "network": BASE_NETWORK,
        "chain_id": 8453,
        "asset": asset.lower(),
        "asset_code": "USDC",
        "asset_decimals": BASE_USDC_DECIMALS,
        "pay_to": pay_to.lower(),
        "atomic_amount": atomic_amount,
        "quote_amount": plan.customer_price,
        "quote_currency": plan.currency,
        "buyer_pays_gas": True,
        "aion_broadcasts_transaction": False,
        "rpc_endpoint": BASE_RPC_URL,
    }


def direct_base_usdc_readiness() -> dict:
    product = configured_route_intelligence_plan()
    offer = configured_direct_base_usdc_offer()
    reasons: list[str] = []

    if product is None:
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
        "payment_method": "direct_base_usdc_transfer",
        "payment_flow": "upfront",
        "network": BASE_NETWORK,
        "chain_id": 8453,
        "asset": BASE_USDC_ADDRESS,
        "asset_code": "USDC",
        "buyer_pays_gas": True,
        "aion_pays_gas": False,
        "facilitator_required": False,
        "facilitator_credentials_required": False,
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
            "buyer_broadcasts_and_pays_gas": True,
            "aion_only_reads_chain_in_payment_verifier": True,
            "transaction_hash_is_not_payment_until_chain_verification": True,
            "safe_block_required_before_result_release": True,
            "one_transaction_can_entitle_at_most_one_purchase": True,
        },
    }


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
    return {
        "payment_method": "direct_base_usdc_transfer",
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
        "purchase_id": purchase_id,
        "prepared_result_digest": result_digest,
        "prepared_at": prepared_at.astimezone(timezone.utc).isoformat(),
        "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
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


def verify_direct_base_usdc_transfer(
    tx_hash: str,
    *,
    expected_asset: str,
    expected_pay_to: str,
    expected_atomic_amount: str,
    not_before: datetime,
    not_after: datetime,
) -> dict:
    """Read Base and classify one buyer-funded USDC transaction.

    This function never signs, broadcasts or pays gas.
    """
    normalized_tx = str(tx_hash or "").strip().lower()
    if not _TX_HASH.fullmatch(normalized_tx):
        return {
            "outcome": "rejected",
            "code": "payment_transaction_hash_invalid",
        }

    asset = str(expected_asset or "").lower()
    pay_to = str(expected_pay_to or "").lower()
    if asset != BASE_USDC_ADDRESS or not _EVM_ADDRESS.fullmatch(pay_to):
        return {
            "outcome": "rejected",
            "code": "direct_payment_expectation_invalid",
        }
    if not str(expected_atomic_amount).isdigit() or int(expected_atomic_amount) <= 0:
        return {
            "outcome": "rejected",
            "code": "direct_payment_amount_invalid",
        }

    status, chain_id = _rpc("eth_chainId", [])
    if status != "ok":
        return {"outcome": "ambiguous", "code": "base_rpc_unavailable"}
    if str(chain_id).lower() != BASE_CHAIN_ID_HEX:
        return {"outcome": "ambiguous", "code": "base_rpc_chain_mismatch"}

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

    start = not_before.astimezone(timezone.utc).timestamp()
    end = not_after.astimezone(timezone.utc).timestamp()
    # Small clock/inclusion tolerance avoids rejecting a legitimate transfer
    # because the service clock and sequencer timestamp differ by a few seconds.
    if block_timestamp < int(start) - 30:
        return {"outcome": "rejected", "code": "payment_predates_purchase"}
    if block_timestamp > int(end) + 120:
        return {"outcome": "rejected", "code": "payment_after_purchase_expiry"}

    logs = receipt.get("logs")
    if not isinstance(logs, list):
        return {"outcome": "ambiguous", "code": "payment_receipt_logs_malformed"}

    transfers_to_recipient: list[dict] = []
    for log in logs:
        if not isinstance(log, dict):
            continue
        if str(log.get("address") or "").lower() != asset:
            continue
        topics = log.get("topics")
        if not isinstance(topics, list) or len(topics) < 3:
            continue
        if str(topics[0] or "").lower() != ERC20_TRANSFER_TOPIC0:
            continue
        payer = _topic_address(topics[1])
        recipient = _topic_address(topics[2])
        if payer is None or recipient != pay_to:
            continue
        raw_amount = log.get("data")
        if not isinstance(raw_amount, str) or not raw_amount.startswith("0x"):
            continue
        try:
            amount = int(raw_amount, 16)
        except ValueError:
            continue
        transfers_to_recipient.append({"payer": payer, "amount": amount})

    exact = [
        item
        for item in transfers_to_recipient
        if item["amount"] == int(expected_atomic_amount)
    ]
    if not exact:
        return {
            "outcome": "rejected",
            "code": (
                "payment_amount_mismatch"
                if transfers_to_recipient
                else "required_usdc_transfer_not_found"
            ),
        }
    if len(exact) != 1:
        return {"outcome": "ambiguous", "code": "multiple_matching_usdc_transfers"}

    payer = exact[0]["payer"]
    if payer == "0x" + "0" * 40:
        return {"outcome": "rejected", "code": "payment_payer_invalid"}

    evidence = {
        "transaction": normalized_tx,
        "network": BASE_NETWORK,
        "chain_id": 8453,
        "asset": asset,
        "pay_to": pay_to,
        "payer": payer,
        "amount": str(expected_atomic_amount),
        "block_number": receipt_block_number,
        "block_hash": receipt_block_hash,
        "block_timestamp": block_timestamp,
        "finality": "safe",
        "buyer_paid_gas": True,
        "aion_broadcast_transaction": False,
    }
    return {
        "outcome": "settled",
        **evidence,
        "response": evidence,
    }
