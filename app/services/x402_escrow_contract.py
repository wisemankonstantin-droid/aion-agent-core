"""Truth-preserving x402 auth-capture escrow contract for a future live adapter.

This module performs no network call and contains no wallet, facilitator secret,
or payment capability. It defines the evidence contract that a separately
reviewed production rail adapter must satisfy before Economic Kernel state may
advance.

Key truth boundary: x402 verification is authorization evidence only. It is not
a reserve. A reserve exists only after a successful auth-capture ``authorize``
settle in ``escrow`` flow.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from . import economic_kernel


CONTRACT_VERSION = "x402_auth_capture_escrow_v1"
PROTOCOL = "x402"
PROTOCOL_VERSION = "2"
SCHEME = "auth-capture"
PAYMENT_FLOW = "escrow"
_SAFE_TEXT = re.compile(r"^[\x21-\x7e]{1,240}$")

# Economic Kernel transition -> x402 lifecycle evidence required.
_REQUIRED_LIFECYCLE = {
    "payment_authorized": "verify",
    "funds_reserved": "authorize",
    "settled": "capture",
    # Used only by ``void_reserved_operation``. The generic Economic Kernel
    # reserve_released transition remains the post-settlement unused-reserve path.
    "reserve_released": "void",
}


class X402EscrowContractError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _safe_text(value: object, field: str) -> str:
    text = str(value or "")
    if not _SAFE_TEXT.fullmatch(text):
        raise X402EscrowContractError(
            "invalid_x402_receipt",
            f"{field} must be bounded printable ASCII",
        )
    return text


def _canonical_receipt(receipt: object, *, expected_lifecycle: str) -> dict:
    if not isinstance(receipt, dict):
        raise X402EscrowContractError(
            "invalid_x402_receipt", "Trusted receipt resolver must return an object"
        )
    if receipt.get("protocol") != PROTOCOL:
        raise X402EscrowContractError("invalid_x402_receipt", "Receipt protocol is not x402")
    if str(receipt.get("protocol_version") or "") != PROTOCOL_VERSION:
        raise X402EscrowContractError("invalid_x402_receipt", "Receipt protocol version is not x402 v2")
    if receipt.get("scheme") != SCHEME:
        raise X402EscrowContractError("invalid_x402_receipt", "Receipt scheme is not auth-capture")
    if receipt.get("payment_flow") != PAYMENT_FLOW:
        raise X402EscrowContractError("invalid_x402_receipt", "Receipt payment flow is not escrow")
    if receipt.get("lifecycle_operation") != expected_lifecycle:
        raise X402EscrowContractError(
            "x402_lifecycle_mismatch",
            f"Expected x402 {expected_lifecycle} evidence",
        )
    if receipt.get("success") is not True:
        raise X402EscrowContractError("x402_operation_not_successful", "x402 lifecycle operation did not succeed")

    try:
        currency = economic_kernel.canonical_currency(str(receipt.get("quote_currency") or ""))
        _, amount = economic_kernel.canonical_money(str(receipt.get("quote_amount") or ""))
    except economic_kernel.EconomicKernelError as exc:
        raise X402EscrowContractError("invalid_x402_receipt", exc.message) from exc

    canonical = {
        "protocol": PROTOCOL,
        "protocol_version": PROTOCOL_VERSION,
        "scheme": SCHEME,
        "payment_flow": PAYMENT_FLOW,
        "lifecycle_operation": expected_lifecycle,
        "success": True,
        "payment_id": _safe_text(receipt.get("payment_id"), "payment_id"),
        "network": _safe_text(receipt.get("network"), "network"),
        "asset": _safe_text(receipt.get("asset"), "asset"),
        "rail_reference": _safe_text(receipt.get("rail_reference"), "rail_reference"),
        "quote_currency": currency,
        "quote_amount": amount,
    }
    return canonical


class X402EscrowEvidenceAdapter:
    """Adapter seam over a trusted receipt resolver, with no transport inside.

    ``receipt_resolver`` is deliberately injected. A future production adapter
    must independently authenticate facilitator/network evidence before returning
    a receipt. This contract never treats requester-supplied JSON as verified.
    """

    authority = "payment_rail_verified"

    def __init__(
        self,
        receipt_resolver: Callable[[str], dict],
        *,
        enabled: bool = False,
        resolver_authority: str = "",
    ):
        self._receipt_resolver = receipt_resolver
        self.enabled = bool(enabled)
        self.resolver_authority = resolver_authority

    def verify(self, transition: str, evidence_reference: str) -> dict:
        if not self.enabled:
            raise economic_kernel.EconomicKernelError(
                409,
                "real_money_adapter_disabled",
                "x402 escrow evidence adapter is disabled",
            )
        if self.resolver_authority != "trusted_facilitator_receipt_resolver":
            raise economic_kernel.EconomicKernelError(
                409,
                "unverified_economic_evidence",
                "x402 receipt resolver authority is not trusted",
            )
        lifecycle = _REQUIRED_LIFECYCLE.get(transition)
        if lifecycle is None:
            raise economic_kernel.EconomicKernelError(
                409,
                "unsupported_x402_transition",
                "Economic transition has no x402 escrow evidence mapping",
            )
        try:
            receipt = _canonical_receipt(
                self._receipt_resolver(evidence_reference),
                expected_lifecycle=lifecycle,
            )
        except X402EscrowContractError as exc:
            raise economic_kernel.EconomicKernelError(
                409,
                exc.code,
                exc.message,
            ) from exc
        return {
            "authority": self.authority,
            "digest": _digest(receipt),
            "lifecycle_operation": lifecycle,
            "quote_currency": receipt["quote_currency"],
            "quote_amount": receipt["quote_amount"],
            "payment_id": receipt["payment_id"],
        }


def x402_escrow_readiness() -> dict:
    """Static readiness truth. No production rail is activated by this module."""
    return {
        "contract_version": CONTRACT_VERSION,
        "protocol": PROTOCOL,
        "protocol_version": PROTOCOL_VERSION,
        "scheme": SCHEME,
        "payment_flow": PAYMENT_FLOW,
        "verify_semantics": "authorization_evidence_only_not_funds_reserved",
        "reserve_semantics": "successful_auth_capture_authorize_settle_only",
        "capture_semantics": "successful_auth_capture_capture_settle_only",
        "void_semantics": "successful_auth_capture_void_settle_only",
        "network_transport_implemented": False,
        "wallet_or_facilitator_secret_configured_here": False,
        "real_money_execution_enabled": bool(economic_kernel.REAL_MONEY_EXECUTION_ENABLED),
        "full_refund_after_capture_supported": False,
        "real_money_launch_ready": False,
    }


def void_reserved_operation(
    db: Session,
    *,
    requester_agent_id: int,
    operation_id: str,
    idempotency_key: str,
    adapter: X402EscrowEvidenceAdapter,
    evidence_reference: str,
) -> dict:
    """Void a verified x402 hold without pretending a settlement occurred.

    V1 supports full void only. The historical hold remains in the transition
    log; ``reserved_amount`` is cleared after verified release so the canonical
    operation status no longer claims an active reserve. Revenue remains zero.
    """
    if not economic_kernel.REAL_MONEY_EXECUTION_ENABLED or not adapter.enabled:
        raise economic_kernel.EconomicKernelError(
            409,
            "real_money_adapter_disabled",
            "Real-money x402 escrow adapter is disabled",
        )

    key = economic_kernel._valid_idempotency(idempotency_key)
    operation_id = economic_kernel._valid_operation_id(operation_id)
    canonical_id = economic_kernel._canonical_agent_id(db, requester_agent_id)
    row = db.scalar(
        select(models.EconomicOperation)
        .where(models.EconomicOperation.operation_id == operation_id)
        .with_for_update()
    )
    if row is None:
        raise economic_kernel.EconomicKernelError(404, "economic_operation_not_found", "Economic operation not found")
    if row.requester_agent_id != canonical_id:
        raise economic_kernel.EconomicKernelError(403, "economic_operation_forbidden", "Economic operation belongs to another logical requester")

    verified = adapter.verify("reserve_released", evidence_reference)
    if verified.get("authority") != "payment_rail_verified":
        raise economic_kernel.EconomicKernelError(409, "unverified_economic_evidence", "x402 void evidence is not rail-verified")
    digest = verified.get("digest")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise economic_kernel.EconomicKernelError(409, "unverified_economic_evidence", "x402 void evidence digest is invalid")

    release_amount = row.reserved_amount
    material = {
        "to_state": "cancelled",
        "reason_code": "x402_escrow_void_verified",
        "amount": release_amount,
        "currency": row.currency,
        "evidence_digest": digest,
    }
    transition_digest = _digest(material)
    existing = db.scalar(
        select(models.EconomicTransition).where(
            models.EconomicTransition.economic_operation_id == row.id,
            models.EconomicTransition.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.transition_digest != transition_digest:
            raise economic_kernel.EconomicKernelError(409, "idempotency_conflict", "Void idempotency key was used for different material")
        return economic_kernel.serialize_operation(db, row, idempotent_replay=True)

    if row.state not in {"funds_reserved", "execution_started"}:
        raise economic_kernel.EconomicKernelError(
            409,
            "illegal_economic_transition",
            f"Cannot void x402 reserve from {row.state}",
        )
    if release_amount is None or row.authorized_amount is None:
        raise economic_kernel.EconomicKernelError(409, "reserve_not_established", "Verified reserve is required before x402 void")
    if row.settlement_amount is not None:
        raise economic_kernel.EconomicKernelError(409, "settlement_already_recorded", "Captured settlement cannot be represented as a pre-capture void")
    if verified.get("quote_currency") != row.currency or verified.get("quote_amount") != release_amount:
        raise economic_kernel.EconomicKernelError(409, "x402_receipt_amount_mismatch", "x402 void receipt must match the immutable verified reserve")

    sequence = (
        db.scalar(
            select(func.max(models.EconomicTransition.sequence)).where(
                models.EconomicTransition.economic_operation_id == row.id
            )
        )
        or 0
    ) + 1
    now = datetime.now(timezone.utc)
    transition = models.EconomicTransition(
        transition_id=str(uuid.uuid4()),
        economic_operation_id=row.id,
        sequence=sequence,
        idempotency_key=key,
        transition_digest=transition_digest,
        from_state=row.state,
        to_state="cancelled",
        reason_code="x402_escrow_void_verified",
        evidence_authority="payment_rail_verified",
        evidence_digest=digest,
        amount=release_amount,
        currency=row.currency,
        created_at=now,
    )
    row.released_amount = release_amount
    row.reserved_amount = None
    row.adapter_state = "verified_adapter_evidence"
    row.state = "cancelled"
    row.updated_at = now
    db.add_all([row, transition])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise economic_kernel.EconomicKernelError(
            409,
            "economic_transition_conflict",
            "Concurrent x402 void transition conflict",
        ) from exc
    db.refresh(row)
    return economic_kernel.serialize_operation(db, row)
