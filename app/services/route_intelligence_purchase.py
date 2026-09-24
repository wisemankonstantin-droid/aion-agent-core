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
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..payment_models import RouteIntelligencePurchase
from . import economic_kernel
from .cdp_x402_facilitator import FacilitatorSettlementError, settle_exact_upfront
from .direct_base_usdc import (
    DIRECT_PAYMENT_METHOD,
    configured_direct_base_usdc_offer,
    direct_payment_requirements,
    verify_direct_base_usdc_transfer,
)
from .paid_route_intelligence import ROUTE_INTELLIGENCE_SKU, configured_route_intelligence_plan
from .x402_exact_upfront import (
    ExactUpfrontError,
    bound_exact_payment_requirements,
    build_exact_payment_required,
    configured_exact_upfront_offer,
)


PREPARATION_TTL_SECONDS = 15 * 60
MAX_PAYMENT_SIGNATURE_HEADER_BYTES = 24 * 1024
X402_PAYMENT_METHOD = "x402_exact_upfront"
_ALLOWED_REQUEST_KEYS = {"need", "candidate_identifier"}
_SIGNATURE = re.compile(r"^0x[0-9a-fA-F]{130}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_NONCE = re.compile(r"^0x[0-9a-fA-F]{64}$")
_PURCHASE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_RESULT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_TX_HASH = re.compile(r"^0x[0-9a-fA-F]{64}$")


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


def _money_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _accounting_evidence(
    *,
    quote_amount: str,
    atomic_amount: str,
    currency: str,
    payment_method: str = X402_PAYMENT_METHOD,
) -> dict:
    plan = configured_route_intelligence_plan()
    if plan is None:  # Defensive: preparation already proved the plan exists.
        raise RouteIntelligencePurchaseError(
            503, "paid_route_quote_not_configured", "Paid Route Intelligence quote changed"
        )
    gross = Decimal(quote_amount)
    maximum_payment_fee = Decimal(plan.payment_fee_allowance)
    budgeted_contribution = gross - maximum_payment_fee
    budgeted_margin_bps = int((budgeted_contribution / gross) * Decimal(10_000))
    unknown_cost_reasons = ["aion_operating_cost_not_metered"]
    if payment_method != DIRECT_PAYMENT_METHOD:
        unknown_cost_reasons.append(
            "facilitator_settlement_contract_has_no_payment_fee_field"
        )
    return {
        "schema": "first_sat_accounting_v1",
        "payment_method": payment_method,
        "currency": currency,
        "quoted_gross_revenue": quote_amount,
        "quoted_atomic_amount": atomic_amount,
        "settled_atomic_amount": None,
        "settled_atomic_amount_source": "not_reported",
        "known_provider_cost": "0",
        "actual_payment_cost": None,
        "actual_aion_operating_cost": None,
        "configured_payment_fee_allowance": _money_text(maximum_payment_fee),
        "budgeted_contribution_after_fee_allowance": _money_text(budgeted_contribution),
        "budgeted_margin_bps_after_fee_allowance": budgeted_margin_bps,
        "fee_allowance_is_not_observed_cost": True,
        "exact_contribution_margin_available": False,
        "unknown_cost_reasons": unknown_cost_reasons,
        "settlement_recorded": False,
    }


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


def _by_purchase_id(db: Session, purchase_id: str) -> RouteIntelligencePurchase | None:
    return db.scalar(
        select(RouteIntelligencePurchase).where(
            RouteIntelligencePurchase.purchase_id == purchase_id
        )
    )


def prepare_route_intelligence(
    db: Session,
    payload: object,
    *,
    payment_method: str | None = None,
) -> RouteIntelligencePurchase:
    request, request_evidence = _validated_request(payload)
    request_digest = _digest(request_evidence)
    now = _now()

    if payment_method not in {None, DIRECT_PAYMENT_METHOD, X402_PAYMENT_METHOD}:
        raise RouteIntelligencePurchaseError(
            400,
            "payment_method_invalid",
            "Unsupported Route Intelligence payment method",
        )

    direct_offer = configured_direct_base_usdc_offer()
    x402_offer = configured_exact_upfront_offer()
    if selected_payment_method == DIRECT_PAYMENT_METHOD:
        offer = direct_offer
        selected_payment_method = DIRECT_PAYMENT_METHOD
    elif payment_method == X402_PAYMENT_METHOD:
        offer = x402_offer
        selected_payment_method = X402_PAYMENT_METHOD
    elif direct_offer is not None:
        offer = direct_offer
        selected_payment_method = DIRECT_PAYMENT_METHOD
    else:
        offer = x402_offer
        selected_payment_method = X402_PAYMENT_METHOD

    if offer is None:
        raise RouteIntelligencePurchaseError(
            503,
            "payment_offer_not_configured",
            "Requested launch payment offer is not fully configured",
        )

    current = _latest_for_request(db, request_digest)
    if (
        current is not None
        and current.state == "prepared"
        and _aware(current.expires_at) > now
        and (current.accounting_evidence or {}).get(
            "payment_method", X402_PAYMENT_METHOD
        )
        == selected_payment_method
    ):
        return current

    from .commercial_router import plan_commercial_route

    prepared_result = plan_commercial_route(db, requester_agent_id=0, payload=request)
    if prepared_result.get("selected_provider") is None:
        raise RouteIntelligencePurchaseError(
            409,
            "no_purchasable_route_available",
            "No bounded qualified route is currently available for this need",
        )

    result_digest = _digest(prepared_result)
    purchase_id = str(uuid.uuid4())
    expires_at = now + timedelta(seconds=PREPARATION_TTL_SECONDS)
    if selected_payment_method == DIRECT_PAYMENT_METHOD:
        requirements = direct_payment_requirements(
            purchase_id=purchase_id,
            result_digest=result_digest,
            prepared_at=now,
            expires_at=expires_at,
        )
    else:
        try:
            requirements = bound_exact_payment_requirements(purchase_id, result_digest)
        except ExactUpfrontError as exc:
            raise RouteIntelligencePurchaseError(503, exc.code, exc.message) from exc

    row = RouteIntelligencePurchase(
        purchase_id=purchase_id,
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
        accounting_evidence=_accounting_evidence(
            quote_amount=offer["quote_amount"],
            atomic_amount=offer["atomic_amount"],
            currency=offer["quote_currency"],
            payment_method=selected_payment_method,
        ),
        state="prepared",
        prepared_at=now,
        expires_at=expires_at,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def payment_required_response_data(row: RouteIntelligencePurchase) -> dict:
    payment_method = (row.accounting_evidence or {}).get(
        "payment_method", X402_PAYMENT_METHOD
    )
    if selected_payment_method == DIRECT_PAYMENT_METHOD:
        requirements = direct_payment_requirements(
            purchase_id=row.purchase_id,
            result_digest=row.result_digest,
            prepared_at=_aware(row.prepared_at),
            expires_at=_aware(row.expires_at),
        )
        required = requirements
    else:
        try:
            requirements = bound_exact_payment_requirements(
                row.purchase_id, row.result_digest
            )
        except ExactUpfrontError as exc:
            raise RouteIntelligencePurchaseError(503, exc.code, exc.message) from exc
        required = build_exact_payment_required(requirements)

    if _digest(requirements) != row.payment_requirements_digest:
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


def _decode_payment_envelope(header_value: str) -> dict:
    if not isinstance(header_value, str) or not header_value:
        raise RouteIntelligencePurchaseError(402, "payment_required", "PAYMENT-SIGNATURE is required")
    if len(header_value.encode("utf-8")) > MAX_PAYMENT_SIGNATURE_HEADER_BYTES:
        raise RouteIntelligencePurchaseError(
            400, "payment_signature_too_large", "PAYMENT-SIGNATURE exceeds the bounded limit"
        )
    try:
        raw = base64.b64decode(header_value, validate=True)
        if len(raw) > MAX_PAYMENT_SIGNATURE_HEADER_BYTES:
            raise ValueError
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError, binascii.Error) as exc:
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "PAYMENT-SIGNATURE is malformed"
        ) from exc
    if not isinstance(data, dict) or data.get("x402Version") != 2:
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "x402Version 2 is required"
        )
    return data


