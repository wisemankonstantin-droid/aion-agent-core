"""Truth-preserving x402 auth-capture escrow contract for a future live rail.

This module performs no network call and contains no wallet, facilitator secret,
or payment capability. It defines the evidence contract that a separately
reviewed production receipt resolver must satisfy before Economic Kernel state
may advance.

Key truth boundaries:
- x402 ``verify`` is authorization evidence only, never a reserve;
- a reserve exists only after successful auth-capture ``authorize`` settlement
  in ``escrow`` flow;
- every receipt is bound to the immutable EconomicOperation amount + currency
  before the generic Economic Kernel transition seam is invoked;
- a pre-capture ``void`` clears the active reserve and records rail-verified
  release evidence without pretending customer settlement occurred.
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

    return {
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


class X402EscrowReceiptVerifier:
    """Resolver seam only; never pass it directly as the Economic Kernel adapter.

    The resolver must authenticate facilitator/network evidence independently.
    Requester-supplied receipt JSON is not trusted evidence. Rail-specific
    wrappers below bind verified receipt material to the immutable quote before
    creating the narrow adapter object consumed by Economic Kernel.
    """

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

    def resolve(self, evidence_reference: str, *, lifecycle: str) -> dict:
        if not self.enabled:
            raise economic_kernel.EconomicKernelError(
                409,
                "real_money_adapter_disabled",
                "x402 escrow receipt verifier is disabled",
            )
        if self.resolver_authority != "trusted_facilitator_receipt_resolver":
            raise economic_kernel.EconomicKernelError(
                409,
                "unverified_economic_evidence",
                "x402 receipt resolver authority is not trusted",
            )
        try:
            receipt = _canonical_receipt(
                self._receipt_resolver(evidence_reference),
                expected_lifecycle=lifecycle,
            )
        except X402EscrowContractError as exc:
            raise economic_kernel.EconomicKernelError(409, exc.code, exc.message) from exc
        receipt["digest"] = _digest(receipt)
        return receipt


class _BoundReceiptAdapter:
    """One-transition adapter created only after quote/receipt material matches."""

    enabled = True

    def __init__(self, transition: str, receipt: dict):
        self._transition = transition
        self._receipt = receipt

    def verify(self, transition: str, evidence_reference: str) -> dict:
        _ = evidence_reference
        if transition != self._transition:
            raise economic_kernel.EconomicKernelError(
                409,
                "x402_lifecycle_mismatch",
                "Bound x402 receipt cannot authorize a different economic transition",
            )
        return {
            "authority": "payment_rail_verified",
            "digest": self._receipt["digest"],
        }


def _operation_for_requester(
    db: Session,
    *,
    requester_agent_id: int,
    operation_id: str,
    lock: bool = False,
) -> models.EconomicOperation:
    operation_id = economic_kernel._valid_operation_id(operation_id)
    canonical_id = economic_kernel._canonical_agent_id(db, requester_agent_id)
    statement = select(models.EconomicOperation).where(
        models.EconomicOperation.operation_id == operation_id
    )
    row = db.scalar(statement.with_for_update() if lock else statement)
    if row is None:
        raise economic_kernel.EconomicKernelError(404, "economic_operation_not_found", "Economic operation not found")
    if row.requester_agent_id != canonical_id:
        raise economic_kernel.EconomicKernelError(403, "economic_operation_forbidden", "Economic operation belongs to another logical requester")
    return row


def _bind_receipt_to_amount(receipt: dict, *, amount: str, currency: str) -> None:
    if receipt.get("quote_currency") != currency or receipt.get("quote_amount") != amount:
        raise economic_kernel.EconomicKernelError(
            409,
            "x402_receipt_amount_mismatch",
            "x402 receipt must match the immutable economic amount and currency",
        )


def authorize_payment_operation(
    db: Session,
    *,
    requester_agent_id: int,
    operation_id: str,
    idempotency_key: str,
    verifier: X402EscrowReceiptVerifier,
    evidence_reference: str,
) -> dict:
    """Bind x402 verification to payment_authorized, never funds_reserved."""
    row = _operation_for_requester(
        db,
        requester_agent_id=requester_agent_id,
        operation_id=operation_id,
    )
    receipt = verifier.resolve(evidence_reference, lifecycle="verify")
    _bind_receipt_to_amount(receipt, amount=row.customer_price, currency=row.currency)
    return economic_kernel.apply_economic_transition(
        db,
        requester_agent_id=requester_agent_id,
        operation_id=operation_id,
        to_state="payment_authorized",
        idempotency_key=idempotency_key,
        adapter=_BoundReceiptAdapter("payment_authorized", receipt),
        evidence_reference=evidence_reference,
        amount=row.customer_price,
        currency=row.currency,
    )


def reserve_funds_operation(
    db: Session,
    *,
    requester_agent_id: int,
    operation_id: str,
    idempotency_key: str,
    verifier: X402EscrowReceiptVerifier,
    evidence_reference: str,
) -> dict:
    """Create reserve only from successful x402 auth-capture authorize settle."""
    row = _operation_for_requester(
        db,
        requester_agent_id=requester_agent_id,
        operation_id=operation_id,
    )
    if row.authorized_amount is None:
        raise economic_kernel.EconomicKernelError(
            409,
            "payment_not_authorized",
            "x402 reserve requires prior verified payment authorization",
        )
    receipt = verifier.resolve(evidence_reference, lifecycle="authorize")
    _bind_receipt_to_amount(receipt, amount=row.authorized_amount, currency=row.currency)
    return economic_kernel.apply_economic_transition(
        db,
        requester_agent_id=requester_agent_id,
        operation_id=operation_id,
        to_state="funds_reserved",
        idempotency_key=idempotency_key,
        adapter=_BoundReceiptAdapter("funds_reserved", receipt),
        evidence_reference=evidence_reference,
        amount=row.authorized_amount,
        currency=row.currency,
    )


def capture_settlement_operation(
    db: Session,
    *,
    requester_agent_id: int,
    operation_id: str,
    idempotency_key: str,
    verifier: X402EscrowReceiptVerifier,
    evidence_reference: str,
) -> dict:
    """Record customer settlement only from successful x402 capture evidence."""
    row = _operation_for_requester(
        db,
        requester_agent_id=requester_agent_id,
        operation_id=operation_id,
    )
    receipt = verifier.resolve(evidence_reference, lifecycle="capture")
    _bind_receipt_to_amount(receipt, amount=row.customer_price, currency=row.currency)
    return economic_kernel.apply_economic_transition(
        db,
        requester_agent_id=requester_agent_id,
        operation_id=operation_id,
        to_state="settled",
        idempotency_key=idempotency_key,
        adapter=_BoundReceiptAdapter("settled", receipt),
        evidence_reference=evidence_reference,
        amount=row.customer_price,
        currency=row.currency,
    )


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
        "receipt_amount_and_currency_binding_required": True,
        "generic_unbound_adapter_allowed": False,
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
    verifier: X402EscrowReceiptVerifier,
    evidence_reference: str,
) -> dict:
    """Void a verified x402 hold without pretending settlement occurred.

    V1 supports full pre-capture void only. Historical hold evidence remains in
    the transition log; ``reserved_amount`` is cleared after verified release so
    canonical status no longer claims an active reserve. Revenue remains zero.
    """
    if not economic_kernel.REAL_MONEY_EXECUTION_ENABLED or not verifier.enabled:
        raise economic_kernel.EconomicKernelError(
            409,
            "real_money_adapter_disabled",
            "Real-money x402 escrow adapter is disabled",
        )

    key = economic_kernel._valid_idempotency(idempotency_key)
    row = _operation_for_requester(
        db,
        requester_agent_id=requester_agent_id,
        operation_id=operation_id,
        lock=True,
    )
    receipt = verifier.resolve(evidence_reference, lifecycle="void")
    release_amount = row.reserved_amount

    material = {
        "to_state": "cancelled",
        "reason_code": "x402_escrow_void_verified",
        "amount": release_amount,
        "currency": row.currency,
        "evidence_digest": receipt["digest"],
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
    _bind_receipt_to_amount(receipt, amount=release_amount, currency=row.currency)

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
        evidence_digest=receipt["digest"],
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
