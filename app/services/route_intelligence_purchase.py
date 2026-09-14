"""Prepared-result purchase lifecycle for AION-owned Route Intelligence.

The expensive/unstable part is deliberately before settlement: AION prepares a
bounded route result, freezes its digest, then asks for exact upfront payment.
After confirmed settlement the handler only releases that already-prepared
result. A raw PAYMENT-SIGNATURE is never persisted or echoed.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..payment_models import RouteIntelligencePurchase
from .cdp_x402_facilitator import FacilitatorSettlementError, settle_exact_upfront
from .paid_route_intelligence import ROUTE_INTELLIGENCE_SKU, configured_route_intelligence_plan
from .x402_exact_upfront import (
    ExactUpfrontError,
    build_exact_payment_required,
    configured_exact_upfront_offer,
    exact_payment_requirements,
)


PREPARATION_TTL_SECONDS = 15 * 60
MAX_PAYMENT_SIGNATURE_HEADER_BYTES = 24 * 1024
_ALLOWED_REQUEST_KEYS = {"need", "candidate_identifier"}
_SIGNATURE = re.compile(r"^0x[0-9a-fA-F]{130}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_NONCE = re.compile(r"^0x[0-9a-fA-F]{64}$")


class RouteIntelligencePurchaseError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _digest(value) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _validated_request(payload: object):
    if not isinstance(payload, dict) or set(payload) - _ALLOWED_REQUEST_KEYS:
        raise RouteIntelligencePurchaseError(
            422,
            "invalid_purchase_request",
            "Purchase request accepts only need and optional candidate_identifier",
        )
    # Import lazily to avoid commercial_router -> payment_routes -> purchase cycle.
    from .commercial_router import CommercialRoutePlanRequest

    plan = configured_route_intelligence_plan()
    if plan is None:
        raise RouteIntelligencePurchaseError(
            503, "paid_route_quote_not_configured", "Paid Route Intelligence quote is not configured"
        )
    material = dict(payload)
    material["currency"] = plan.currency
    try:
        request = CommercialRoutePlanRequest.model_validate(material)
    except ValidationError as exc:
        # Never surface rejected input: router validators intentionally replace
        # sensitive values with sentinels before validation, but this boundary
        # stays generic as a second privacy layer.
        raise RouteIntelligencePurchaseError(
            422, "invalid_purchase_request", "Purchase request failed bounded validation"
        ) from exc
    return request, {
        "need": request.need,
        "candidate_identifier": request.candidate_identifier,
    }


def _latest_for_request(db: Session, request_digest: str) -> RouteIntelligencePurchase | None:
    return db.scalar(
        select(RouteIntelligencePurchase)
        .where(RouteIntelligencePurchase.request_digest == request_digest)
        .order_by(RouteIntelligencePurchase.prepared_at.desc(), RouteIntelligencePurchase.id.desc())
        .limit(1)
    )


def prepare_route_intelligence(db: Session, payload: object) -> RouteIntelligencePurchase:
    request, request_evidence = _validated_request(payload)
    request_digest = _digest(request_evidence)
    now = _now()
    current = _latest_for_request(db, request_digest)
    if (
        current is not None
        and current.state == "prepared"
        and _aware(current.expires_at) > now
    ):
        return current

    offer = configured_exact_upfront_offer()
    if offer is None:
        raise RouteIntelligencePurchaseError(
            503,
            "x402_exact_upfront_not_configured",
            "Exact upfront payment offer is not fully configured",
        )
    try:
        requirements = exact_payment_requirements()
    except ExactUpfrontError as exc:
        raise RouteIntelligencePurchaseError(503, exc.code, exc.message) from exc

    from .commercial_router import plan_commercial_route

    prepared_result = plan_commercial_route(db, requester_agent_id=0, payload=request)
    if prepared_result.get("selected_provider") is None:
        raise RouteIntelligencePurchaseError(
            409,
            "no_purchasable_route_available",
            "No bounded qualified route is currently available for this need",
        )

    result_digest = _digest(prepared_result)
    row = RouteIntelligencePurchase(
        purchase_id=str(uuid.uuid4()),
        product_sku=ROUTE_INTELLIGENCE_SKU,
        request_digest=request_digest,
        request_evidence=request_evidence,
        result_digest=result_digest,
        prepared_result=prepared_result,
        quote_currency=offer["quote_currency"],
        quote_amount=offer["quote_amount"],
        network=offer["network"],
        asset=offer["asset"],
        asset_code=offer["asset_code"],
        pay_to=offer["pay_to"],
        atomic_amount=offer["atomic_amount"],
        payment_requirements_digest=_digest(requirements),
        state="prepared",
        prepared_at=now,
        expires_at=now + timedelta(seconds=PREPARATION_TTL_SECONDS),
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def payment_required_response_data(row: RouteIntelligencePurchase) -> dict:
    required = build_exact_payment_required()
    if _digest(required["accepts"][0]) != row.payment_requirements_digest:
        raise RouteIntelligencePurchaseError(
            409,
            "payment_requirement_changed",
            "Payment requirements changed after the result was prepared; request a fresh preparation",
        )
    return {
        "purchase_id": row.purchase_id,
        "product_sku": row.product_sku,
        "prepared_result_digest": row.result_digest,
        "prepared_at": _aware(row.prepared_at).isoformat(),
        "expires_at": _aware(row.expires_at).isoformat(),
        "quote": {
            "amount": row.quote_amount,
            "currency": row.quote_currency,
            "atomic_amount": row.atomic_amount,
            "network": row.network,
            "asset": row.asset,
            "asset_code": row.asset_code,
        },
        "payment_required": required,
    }


def _decode_payment_payload(header_value: str, requirements: dict) -> tuple[dict, str]:
    if not isinstance(header_value, str) or not header_value:
        raise RouteIntelligencePurchaseError(402, "payment_required", "PAYMENT-SIGNATURE is required")
    if len(header_value.encode("utf-8")) > MAX_PAYMENT_SIGNATURE_HEADER_BYTES:
        raise RouteIntelligencePurchaseError(400, "payment_signature_too_large", "PAYMENT-SIGNATURE exceeds the bounded limit")
    try:
        raw = base64.b64decode(header_value, validate=True)
        if len(raw) > MAX_PAYMENT_SIGNATURE_HEADER_BYTES:
            raise ValueError
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "PAYMENT-SIGNATURE is malformed") from exc
    if not isinstance(data, dict) or data.get("x402Version") != 2:
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "x402Version 2 is required")
    if data.get("accepted") != requirements:
        raise RouteIntelligencePurchaseError(409, "payment_requirement_mismatch", "Signed payment does not match the prepared requirement")
    scheme_payload = data.get("payload")
    if not isinstance(scheme_payload, dict) or set(scheme_payload) != {"signature", "authorization"}:
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "EIP-3009 payment payload is malformed")
    signature = scheme_payload.get("signature")
    authorization = scheme_payload.get("authorization")
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature):
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "EIP-3009 signature is malformed")
    if not isinstance(authorization, dict) or set(authorization) != {
        "from", "to", "value", "validAfter", "validBefore", "nonce"
    }:
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "EIP-3009 authorization is malformed")
    payer = authorization.get("from")
    to = authorization.get("to")
    value = authorization.get("value")
    nonce = authorization.get("nonce")
    valid_after = authorization.get("validAfter")
    valid_before = authorization.get("validBefore")
    if not isinstance(payer, str) or not _ADDRESS.fullmatch(payer):
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "Payer address is malformed")
    if not isinstance(to, str) or not _ADDRESS.fullmatch(to) or to.lower() != str(requirements["payTo"]).lower():
        raise RouteIntelligencePurchaseError(409, "payment_recipient_mismatch", "Payment recipient does not match the prepared requirement")
    if str(value) != str(requirements["amount"]):
        raise RouteIntelligencePurchaseError(409, "payment_amount_mismatch", "Payment amount does not match the prepared requirement")
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "Payment nonce is malformed")
    if not str(valid_after).isdigit() or not str(valid_before).isdigit() or int(valid_before) <= int(valid_after):
        raise RouteIntelligencePurchaseError(400, "malformed_payment_signature", "Payment validity window is malformed")

    # Digest the signed transfer identity, not merely the wrapper JSON. This
    # prevents the same EIP-3009 authorization from being repackaged with a
    # different resource wrapper to fund another AION result.
    identity = {
        "network": requirements["network"],
        "asset": str(requirements["asset"]).lower(),
        "pay_to": str(requirements["payTo"]).lower(),
        "signature": signature.lower(),
        "authorization": {
            "from": payer.lower(),
            "to": to.lower(),
            "value": str(value),
            "validAfter": str(valid_after),
            "validBefore": str(valid_before),
            "nonce": nonce.lower(),
        },
    }
    return data, _digest(identity)


def _existing_by_payment_digest(db: Session, digest: str) -> RouteIntelligencePurchase | None:
    return db.scalar(
        select(RouteIntelligencePurchase).where(
            RouteIntelligencePurchase.payment_payload_digest == digest
        )
    )


def _entitlement(row: RouteIntelligencePurchase, *, idempotent_replay: bool) -> dict:
    return {
        "purchase_id": row.purchase_id,
        "product_sku": row.product_sku,
        "state": row.state,
        "prepared_result_digest": row.result_digest,
        "result": row.prepared_result,
        "payment": {
            "scheme": "exact",
            "payment_flow": "upfront",
            "network": row.network,
            "transaction": row.transaction_id,
            "payer": row.payer,
            "amount": row.quote_amount,
            "currency": row.quote_currency,
            "atomic_amount": row.atomic_amount,
        },
        "idempotent_replay": idempotent_replay,
        "aion_membership_created": False,
        "commercial_proof_created": False,
        "truth_boundaries": {
            "payment_is_real_settlement_only_when_state_entitled": True,
            "purchase_is_not_package5_vuo_or_adoption": True,
            "result_was_prepared_before_settlement": True,
        },
    }


def settle_and_release(db: Session, payload: object, payment_signature: str) -> dict:
    request, request_evidence = _validated_request(payload)
    _ = request
    request_digest = _digest(request_evidence)
    try:
        requirements = exact_payment_requirements()
    except ExactUpfrontError as exc:
        raise RouteIntelligencePurchaseError(503, exc.code, exc.message) from exc
    payment_payload, payment_digest = _decode_payment_payload(payment_signature, requirements)

    existing_payment = _existing_by_payment_digest(db, payment_digest)
    if existing_payment is not None:
        if existing_payment.request_digest != request_digest:
            raise RouteIntelligencePurchaseError(
                409,
                "payment_replay_conflict",
                "This signed payment identity is already bound to a different prepared request",
            )
        if existing_payment.state == "entitled":
            return _entitlement(existing_payment, idempotent_replay=True)
        raise RouteIntelligencePurchaseError(
            409,
            "payment_settlement_not_retryable",
            "This signed payment was already claimed; automatic settlement retry is disabled",
        )

    row = _latest_for_request(db, request_digest)
    if row is None:
        raise RouteIntelligencePurchaseError(
            409, "payment_without_preparation", "Request a fresh 402 preparation before submitting payment"
        )
    if row.state != "prepared":
        raise RouteIntelligencePurchaseError(
            409, "preparation_already_claimed", "The latest prepared result is already claimed"
        )
    if _aware(row.expires_at) <= _now():
        raise RouteIntelligencePurchaseError(
            409, "preparation_expired", "Prepared result expired; request a fresh 402 preparation"
        )
    if row.payment_requirements_digest != _digest(requirements):
        raise RouteIntelligencePurchaseError(
            409, "payment_requirement_changed", "Payment requirements changed after preparation"
        )

    row.payment_payload_digest = payment_digest
    row.state = "settlement_claimed"
    row.updated_at = _now()
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        collision = _existing_by_payment_digest(db, payment_digest)
        if collision is not None and collision.request_digest != request_digest:
            raise RouteIntelligencePurchaseError(
                409, "payment_replay_conflict", "Signed payment is already bound elsewhere"
            ) from exc
        raise RouteIntelligencePurchaseError(
            409, "payment_claim_conflict", "Concurrent payment claim conflict"
        ) from exc
    db.refresh(row)

    try:
        settlement = settle_exact_upfront(payment_payload, requirements)
    except FacilitatorSettlementError as exc:
        # The code-owned real-money gate is checked before any facilitator POST.
        # A disabled gate is safe to return to prepared only because no outbound
        # settlement attempt occurred.
        if exc.code == "real_money_adapter_disabled":
            row.payment_payload_digest = None
            row.state = "prepared"
            row.updated_at = _now()
            db.add(row)
            db.commit()
        raise RouteIntelligencePurchaseError(503, exc.code, exc.message) from exc

    outcome = settlement.get("outcome")
    row.updated_at = _now()
    if outcome == "settled":
        row.transaction_id = settlement["transaction"]
        row.payer = settlement["payer"]
        row.settlement_response_digest = _digest(settlement.get("response") or settlement)
        row.state = "entitled"
        row.entitled_at = row.updated_at
        row.failure_code = None
        row.failure_detail = None
        db.add(row)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise RouteIntelligencePurchaseError(
                409,
                "settlement_evidence_replay_conflict",
                "Settlement transaction is already bound to another purchase",
            ) from exc
        db.refresh(row)
        return _entitlement(row, idempotent_replay=False)

    if outcome == "pending":
        row.state = "settlement_pending"
        row.transaction_id = settlement.get("transaction")
        row.payer = settlement.get("payer")
        row.failure_code = "settlement_pending"
        row.failure_detail = settlement.get("detail")
    elif outcome == "rejected":
        row.state = "settlement_failed"
        row.failure_code = str(settlement.get("code") or "settlement_rejected")[:96]
        row.failure_detail = settlement.get("detail")
    else:
        row.state = "settlement_ambiguous"
        row.failure_code = str(settlement.get("code") or "settlement_ambiguous")[:96]
        row.failure_detail = settlement.get("detail")
    if settlement.get("response") is not None:
        row.settlement_response_digest = _digest(settlement["response"])
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RouteIntelligencePurchaseError(
            409, "settlement_evidence_replay_conflict", "Settlement evidence conflicts with another purchase"
        ) from exc

    status = 503 if row.state in {"settlement_pending", "settlement_ambiguous"} else 402
    raise RouteIntelligencePurchaseError(
        status,
        row.failure_code or row.state,
        "Settlement did not establish a releasable entitlement; the prepared result was not released",
    )
