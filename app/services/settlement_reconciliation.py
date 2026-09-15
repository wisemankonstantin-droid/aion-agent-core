"""Fail-closed recovery for uncertain x402 exact/upfront settlement.

Reconciliation never accepts or re-submits PAYMENT-SIGNATURE and never calls the
facilitator settle endpoint. It reads a fixed allowlisted Base JSON-RPC endpoint
and only promotes an uncertain purchase to entitlement after a finalized receipt
proves one exact configured ERC-20 Transfer(asset, payer, payTo, atomicAmount).
Unknown evidence remains pending/ambiguous; a finalized reverted transaction or a
finalized successful transaction with no qualifying exact transfer is a definite
failure. Multiple qualifying transfers remain ambiguous rather than being treated
as either entitlement or definite failure. The status surface never releases the
prepared result.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..payment_models import RouteIntelligencePurchase
from .safe_http import FetchPolicy, fetch_json


_BASE_NETWORKS = {
    "eip155:8453": {
        "rpc_url": "https://mainnet.base.org",
        "chain_id": "0x2105",
    },
    "eip155:84532": {
        "rpc_url": "https://sepolia.base.org",
        "chain_id": "0x14a34",
    },
}
_TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)
_TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TOPIC = re.compile(r"^0x[0-9a-fA-F]{64}$")
_HEX = re.compile(r"^0x[0-9a-fA-F]+$")
_PURCHASE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_MAX_RPC_BYTES = 128_000


class SettlementReconciliationError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: object) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_purchase_id(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _PURCHASE_ID.fullmatch(normalized):
        raise SettlementReconciliationError(
            404, "purchase_not_found", "Purchase was not found"
        )
    return normalized


def _purchase(db: Session, purchase_id: str) -> RouteIntelligencePurchase:
    canonical = _canonical_purchase_id(purchase_id)
    row = db.scalar(
        select(RouteIntelligencePurchase).where(
            RouteIntelligencePurchase.purchase_id == canonical
        )
    )
    if row is None:
        raise SettlementReconciliationError(
            404, "purchase_not_found", "Purchase was not found"
        )
    return row


def purchase_status_data(row: RouteIntelligencePurchase) -> dict:
    """Return buyer-safe durable state without releasing the paid result."""
    return {
        "purchase_id": row.purchase_id,
        "product_sku": row.product_sku,
        "state": row.state,
        "prepared_result_digest": row.result_digest,
        "network": row.network,
        "asset": row.asset,
        "asset_code": row.asset_code,
        "pay_to": row.pay_to,
        "atomic_amount": row.atomic_amount,
        "transaction": row.transaction_id,
        "settlement_evidence_digest": row.settlement_response_digest,
        "failure_code": row.failure_code,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "entitled_at": row.entitled_at.isoformat() if row.entitled_at else None,
        "result_released": False,
        "result_available_via_idempotent_signed_purchase_replay": row.state == "entitled",
        "reconciliation_retry_safe": row.state
        in {"settlement_pending", "settlement_ambiguous"},
        "truth_boundaries": {
            "status_or_reconciliation_creates_membership": False,
            "status_or_reconciliation_creates_vuo_or_adoption": False,
            "payment_signature_accepted_by_reconciliation": False,
            "facilitator_settlement_retried_by_reconciliation": False,
            "prepared_result_released_by_status": False,
        },
    }


def get_purchase_status(db: Session, purchase_id: str) -> dict:
    return purchase_status_data(_purchase(db, purchase_id))


def _rpc(url: str, method: str, params: list) -> tuple[object | None, str | None]:
    result, data = fetch_json(
        "POST",
        url,
        payload={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        policy=FetchPolicy(
            timeout_seconds=8.0,
            max_response_bytes=_MAX_RPC_BYTES,
            max_attempts=1,
            max_resolved_addresses=4,
            user_agent="AION-x402-Reconciliation/0.8.0",
        ),
    )
    if result.error:
        return None, "rpc_transport_unavailable"
    if result.status != 200 or not isinstance(data, dict):
        return None, "rpc_response_invalid"
    if data.get("jsonrpc") != "2.0" or data.get("id") != 1:
        return None, "rpc_response_invalid"
    if data.get("error") is not None:
        return None, "rpc_method_error"
    if "result" not in data:
        return None, "rpc_response_invalid"
    return data.get("result"), None


def _hex_int(value: object) -> int | None:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        return None
    try:
        return int(value, 16)
    except ValueError:
        return None


def _topic_address(value: object) -> str | None:
    if not isinstance(value, str) or not _TOPIC.fullmatch(value):
        return None
    body = value[2:]
    if body[:24].lower() != "0" * 24:
        return None
    return "0x" + body[-40:].lower()


def _matching_transfers(row: RouteIntelligencePurchase, receipt: dict) -> list[dict]:
    logs = receipt.get("logs")
    if not isinstance(logs, list):
        return []
    expected_asset = str(row.asset or "").lower()
    expected_to = str(row.pay_to or "").lower()
    expected_payer = str(row.payer or "").lower() or None
    if not _ADDRESS.fullmatch(expected_asset) or not _ADDRESS.fullmatch(expected_to):
        return []
    if expected_payer is not None and not _ADDRESS.fullmatch(expected_payer):
        return []
    try:
        expected_amount = int(str(row.atomic_amount))
    except ValueError:
        return []
    if expected_amount <= 0:
        return []

    matches = []
    for item in logs:
        if not isinstance(item, dict) or str(item.get("address") or "").lower() != expected_asset:
            continue
        topics = item.get("topics")
        if not isinstance(topics, list) or len(topics) < 3:
            continue
        if str(topics[0]).lower() != _TRANSFER_TOPIC:
            continue
        payer = _topic_address(topics[1])
        pay_to = _topic_address(topics[2])
        amount = _hex_int(item.get("data"))
        if payer is None or pay_to != expected_to or amount != expected_amount:
            continue
        if expected_payer is not None and payer != expected_payer:
            continue
        matches.append({"payer": payer, "log_index": item.get("logIndex")})
    return matches


def _resolve_finalized_chain_evidence(row: RouteIntelligencePurchase) -> dict:
    config = _BASE_NETWORKS.get(str(row.network or ""))
    if config is None:
        return {
            "outcome": "unresolved",
            "code": "reconciliation_network_not_allowlisted",
        }
    transaction = str(row.transaction_id or "").lower()
    if not _TX.fullmatch(transaction):
        return {
            "outcome": "unresolved",
            "code": "reconciliation_transaction_evidence_missing",
        }

    chain_id, error = _rpc(config["rpc_url"], "eth_chainId", [])
    if error or str(chain_id or "").lower() != config["chain_id"]:
        return {"outcome": "unresolved", "code": error or "reconciliation_chain_mismatch"}

    receipt, error = _rpc(
        config["rpc_url"], "eth_getTransactionReceipt", [transaction]
    )
    if error:
        return {"outcome": "unresolved", "code": error}
    if receipt is None:
        return {"outcome": "unresolved", "code": "transaction_not_mined"}
    if not isinstance(receipt, dict):
        return {"outcome": "unresolved", "code": "receipt_invalid"}
    if str(receipt.get("transactionHash") or "").lower() != transaction:
        return {"outcome": "unresolved", "code": "receipt_transaction_mismatch"}

    block_number = _hex_int(receipt.get("blockNumber"))
    block_hash = str(receipt.get("blockHash") or "").lower()
    if block_number is None or not _TX.fullmatch(block_hash):
        return {"outcome": "unresolved", "code": "receipt_block_evidence_invalid"}

    finalized, error = _rpc(
        config["rpc_url"], "eth_getBlockByNumber", ["finalized", False]
    )
    if error or not isinstance(finalized, dict):
        return {"outcome": "unresolved", "code": error or "finality_evidence_unavailable"}
    finalized_number = _hex_int(finalized.get("number"))
    if finalized_number is None or block_number > finalized_number:
        return {"outcome": "unresolved", "code": "transaction_not_finalized"}

    status = str(receipt.get("status") or "").lower()
    base_evidence = {
        "authority": "base_finalized_json_rpc_receipt",
        "network": row.network,
        "transaction": transaction,
        "block_number": hex(block_number),
        "block_hash": block_hash,
        "finalized_block_number": hex(finalized_number),
        "asset": str(row.asset).lower(),
        "pay_to": str(row.pay_to).lower(),
        "atomic_amount": str(row.atomic_amount),
    }
    if status == "0x0":
        return {
            "outcome": "failed",
            "code": "reconciliation_transaction_reverted",
            "evidence": {**base_evidence, "receipt_status": status},
        }
    if status != "0x1":
        return {"outcome": "unresolved", "code": "receipt_status_invalid"}

    transfers = _matching_transfers(row, receipt)
    if len(transfers) == 0:
        return {
            "outcome": "failed",
            "code": "reconciliation_exact_transfer_not_proven",
            "evidence": {**base_evidence, "receipt_status": status},
        }
    if len(transfers) > 1:
        return {
            "outcome": "unresolved",
            "code": "multiple_exact_transfers_ambiguous",
        }
    transfer = transfers[0]
    return {
        "outcome": "settled",
        "evidence": {
            **base_evidence,
            "receipt_status": status,
            "payer": transfer["payer"],
            "transfer_log_index": transfer["log_index"],
        },
    }


def reconcile_purchase(db: Session, purchase_id: str) -> dict:
    """Reconcile durable chain evidence without any second settlement attempt."""
    row = _purchase(db, purchase_id)
    if row.state in {"entitled", "settlement_failed"}:
        return {
            **purchase_status_data(row),
            "reconciliation": {"outcome": "terminal", "idempotent": True},
        }
    if row.state not in {"settlement_pending", "settlement_ambiguous"}:
        return {
            **purchase_status_data(row),
            "reconciliation": {
                "outcome": "not_applicable",
                "code": "purchase_has_no_reconcilable_transaction_state",
            },
        }

    resolved = _resolve_finalized_chain_evidence(row)
    if resolved["outcome"] == "unresolved":
        return {
            **purchase_status_data(row),
            "reconciliation": {
                "outcome": "unresolved",
                "code": resolved["code"],
            },
        }

    evidence = resolved["evidence"]
    now = _now()
    values = {
        "updated_at": now,
        "settlement_response_digest": _digest(
            {
                "previous_settlement_response_digest": row.settlement_response_digest,
                "reconciliation": evidence,
            }
        ),
    }
    if resolved["outcome"] == "settled":
        values.update(
            state="entitled",
            payer=evidence["payer"],
            entitled_at=now,
            failure_code=None,
            failure_detail=None,
        )
    else:
        values.update(
            state="settlement_failed",
            entitled_at=None,
            failure_code=str(resolved["code"])[:96],
            failure_detail="Finalized on-chain evidence did not establish the required exact transfer",
        )

    try:
        changed = db.execute(
            update(RouteIntelligencePurchase)
            .where(
                RouteIntelligencePurchase.id == row.id,
                RouteIntelligencePurchase.state.in_(
                    ["settlement_pending", "settlement_ambiguous"]
                ),
                RouteIntelligencePurchase.transaction_id == row.transaction_id,
            )
            .values(**values)
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise SettlementReconciliationError(
            409,
            "reconciliation_evidence_conflict",
            "Reconciliation evidence conflicts with an existing purchase",
        ) from exc

    fresh = _purchase(db, row.purchase_id)
    if changed.rowcount not in {0, 1}:
        raise SettlementReconciliationError(
            409, "reconciliation_state_conflict", "Reconciliation state conflict"
        )
    if changed.rowcount == 0 and fresh.state not in {"entitled", "settlement_failed"}:
        raise SettlementReconciliationError(
            409, "reconciliation_state_conflict", "Purchase changed during reconciliation"
        )
    return {
        **purchase_status_data(fresh),
        "reconciliation": {
            "outcome": "settled" if fresh.state == "entitled" else "failed",
            "idempotent": changed.rowcount == 0,
        },
    }
