"""Package 6A deterministic economic policy and disabled real-money boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import hashlib
import json
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..release_identity import release_identity
from .identity_resolution import logical_groups
from .rate_limit import allow_economic_preflight, configured_economic_preflight_limit


MINIMUM_MARGIN_BPS = 4_000
STANDARD_TARGET_MARGIN_BPS = 6_000
REAL_MONEY_EXECUTION_ENABLED = False
QUOTE_TTL_SECONDS = 900
MAX_LOGICAL_IDENTITIES = 500
_MONEY = re.compile(r"^(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,6})?$")
_CURRENCY = re.compile(r"^[A-Z][A-Z0-9]{2,15}$")
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_OPERATION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


class EconomicKernelError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def canonical_money(value: str | Decimal) -> tuple[Decimal, str]:
    raw = str(value)
    if not _MONEY.fullmatch(raw):
        raise EconomicKernelError(422, "malformed_money", "Money must be canonical non-negative decimal notation with at most 18 integer and 6 fractional digits")
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise EconomicKernelError(422, "malformed_money", "Invalid monetary value") from exc
    if not number.is_finite() or number < 0:
        raise EconomicKernelError(422, "malformed_money", "Money must be finite and non-negative")
    canonical = format(number, "f").rstrip("0").rstrip(".") if "." in format(number, "f") else format(number, "f")
    return number, canonical or "0"


def canonical_currency(value: str) -> str:
    raw = str(value)
    if not _CURRENCY.fullmatch(raw):
        raise EconomicKernelError(422, "currency_mismatch", "Currency must be an exact supported uppercase asset identifier")
    return raw


def _canonical_signed_calculation(value: Decimal) -> str:
    """Canonicalize a trusted derived value; requester money remains non-negative."""
    absolute = -value if value < 0 else value
    _, canonical = canonical_money(format(absolute, "f"))
    return "-" + canonical if value < 0 else canonical


@dataclass(frozen=True)
class TrustedEconomicPlan:
    product_sku: str
    currency: str
    customer_price: str
    expected_variable_cost: str
    maximum_variable_cost: str | None
    verification_cost: str
    payment_fee_allowance: str
    maximum_attempts: int
    commercial_rights_state: str
    maximum_total_spend_cap: str
    direct_expected_cost_per_vuo: str | None = None
    expected_success_probability: str | None = None


TRUSTED_PRODUCT_PROFILES = {
    "aion.cached.utility.v1": TrustedEconomicPlan(
        "aion.cached.utility.v1", "USD", "0", "0", "0", "0", "0", 1, "allowed", "0", "0"
    ),
    "aion.verified.callability.v1": TrustedEconomicPlan(
        "aion.verified.callability.v1", "USD", "10", "5.5", "5.5", "0.5", "0", 1, "allowed", "6", "6"
    ),
}


def evaluate_plan(plan: TrustedEconomicPlan, *, requested_currency: str, requester_max_price: str | None) -> dict:
    currency = canonical_currency(plan.currency)
    requested = canonical_currency(requested_currency)
    if requested != currency:
        raise EconomicKernelError(422, "currency_mismatch", "No FX adapter exists; requested and trusted-plan currency must match")
    price, price_s = canonical_money(plan.customer_price)
    expected_variable, expected_variable_s = canonical_money(plan.expected_variable_cost)
    verification, verification_s = canonical_money(plan.verification_cost)
    payment_fee, payment_fee_s = canonical_money(plan.payment_fee_allowance)
    cap, cap_s = canonical_money(plan.maximum_total_spend_cap)
    reasons = []
    if plan.maximum_variable_cost is None:
        maximum_variable = None
        maximum_variable_s = None
        maximum_spend = None
        maximum_spend_s = None
        reasons.append("unknown_maximum_cost")
    else:
        maximum_variable, maximum_variable_s = canonical_money(plan.maximum_variable_cost)
        maximum_spend = maximum_variable + verification + payment_fee
        _, maximum_spend_s = canonical_money(format(maximum_spend, "f"))
        if maximum_spend > cap:
            reasons.append("max_total_spend_exceeded")
    expected_total = expected_variable + verification + payment_fee
    _, expected_total_s = canonical_money(format(expected_total, "f"))
    contribution = price - expected_total
    contribution_s = _canonical_signed_calculation(contribution)
    margin_bps = 0 if price == 0 or contribution < 0 else int(((contribution / price) * Decimal(10_000)).to_integral_value(rounding=ROUND_FLOOR))
    if plan.commercial_rights_state == "unknown":
        reasons.append("commercial_rights_unknown")
    elif plan.commercial_rights_state != "allowed":
        reasons.append("commercial_rights_prohibited")
    if price == 0 and maximum_spend is not None and maximum_spend > 0:
        reasons.append("free_variable_cost_execution_prohibited")
    elif price > 0 and margin_bps < MINIMUM_MARGIN_BPS:
        reasons.append("margin_below_floor")
    if requester_max_price is not None:
        budget, _ = canonical_money(requester_max_price)
        if budget < price:
            reasons.append("requester_budget_below_price")
    if plan.maximum_attempts < 1 or plan.maximum_attempts > 16:
        raise EconomicKernelError(422, "invalid_maximum_attempts", "Trusted maximum attempts must be between 1 and 16")
    if plan.direct_expected_cost_per_vuo is not None:
        _, expected_vuo_s = canonical_money(plan.direct_expected_cost_per_vuo)
    elif plan.expected_success_probability is not None:
        try:
            probability = Decimal(plan.expected_success_probability)
        except InvalidOperation as exc:
            raise EconomicKernelError(422, "invalid_success_probability", "Trusted success probability is invalid") from exc
        if not probability.is_finite() or probability <= 0 or probability > 1:
            raise EconomicKernelError(422, "invalid_success_probability", "Trusted success probability must be greater than zero and at most one")
        expected_vuo = (expected_variable / probability) + verification + payment_fee
        _, expected_vuo_s = canonical_money(format(expected_vuo.quantize(Decimal("0.000001")), "f"))
    else:
        raise EconomicKernelError(422, "expected_vuo_cost_unknown", "Trusted expected cost per verified outcome evidence is required")
    policy_eligible = not reasons
    funding_required = price > 0 or (maximum_spend is not None and maximum_spend > 0)
    execution_reasons = list(reasons)
    if funding_required:
        execution_reasons.extend(["payment_not_authorized", "reserve_not_established", "real_money_adapter_disabled"])
    return {
        "product_sku": plan.product_sku, "currency": currency,
        "customer_price": price_s, "expected_variable_cost": expected_variable_s,
        "maximum_variable_cost": maximum_variable_s, "verification_cost": verification_s,
        "payment_fee_allowance": payment_fee_s, "expected_total_cost": expected_total_s,
        "maximum_total_spend": maximum_spend_s, "maximum_total_spend_cap": cap_s,
        "contribution_amount": contribution_s, "expected_margin_bps": margin_bps,
        "expected_margin_state": "not_applicable_zero_price_zero_cost" if price == expected_total == 0 else "calculated",
        "minimum_margin_bps": MINIMUM_MARGIN_BPS, "standard_target_margin_bps": STANDARD_TARGET_MARGIN_BPS,
        "expected_cost_per_verified_outcome": expected_vuo_s,
        "maximum_attempts": plan.maximum_attempts, "commercial_rights_state": plan.commercial_rights_state,
        "funding_required": funding_required, "policy_eligible": policy_eligible,
        "execution_eligible": policy_eligible and not funding_required,
        "decision_reasons": execution_reasons or ["known_zero_cost_no_payment_required"],
    }


def _canonical_agent_id(db: Session, agent_id: int) -> int:
    raw_count = db.scalar(select(func.count()).select_from(models.Agent)) or 0
    if raw_count > MAX_LOGICAL_IDENTITIES:
        raise EconomicKernelError(503, "economic_resource_limit", "Raw identity input exceeds Package 6A bound")
    groups = logical_groups(db)
    if len(groups) > MAX_LOGICAL_IDENTITIES:
        raise EconomicKernelError(503, "economic_resource_limit", "Logical-identity input exceeds Package 6A bound")
    for group in groups:
        if agent_id in group["row_ids"]:
            return group["canonical_agent_id"]
    raise EconomicKernelError(404, "agent_not_found", "Agent not found")


def _valid_operation_id(value: str) -> str:
    operation_id = str(value or "").lower()
    if not _OPERATION_ID.fullmatch(operation_id):
        raise EconomicKernelError(422, "invalid_operation_id", "Operation ID must be a canonical UUID")
    return operation_id


def _valid_idempotency(value: str | None) -> str:
    key = str(value or "")
    if not _IDEMPOTENCY.fullmatch(key):
        raise EconomicKernelError(422, "invalid_idempotency_key", "Idempotency key must be 1 to 128 safe ASCII characters")
    return key


def create_preflight(
    db: Session, *, requester_agent_id: int, product_sku: str,
    requested_currency: str, requester_max_price: str | None,
    idempotency_key: str, parent_operation_id: str | None = None,
) -> dict:
    key = _valid_idempotency(idempotency_key)
    canonical_id = _canonical_agent_id(db, requester_agent_id)
    if not allow_economic_preflight(canonical_id):
        raise EconomicKernelError(
            429, "economic_rate_limited",
            f"Economic preflight rate limit exceeded ({configured_economic_preflight_limit()}/minute)",
        )
    plan = TRUSTED_PRODUCT_PROFILES.get(product_sku)
    if plan is None:
        raise EconomicKernelError(422, "unknown_product_sku", "No trusted economic profile exists for this product")
    evaluated = evaluate_plan(plan, requested_currency=requested_currency, requester_max_price=requester_max_price)
    parent_operation_id = _valid_operation_id(parent_operation_id) if parent_operation_id else None
    material = {"canonical_requester_agent_id": canonical_id, "product_sku": product_sku,
                "requested_currency": requested_currency, "requester_max_price": requester_max_price,
                "parent_operation_id": parent_operation_id}
    request_digest = _digest(material)
    existing = db.scalar(select(models.EconomicOperation).where(
        models.EconomicOperation.requester_agent_id == canonical_id,
        models.EconomicOperation.idempotency_key == key,
    ))
    if existing is not None:
        if existing.request_digest != request_digest:
            raise EconomicKernelError(409, "idempotency_conflict", "Idempotency key was used for different economic material")
        return serialize_operation(db, existing, idempotent_replay=True)
    parent = None
    if parent_operation_id is not None:
        parent = db.scalar(select(models.EconomicOperation).where(
            models.EconomicOperation.operation_id == parent_operation_id
        ).with_for_update())
        if parent is None:
            raise EconomicKernelError(404, "parent_operation_not_found", "Parent economic operation not found")
        if parent.requester_agent_id != canonical_id:
            raise EconomicKernelError(403, "parent_operation_forbidden", "Parent economic operation belongs to another logical requester")
        if parent.currency != evaluated["currency"]:
            raise EconomicKernelError(409, "currency_mismatch", "Child and parent economic operations must use the same currency")
        if parent.maximum_total_spend is None or evaluated["maximum_total_spend"] is None:
            raise EconomicKernelError(409, "unknown_maximum_cost", "Parent and child require known maximum spend")
        if not parent.policy_eligible or parent.state not in {"quoted", "payment_authorized", "funds_reserved"}:
            raise EconomicKernelError(409, "parent_not_eligible", "Parent economic operation cannot allocate child spend")
        if _aware(parent.quote_expires_at) <= _now() and parent.state in {"quoted", "payment_authorized"}:
            raise EconomicKernelError(409, "quote_expired", "Expired parent quote cannot allocate child spend")
        # A competing identical child may have committed while this transaction
        # waited for the parent lock. Re-check before calculating allocation.
        existing = db.scalar(select(models.EconomicOperation).where(
            models.EconomicOperation.requester_agent_id == canonical_id,
            models.EconomicOperation.idempotency_key == key,
        ))
        if existing is not None:
            if existing.request_digest != request_digest:
                raise EconomicKernelError(409, "idempotency_conflict", "Idempotency key was used for different economic material")
            return serialize_operation(db, existing, idempotent_replay=True)
        allocated = sum(
            (Decimal(value) for value in db.scalars(select(models.EconomicOperation.maximum_total_spend).where(
                models.EconomicOperation.parent_economic_operation_id == parent.id
            )).all() if value is not None),
            Decimal("0"),
        )
        if allocated + Decimal(evaluated["maximum_total_spend"]) > Decimal(parent.maximum_total_spend):
            raise EconomicKernelError(409, "child_budget_exceeds_parent_remaining", "Child maximum spend exceeds the parent's remaining immutable budget")
    now = _now()
    row = models.EconomicOperation(
        operation_id=str(uuid.uuid4()), requester_agent_id=canonical_id,
        parent_economic_operation_id=parent.id if parent is not None else None,
        idempotency_key=key,
        request_digest=request_digest, product_sku=product_sku, currency=evaluated["currency"],
        customer_price=evaluated["customer_price"], expected_variable_cost=evaluated["expected_variable_cost"],
        maximum_variable_cost=evaluated["maximum_variable_cost"], verification_cost=evaluated["verification_cost"],
        payment_fee_allowance=evaluated["payment_fee_allowance"], expected_total_cost=evaluated["expected_total_cost"],
        maximum_total_spend=evaluated["maximum_total_spend"], contribution_amount=evaluated["contribution_amount"],
        expected_margin_bps=evaluated["expected_margin_bps"], expected_cost_per_verified_outcome=evaluated["expected_cost_per_verified_outcome"],
        maximum_attempts=evaluated["maximum_attempts"], commercial_rights_state=evaluated["commercial_rights_state"],
        funding_required=evaluated["funding_required"], policy_eligible=evaluated["policy_eligible"],
        execution_eligible=evaluated["execution_eligible"], decision_reasons=evaluated["decision_reasons"],
        adapter_state="real_money_disabled", state="quoted", release_sha=release_identity()["release_sha"],
        quote_expires_at=now + timedelta(seconds=QUOTE_TTL_SECONDS), created_at=now, updated_at=now,
    )
    db.add(row)
    try:
        db.flush()
        db.add(models.EconomicTransition(
            transition_id=str(uuid.uuid4()), economic_operation_id=row.id, sequence=1,
            idempotency_key="quote:" + key, transition_digest=_digest({"to": "quoted", "request": request_digest}),
            from_state=None, to_state="quoted", reason_code="economic_preflight_recorded",
            evidence_authority="trusted_internal_product_profile", evidence_digest=_digest(evaluated),
            amount=row.customer_price, currency=row.currency, created_at=now,
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(models.EconomicOperation).where(
            models.EconomicOperation.requester_agent_id == canonical_id,
            models.EconomicOperation.idempotency_key == key,
        ))
        if existing is None or existing.request_digest != request_digest:
            raise EconomicKernelError(409, "economic_operation_conflict", "Concurrent economic preflight conflict")
        return serialize_operation(db, existing, idempotent_replay=True)
    db.refresh(row)
    return serialize_operation(db, row)


def get_operation(db: Session, *, requester_agent_id: int, operation_id: str) -> dict:
    operation_id = _valid_operation_id(operation_id)
    canonical_id = _canonical_agent_id(db, requester_agent_id)
    row = db.scalar(select(models.EconomicOperation).where(models.EconomicOperation.operation_id == operation_id))
    if row is None:
        raise EconomicKernelError(404, "economic_operation_not_found", "Economic operation not found")
    if row.requester_agent_id != canonical_id:
        raise EconomicKernelError(403, "economic_operation_forbidden", "Economic operation belongs to another logical requester")
    return serialize_operation(db, row)


def serialize_operation(db: Session, row: models.EconomicOperation, *, idempotent_replay: bool = False) -> dict:
    transitions = db.scalars(select(models.EconomicTransition).where(
        models.EconomicTransition.economic_operation_id == row.id
    ).order_by(models.EconomicTransition.sequence)).all()
    expired = _aware(row.quote_expires_at) <= _now() and row.state == "quoted"
    child_maxima = db.scalars(select(models.EconomicOperation.maximum_total_spend).where(
        models.EconomicOperation.parent_economic_operation_id == row.id
    )).all()
    allocated_child_spend = sum((Decimal(value) for value in child_maxima if value is not None), Decimal("0"))
    allocated_child_spend_s = _canonical_signed_calculation(allocated_child_spend)
    remaining_spend_s = None
    if row.maximum_total_spend is not None:
        remaining_spend_s = _canonical_signed_calculation(Decimal(row.maximum_total_spend) - allocated_child_spend)
    parent_operation_id = None
    if row.parent_economic_operation_id is not None:
        parent_operation_id = db.scalar(select(models.EconomicOperation.operation_id).where(
            models.EconomicOperation.id == row.parent_economic_operation_id
        ))
    return {
        "operation_id": row.operation_id, "canonical_requester_agent_id": row.requester_agent_id,
        "parent_operation_id": parent_operation_id,
        "product_sku": row.product_sku, "currency": row.currency, "customer_price": row.customer_price,
        "expected_variable_cost": row.expected_variable_cost, "maximum_variable_cost": row.maximum_variable_cost,
        "verification_cost": row.verification_cost, "payment_fee_allowance": row.payment_fee_allowance,
        "expected_total_cost": row.expected_total_cost, "maximum_total_spend": row.maximum_total_spend,
        "allocated_child_maximum_spend": allocated_child_spend_s,
        "remaining_unallocated_maximum_spend": remaining_spend_s,
        "contribution_amount": row.contribution_amount, "expected_margin_bps": row.expected_margin_bps,
        "expected_margin_state": (
            "not_applicable_zero_price_zero_cost"
            if Decimal(row.customer_price) == 0 and Decimal(row.expected_total_cost) == 0
            else "calculated"
        ),
        "minimum_margin_bps": MINIMUM_MARGIN_BPS, "standard_target_margin_bps": STANDARD_TARGET_MARGIN_BPS,
        "expected_cost_per_verified_outcome": row.expected_cost_per_verified_outcome,
        "maximum_attempts": row.maximum_attempts, "commercial_rights_state": row.commercial_rights_state,
        "funding_required": row.funding_required, "policy_eligible": row.policy_eligible,
        "execution_eligible": row.execution_eligible and not expired and row.state == "quoted",
        "decision_reasons": ["quote_expired"] if expired else row.decision_reasons,
        "state": row.state, "adapter_state": row.adapter_state,
        "payment_authorized": row.authorized_amount is not None, "reserve_established": row.reserved_amount is not None,
        "authorized_amount": row.authorized_amount, "reserved_amount": row.reserved_amount,
        "actual_cost": row.actual_cost, "settlement_amount": row.settlement_amount,
        "released_amount": row.released_amount,
        "execution_started": row.state in {"execution_started", "outcome_verified", "settlement_ready", "settled", "reserve_released"},
        "outcome_verified": row.state in {"outcome_verified", "settlement_ready", "settled", "reserve_released"},
        "settlement_ready": row.state in {"settlement_ready", "settled", "reserve_released"},
        "settlement_completed": row.state in {"settled", "reserve_released"},
        "real_settlement_revenue": row.settlement_amount or "0",
        "real_settlement_state": "not_enabled" if row.settlement_amount is None else "adapter_verified",
        "quote_expires_at": row.quote_expires_at.isoformat(), "idempotent_replay": idempotent_replay,
        "transitions": [{"transition_id": t.transition_id, "sequence": t.sequence, "from_state": t.from_state,
                         "to_state": t.to_state, "reason_code": t.reason_code,
                         "evidence_authority": t.evidence_authority, "evidence_digest": t.evidence_digest,
                         "amount": t.amount, "currency": t.currency, "created_at": t.created_at.isoformat()} for t in transitions],
        "truth_boundaries": {"requester_budget_is_not_funds": True, "legacy_payment_intent_is_not_funding": True,
                             "payment_authorization_is_not_settlement": True, "real_money_adapter_enabled": False,
                             "creates_vuo_or_return_evidence": False},
    }


class DisabledEconomicAdapter:
    enabled = False
    authority = "disabled"

    def verify(self, transition: str, evidence_reference: str) -> dict:
        raise EconomicKernelError(409, "real_money_adapter_disabled", "Real-money authorization, reserve, spend and settlement adapters are disabled")


DISABLED_ECONOMIC_ADAPTER = DisabledEconomicAdapter()


_ALLOWED_TRANSITIONS = {
    "quoted": {"payment_authorized", "execution_started", "failed", "cancelled"},
    "payment_authorized": {"funds_reserved", "failed", "cancelled"},
    "funds_reserved": {"execution_started", "failed", "cancelled"},
    "execution_started": {"outcome_verified", "failed", "cancelled"},
    "outcome_verified": {"settlement_ready", "failed", "cancelled"},
    "settlement_ready": {"settled", "failed", "cancelled"},
    "settled": {"reserve_released"},
    "reserve_released": set(), "failed": set(), "cancelled": set(),
}


def _direct_child_allocation(db: Session, row_id: int) -> Decimal:
    values = db.scalars(select(models.EconomicOperation.maximum_total_spend).where(
        models.EconomicOperation.parent_economic_operation_id == row_id
    )).all()
    return sum((Decimal(value) for value in values if value is not None), Decimal("0"))


def _adapter_evidence(adapter, transition: str, evidence_reference: str) -> tuple[str, str]:
    if not REAL_MONEY_EXECUTION_ENABLED or not getattr(adapter, "enabled", False):
        raise EconomicKernelError(409, "real_money_adapter_disabled", "Real-money authorization, reserve, spend and settlement adapters are disabled")
    verified = adapter.verify(transition, evidence_reference)
    if not isinstance(verified, dict):
        raise EconomicKernelError(409, "unverified_economic_evidence", "Adapter did not return verified evidence")
    authority, digest = verified.get("authority"), verified.get("digest")
    expected = {
        "payment_authorized": "payment_rail_verified",
        "funds_reserved": "payment_rail_verified",
        "execution_started": "internal_executor_verified",
        "settlement_ready": "provider_meter_verified",
        "settled": "payment_rail_verified",
        "reserve_released": "payment_rail_verified",
        "failed": "trusted_internal_control",
        "cancelled": "trusted_internal_control",
    }.get(transition)
    if authority != expected or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise EconomicKernelError(409, "unverified_economic_evidence", "Adapter evidence authority or digest is invalid")
    return authority, digest


def apply_economic_transition(
    db: Session, *, requester_agent_id: int, operation_id: str, to_state: str,
    idempotency_key: str, adapter=DISABLED_ECONOMIC_ADAPTER,
    evidence_reference: str = "", amount: str | None = None,
    currency: str | None = None, action_id: str | None = None,
) -> dict:
    """Internal adapter seam. No public route exposes this state mutation."""
    key = _valid_idempotency(idempotency_key)
    operation_id = _valid_operation_id(operation_id)
    canonical_id = _canonical_agent_id(db, requester_agent_id)
    row = db.scalar(select(models.EconomicOperation).where(
        models.EconomicOperation.operation_id == operation_id
    ).with_for_update())
    if row is None:
        raise EconomicKernelError(404, "economic_operation_not_found", "Economic operation not found")
    if row.requester_agent_id != canonical_id:
        raise EconomicKernelError(403, "economic_operation_forbidden", "Economic operation belongs to another logical requester")
    existing = db.scalar(select(models.EconomicTransition).where(
        models.EconomicTransition.economic_operation_id == row.id,
        models.EconomicTransition.idempotency_key == key,
    ))
    if currency is not None:
        currency = canonical_currency(currency)
    amount_value = amount_canonical = None
    if amount is not None:
        amount_value, amount_canonical = canonical_money(amount)
    money_transitions = {
        "payment_authorized", "funds_reserved", "execution_started",
        "settlement_ready", "settled", "reserve_released",
    }
    if to_state in money_transitions and (amount_canonical is None or currency is None):
        raise EconomicKernelError(422, "economic_amount_required", "Amount and matching currency are required for this transition")
    material = {
        "to_state": to_state, "amount": amount_canonical, "currency": currency,
        "action_id": action_id,
        "evidence_reference_digest": _digest(evidence_reference),
    }
    transition_digest = _digest(material)
    if existing is not None:
        if existing.transition_digest != transition_digest:
            raise EconomicKernelError(409, "idempotency_conflict", "Transition idempotency key was used for different material")
        return serialize_operation(db, row, idempotent_replay=True)
    if to_state not in _ALLOWED_TRANSITIONS.get(row.state, set()):
        raise EconomicKernelError(409, "illegal_economic_transition", f"Cannot transition from {row.state} to {to_state}")
    if _aware(row.quote_expires_at) <= _now() and row.state in {"quoted", "payment_authorized"}:
        raise EconomicKernelError(409, "quote_expired", "Expired quote cannot authorize execution")
    if not row.policy_eligible and to_state not in {"failed", "cancelled"}:
        raise EconomicKernelError(409, row.decision_reasons[0], "Economic policy blocks execution")
    row_currency = canonical_currency(row.currency)
    if currency is not None and currency != row_currency:
        raise EconomicKernelError(409, "currency_mismatch", "Transition currency must match immutable quote currency")
    evidence_authority = "aion_verified_action_evidence"
    evidence_digest = _digest({"operation": row.operation_id, "transition": to_state})
    reason_code = "economic_transition_verified"
    if to_state == "payment_authorized":
        price = Decimal(row.customer_price)
        if amount_value is None or amount_value != price:
            raise EconomicKernelError(409, "insufficient_authorized_funds", "Verified authorization must equal the immutable quoted customer price")
        evidence_authority, evidence_digest = _adapter_evidence(adapter, to_state, evidence_reference)
        row.authorized_amount = amount_canonical
    elif to_state == "funds_reserved":
        if amount_canonical != row.authorized_amount:
            raise EconomicKernelError(409, "reserve_not_established", "Verified reserve must equal the authorized quoted amount")
        evidence_authority, evidence_digest = _adapter_evidence(adapter, to_state, evidence_reference)
        row.reserved_amount = amount_canonical
    elif to_state == "execution_started":
        if amount_value is None or row.maximum_total_spend is None:
            raise EconomicKernelError(409, "unknown_maximum_cost", "Execution permission requires immutable maximum total spend")
        if amount_value > Decimal(row.maximum_total_spend):
            raise EconomicKernelError(409, "paid_fallback_requires_reauthorization", "Higher-cost execution requires a new quote and new authorization")
        if _direct_child_allocation(db, row.id) > 0:
            raise EconomicKernelError(409, "parent_budget_delegated_to_children", "A parent operation with allocated child budget cannot also execute directly")
        if row.funding_required:
            if row.reserved_amount is None:
                raise EconomicKernelError(409, "reserve_not_established", "Execution requires a verified reserve")
            if amount_value > Decimal(row.reserved_amount):
                raise EconomicKernelError(409, "insufficient_authorized_funds", "Execution permission exceeds verified reserved funds")
            evidence_authority, evidence_digest = _adapter_evidence(adapter, to_state, evidence_reference)
        else:
            if Decimal(row.maximum_total_spend or "0") != 0 or amount_value != 0:
                raise EconomicKernelError(409, "free_variable_cost_execution_prohibited", "Zero-price execution cannot incur variable cost")
            evidence_authority, reason_code = "trusted_internal_zero_cost_control", "known_zero_cost_execution_claimed"
    elif to_state == "outcome_verified":
        if not action_id:
            raise EconomicKernelError(409, "settlement_evidence_missing", "A verified ActionRun binding is required")
        action = db.scalar(select(models.ActionRun).where(models.ActionRun.action_id == action_id))
        if action is None or _canonical_agent_id(db, action.requester_agent_id) != canonical_id:
            raise EconomicKernelError(403, "action_evidence_forbidden", "Action evidence belongs to another requester")
        outcome = db.scalar(select(models.ActionOutcome).where(models.ActionOutcome.action_run_id == action.id))
        verification = db.scalar(select(models.ActionVerification).where(models.ActionVerification.action_run_id == action.id))
        if action.state != "completed" or outcome is None or not outcome.verified_outcome or verification is None or verification.state != "verified":
            raise EconomicKernelError(409, "settlement_evidence_missing", "Completed verified outcome evidence is required")
        execution_transition = db.scalar(select(models.EconomicTransition).where(
            models.EconomicTransition.economic_operation_id == row.id,
            models.EconomicTransition.to_state == "execution_started",
        ))
        if (
            execution_transition is None
            or action.started_at is None
            or action.completed_at is None
            or _aware(action.started_at) < _aware(execution_transition.created_at)
            or _aware(action.completed_at) < _aware(execution_transition.created_at)
        ):
            raise EconomicKernelError(409, "action_evidence_predates_execution_permission", "Verified action evidence must follow economic execution permission")
        row.action_run_id = action.id
        evidence_digest = _digest({"action_id": action.action_id, "outcome_id": outcome.id, "verification_id": verification.id})
        reason_code = "verified_action_outcome_bound"
    elif to_state == "settlement_ready":
        if amount_value is None or row.maximum_total_spend is None or amount_value > Decimal(row.maximum_total_spend):
            raise EconomicKernelError(409, "max_total_spend_exceeded", "Actual cost exceeds immutable maximum total spend")
        if row.action_run_id is not None:
            action = db.get(models.ActionRun, row.action_run_id)
            if (action.cost_amount is None) != (action.cost_currency is None):
                raise EconomicKernelError(409, "action_cost_evidence_invalid", "Action cost evidence must contain both amount and currency")
            if action.cost_amount is not None:
                action_cost, action_cost_s = canonical_money(action.cost_amount)
                if canonical_currency(action.cost_currency) != row_currency or action_cost != amount_value:
                    raise EconomicKernelError(409, "action_cost_evidence_mismatch", "Verified adapter cost must match existing ActionRun cost evidence")
        evidence_authority, evidence_digest = _adapter_evidence(adapter, to_state, evidence_reference)
        row.actual_cost = amount_canonical
    elif to_state == "settled":
        if amount_canonical != row.customer_price or row.reserved_amount is None or amount_value > Decimal(row.reserved_amount):
            raise EconomicKernelError(409, "settlement_amount_invalid", "Settlement must equal quoted price within verified reserve")
        evidence_authority, evidence_digest = _adapter_evidence(adapter, to_state, evidence_reference)
        row.settlement_amount = amount_canonical
    elif to_state == "reserve_released":
        expected_release = Decimal(row.reserved_amount or "0") - Decimal(row.settlement_amount or "0")
        _, expected_release_s = canonical_money(format(expected_release, "f"))
        if amount_canonical != expected_release_s:
            raise EconomicKernelError(409, "release_amount_invalid", "Released reserve must equal unused verified reserve")
        evidence_authority, evidence_digest = _adapter_evidence(adapter, to_state, evidence_reference)
        row.released_amount = amount_canonical
    else:
        evidence_authority = "trusted_internal_control"
        evidence_digest = _digest({"operation": row.operation_id, "transition": to_state, "reference": evidence_reference})
        reason_code = "trusted_terminal_transition"
    if evidence_authority in {"payment_rail_verified", "internal_executor_verified", "provider_meter_verified"}:
        row.adapter_state = "verified_adapter_evidence"
    sequence = (db.scalar(select(func.max(models.EconomicTransition.sequence)).where(
        models.EconomicTransition.economic_operation_id == row.id
    )) or 0) + 1
    transition = models.EconomicTransition(
        transition_id=str(uuid.uuid4()), economic_operation_id=row.id, sequence=sequence,
        idempotency_key=key, transition_digest=transition_digest, from_state=row.state,
        to_state=to_state, reason_code=reason_code, evidence_authority=evidence_authority,
        evidence_digest=evidence_digest, amount=amount_canonical, currency=currency,
        created_at=_now(),
    )
    row.state, row.updated_at = to_state, _now()
    db.add_all([row, transition])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.scalar(select(models.EconomicOperation).where(models.EconomicOperation.operation_id == operation_id))
        existing = db.scalar(select(models.EconomicTransition).where(
            models.EconomicTransition.economic_operation_id == row.id,
            models.EconomicTransition.idempotency_key == key,
        )) if row is not None else None
        if row is None or existing is None or existing.transition_digest != transition_digest:
            raise EconomicKernelError(409, "economic_transition_conflict", "Concurrent transition conflict")
        return serialize_operation(db, row, idempotent_replay=True)
    db.refresh(row)
    return serialize_operation(db, row)