def _payment_binding(data: dict) -> tuple[str, str]:
    accepted = data.get("accepted")
    extra = accepted.get("extra") if isinstance(accepted, dict) else None
    purchase_id = extra.get("aionPurchaseId") if isinstance(extra, dict) else None
    result_digest = extra.get("aionPreparedResultDigest") if isinstance(extra, dict) else None
    if not isinstance(purchase_id, str) or not _PURCHASE_ID.fullmatch(purchase_id.lower()):
        raise RouteIntelligencePurchaseError(
            409,
            "payment_preparation_binding_missing",
            "Signed payment does not identify a canonical prepared purchase",
        )
    if not isinstance(result_digest, str) or not _RESULT_DIGEST.fullmatch(result_digest.lower()):
        raise RouteIntelligencePurchaseError(
            409,
            "payment_preparation_binding_missing",
            "Signed payment does not identify the prepared result digest",
        )
    return purchase_id.lower(), result_digest.lower()


def _validate_payment_payload(data: dict, requirements: dict) -> str:
    if data.get("accepted") != requirements:
        raise RouteIntelligencePurchaseError(
            409,
            "payment_requirement_mismatch",
            "Signed payment does not match the prepared requirement",
        )
    scheme_payload = data.get("payload")
    if not isinstance(scheme_payload, dict) or set(scheme_payload) != {"signature", "authorization"}:
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "EIP-3009 payment payload is malformed"
        )
    signature = scheme_payload.get("signature")
    authorization = scheme_payload.get("authorization")
    if not isinstance(signature, str) or not _SIGNATURE.fullmatch(signature):
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "EIP-3009 signature is malformed"
        )
    if not isinstance(authorization, dict) or set(authorization) != {
        "from", "to", "value", "validAfter", "validBefore", "nonce"
    }:
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "EIP-3009 authorization is malformed"
        )
    payer = authorization.get("from")
    to = authorization.get("to")
    value = authorization.get("value")
    nonce = authorization.get("nonce")
    valid_after = authorization.get("validAfter")
    valid_before = authorization.get("validBefore")
    if not isinstance(payer, str) or not _ADDRESS.fullmatch(payer):
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "Payer address is malformed"
        )
    if not isinstance(to, str) or not _ADDRESS.fullmatch(to) or to.lower() != str(requirements["payTo"]).lower():
        raise RouteIntelligencePurchaseError(
            409, "payment_recipient_mismatch", "Payment recipient does not match the prepared requirement"
        )
    if str(value) != str(requirements["amount"]):
        raise RouteIntelligencePurchaseError(
            409, "payment_amount_mismatch", "Payment amount does not match the prepared requirement"
        )
    if not isinstance(nonce, str) or not _NONCE.fullmatch(nonce):
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "Payment nonce is malformed"
        )
    if not str(valid_after).isdigit() or not str(valid_before).isdigit() or int(valid_before) <= int(valid_after):
        raise RouteIntelligencePurchaseError(
            400, "malformed_payment_signature", "Payment validity window is malformed"
        )

    # Digest the signed transfer identity, not merely the wrapper JSON. This
    # prevents the same EIP-3009 authorization from being repackaged with a
    # different prepared-result binding to fund another AION result.
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
    return _digest(identity)


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
            "method": (row.accounting_evidence or {}).get(
                "payment_method", X402_PAYMENT_METHOD
            ),
            "scheme": (
                "eip3009_buyer_broadcast"
                if (row.accounting_evidence or {}).get("payment_method")
                == DIRECT_PAYMENT_METHOD
                else "exact"
            ),
            "payment_flow": "upfront",
            "network": row.network,
            "transaction": row.transaction_id,
            "payer": row.payer,
            "amount": row.quote_amount,
            "currency": row.quote_currency,
            "atomic_amount": row.atomic_amount,
        },
        "accounting": row.accounting_evidence,
        "idempotent_replay": idempotent_replay,
        "aion_membership_created": False,
        "commercial_proof_created": False,
        "truth_boundaries": {
            "payment_is_real_settlement_only_when_state_entitled": True,
            "purchase_is_not_package5_vuo_or_adoption": True,
            "result_was_prepared_before_settlement": True,
            "payment_requirements_bound_to_purchase_and_result_digest": True,
            "concurrent_claim_is_committed_before_external_payment_check": True,
            "buyer_pays_gas_when_direct_payment_method": True,
        },
    }


def _existing_by_transaction(
    db: Session, transaction_id: str
) -> RouteIntelligencePurchase | None:
    return db.scalar(
        select(RouteIntelligencePurchase).where(
            RouteIntelligencePurchase.transaction_id == transaction_id
        )
    )


def settle_direct_and_release(
    db: Session,
    payload: object,
    *,
    purchase_id: str,
    transaction_hash: str,
) -> dict:
    """Verify buyer-broadcast EIP-3009 payment, then atomically entitle once.

    Direct verification is read-only, so unverified evidence never claims a
    purchase or transaction hash. This prevents a bad or observed tx hash from
    being used to poison another buyer's legitimate purchase.
    """
    if not economic_kernel.REAL_MONEY_EXECUTION_ENABLED:
        raise RouteIntelligencePurchaseError(
            503,
            "real_money_adapter_disabled",
            "Real-money execution is disabled",
        )

    normalized_purchase_id = str(purchase_id or "").strip().lower()
    normalized_tx = str(transaction_hash or "").strip().lower()
    if not _PURCHASE_ID.fullmatch(normalized_purchase_id):
        raise RouteIntelligencePurchaseError(
            400, "purchase_id_invalid", "X-AION-PURCHASE-ID is invalid"
        )
    if not _TX_HASH.fullmatch(normalized_tx):
        raise RouteIntelligencePurchaseError(
            400, "payment_transaction_hash_invalid", "X-AION-PAYMENT-TX is invalid"
        )

    request, request_evidence = _validated_request(payload)
    _ = request
    request_digest = _digest(request_evidence)
    row = _by_purchase_id(db, normalized_purchase_id)
    if row is None:
        raise RouteIntelligencePurchaseError(
            409, "payment_preparation_unknown", "Prepared purchase does not exist"
        )
    if row.request_digest != request_digest:
        raise RouteIntelligencePurchaseError(
            409,
            "payment_request_binding_mismatch",
            "Payment proof is bound to a different purchase request",
        )
    if (row.accounting_evidence or {}).get("payment_method") != DIRECT_PAYMENT_METHOD:
        raise RouteIntelligencePurchaseError(
            409,
            "payment_method_mismatch",
            "Prepared purchase does not use direct Base USDC EIP-3009 settlement",
        )

    if row.state == "entitled":
        if row.transaction_id == normalized_tx:
            return _entitlement(row, idempotent_replay=True)
        raise RouteIntelligencePurchaseError(
            409,
            "preparation_already_claimed",
            "Prepared result is already entitled by another payment",
        )
    if row.state != "prepared":
        raise RouteIntelligencePurchaseError(
            409,
            "preparation_already_claimed",
            "Prepared result is not available for a new direct payment proof",
        )

    requirements = direct_payment_requirements(
        purchase_id=row.purchase_id,
        result_digest=row.result_digest,
        prepared_at=_aware(row.prepared_at),
        expires_at=_aware(row.expires_at),
    )
    if row.payment_requirements_digest != _digest(requirements):
        raise RouteIntelligencePurchaseError(
            409,
            "payment_requirement_changed",
            "Payment requirements changed after preparation",
        )

    authorization = requirements["authorization"]["message"]
    settlement = verify_direct_base_usdc_transfer(
        normalized_tx,
        expected_asset=row.asset,
        expected_pay_to=row.pay_to,
        expected_atomic_amount=row.atomic_amount,
        expected_authorization_nonce=authorization["nonce"],
        expected_valid_after=int(authorization["validAfter"]),
        expected_valid_before=int(authorization["validBefore"]),
    )

    outcome = settlement.get("outcome")
    if outcome != "settled":
        status = 503 if outcome in {"pending", "ambiguous"} else 402
        raise RouteIntelligencePurchaseError(
            status,
            str(settlement.get("code") or "direct_payment_verification_failed")[:96],
            "Payment was not verified as a releasable purchase-bound Base USDC settlement",
        )

    if settlement.get("transaction") != normalized_tx:
        raise RouteIntelligencePurchaseError(
            409,
            "settlement_transaction_mismatch",
            "Verified settlement transaction does not match submitted proof",
        )

    collision = _existing_by_transaction(db, normalized_tx)
    if collision is not None:
        if collision.purchase_id == row.purchase_id and collision.state == "entitled":
            return _entitlement(collision, idempotent_replay=True)
        raise RouteIntelligencePurchaseError(
            409,
            "payment_replay_conflict",
            "This transaction is already bound to another purchase",
        )

    payment_digest = _digest(
        {
            "payment_method": DIRECT_PAYMENT_METHOD,
            "transaction": normalized_tx,
            "authorization_nonce": authorization["nonce"],
        }
    )
    now = _now()
    accounting = dict(row.accounting_evidence or {})
    accounting["settled_atomic_amount"] = str(settlement["amount"])
    accounting["settled_atomic_amount_source"] = (
        "onchain_base_usdc_eip3009_transfer"
    )
    accounting["actual_payment_cost"] = "0"
    accounting["aion_blockchain_gas_cost"] = "0"
    accounting["buyer_or_buyer_selected_broadcaster_paid_gas"] = True
    accounting["purchase_bound_authorization_nonce"] = settlement.get(
        "authorization_nonce"
    )
    accounting["settlement_finality"] = settlement.get("finality")
    accounting["settlement_recorded"] = True
    accounting["unknown_cost_reasons"] = [
        reason
        for reason in accounting.get("unknown_cost_reasons", [])
        if reason != "facilitator_settlement_contract_has_no_payment_fee_field"
    ]
    settlement_digest = _digest(settlement.get("response") or settlement)

    try:
        entitled = db.execute(
            update(RouteIntelligencePurchase)
            .where(
                RouteIntelligencePurchase.id == row.id,
                RouteIntelligencePurchase.state == "prepared",
                RouteIntelligencePurchase.payment_payload_digest.is_(None),
                RouteIntelligencePurchase.transaction_id.is_(None),
            )
            .values(
                payment_payload_digest=payment_digest,
                transaction_id=normalized_tx,
                payer=settlement["payer"],
                settlement_response_digest=settlement_digest,
                accounting_evidence=accounting,
                state="entitled",
                entitled_at=now,
                updated_at=now,
                failure_code=None,
                failure_detail=None,
            )
        )
        if entitled.rowcount != 1:
            db.rollback()
            fresh = _by_purchase_id(db, row.purchase_id)
            if (
                fresh is not None
                and fresh.state == "entitled"
                and fresh.transaction_id == normalized_tx
            ):
                return _entitlement(fresh, idempotent_replay=True)
            collision = _existing_by_transaction(db, normalized_tx)
            if collision is not None and collision.purchase_id != row.purchase_id:
                raise RouteIntelligencePurchaseError(
                    409,
                    "payment_replay_conflict",
                    "Verified transaction was concurrently bound to another purchase",
                )
            raise RouteIntelligencePurchaseError(
                409,
                "payment_claim_conflict",
                "Prepared purchase changed before verified entitlement could commit",
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        collision = _existing_by_transaction(db, normalized_tx)
        if collision is not None:
            if collision.purchase_id == row.purchase_id and collision.state == "entitled":
                return _entitlement(collision, idempotent_replay=True)
            raise RouteIntelligencePurchaseError(
                409,
                "payment_replay_conflict",
                "Verified transaction is already bound to another purchase",
            ) from exc
        raise RouteIntelligencePurchaseError(
            409,
            "payment_claim_conflict",
            "Verified entitlement conflicted with concurrent state",
        ) from exc

    fresh = _by_purchase_id(db, row.purchase_id)
    if fresh is None or fresh.state != "entitled":
        raise RouteIntelligencePurchaseError(
            409,
            "payment_claim_conflict",
            "Verified entitlement could not be reloaded after commit",
        )
    return _entitlement(fresh, idempotent_replay=False)


def settle_and_release(db: Session, payload: object, payment_signature: str) -> dict:
    request, request_evidence = _validated_request(payload)
    _ = request
    request_digest = _digest(request_evidence)

    payment_payload = _decode_payment_envelope(payment_signature)
    purchase_id, bound_result_digest = _payment_binding(payment_payload)
    row = _by_purchase_id(db, purchase_id)
    if row is None:
        raise RouteIntelligencePurchaseError(
            409,
            "payment_preparation_unknown",
            "Signed payment references an unknown prepared purchase",
        )
    if row.request_digest != request_digest:
        raise RouteIntelligencePurchaseError(
            409,
            "payment_request_binding_mismatch",
            "Signed payment is bound to a different purchase request",
        )
    if row.result_digest != bound_result_digest:
        raise RouteIntelligencePurchaseError(
            409,
            "payment_result_binding_mismatch",
            "Signed payment is bound to a different prepared result",
        )

    try:
        requirements = bound_exact_payment_requirements(row.purchase_id, row.result_digest)
    except ExactUpfrontError as exc:
        raise RouteIntelligencePurchaseError(503, exc.code, exc.message) from exc
    if row.payment_requirements_digest != _digest(requirements):
        raise RouteIntelligencePurchaseError(
            409, "payment_requirement_changed", "Payment requirements changed after preparation"
        )

    payment_digest = _validate_payment_payload(payment_payload, requirements)
    existing_payment = _existing_by_payment_digest(db, payment_digest)
    if existing_payment is not None:
        if existing_payment.purchase_id != row.purchase_id:
            raise RouteIntelligencePurchaseError(
                409,
                "payment_replay_conflict",
                "This signed payment identity is already bound to a different prepared purchase",
            )
        if existing_payment.state == "entitled":
            return _entitlement(existing_payment, idempotent_replay=True)
        raise RouteIntelligencePurchaseError(
            409,
            "payment_settlement_not_retryable",
            "This signed payment was already claimed; automatic settlement retry is disabled",
        )

    now = _now()
    if row.state != "prepared":
        raise RouteIntelligencePurchaseError(
            409, "preparation_already_claimed", "The prepared result is already claimed"
        )
    if _aware(row.expires_at) <= now:
        raise RouteIntelligencePurchaseError(
            409, "preparation_expired", "Prepared result expired; request a fresh preparation"
        )

    # Claim atomically before any facilitator contact. A conditional UPDATE is
    # portable across SQLite/PostgreSQL and prevents two concurrent signed
    # requests from both reaching the money-moving seam for the same snapshot.
    try:
        claimed = db.execute(
            update(RouteIntelligencePurchase)
            .where(
                RouteIntelligencePurchase.id == row.id,
                RouteIntelligencePurchase.state == "prepared",
                RouteIntelligencePurchase.payment_payload_digest.is_(None),
            )
            .values(
                payment_payload_digest=payment_digest,
                state="settlement_claimed",
                updated_at=now,
            )
        )
        if claimed.rowcount != 1:
            db.rollback()
            fresh = _by_purchase_id(db, row.purchase_id)
            if fresh is not None and fresh.payment_payload_digest == payment_digest:
                if fresh.state == "entitled":
                    return _entitlement(fresh, idempotent_replay=True)
                raise RouteIntelligencePurchaseError(
                    409,
                    "payment_settlement_not_retryable",
                    "This signed payment was already claimed; automatic settlement retry is disabled",
                )
            raise RouteIntelligencePurchaseError(
                409,
                "preparation_already_claimed",
                "The prepared result was concurrently claimed before settlement",
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        collision = _existing_by_payment_digest(db, payment_digest)
        if collision is not None:
            if collision.purchase_id != row.purchase_id:
                raise RouteIntelligencePurchaseError(
                    409, "payment_replay_conflict", "Signed payment is already bound elsewhere"
                ) from exc
            if collision.state == "entitled":
                return _entitlement(collision, idempotent_replay=True)
            raise RouteIntelligencePurchaseError(
                409,
                "payment_settlement_not_retryable",
                "This signed payment was already claimed; automatic settlement retry is disabled",
            ) from exc
        raise RouteIntelligencePurchaseError(
            409, "payment_claim_conflict", "Concurrent payment claim conflict"
        ) from exc

    row = _by_purchase_id(db, row.purchase_id)
    if row is None or row.state != "settlement_claimed" or row.payment_payload_digest != payment_digest:
        raise RouteIntelligencePurchaseError(
            409, "payment_claim_conflict", "Persisted payment claim could not be verified"
        )

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
        accounting = dict(row.accounting_evidence or {})
        response = settlement.get("response")
        reported_amount = response.get("amount") if isinstance(response, dict) else None
        accounting["settled_atomic_amount"] = (
            str(reported_amount) if reported_amount is not None else None
        )
        accounting["settled_atomic_amount_source"] = (
            "facilitator_reported" if reported_amount is not None else "not_reported"
        )
        accounting["settlement_recorded"] = True
        row.accounting_evidence = accounting
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