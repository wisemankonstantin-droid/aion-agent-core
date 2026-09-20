"""One bounded real external-supply execution path.

This adapter intentionally supports one fixed, useful capability from one
official zero-price provider. It is not a general URL fetcher or marketplace.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from . import safe_http
from .economic_kernel import TrustedEconomicPlan, evaluate_plan


CAPABILITY = "world_bank.population.latest"
PROVIDER_IDENTIFIER = "world_bank_wdi"
PROVIDER_NAME = "World Bank World Development Indicators"
PROVIDER_BASE = "https://api.worldbank.org/v2"
DATASET_URL = (
    "https://datacatalog.worldbank.org/search/dataset/0037712/"
    "World-Development-Indicators"
)
LICENSE = "CC-BY-4.0"
VERIFICATION_METHOD = "world_bank_wdi_population_schema_v1"
MAX_RESPONSE_BYTES = 128 * 1024
TIMEOUT_SECONDS = 7.0
IDEMPOTENCY_KEY_MAX_LENGTH = 128
RATE_LIMIT = 20
RATE_WINDOW_SECONDS = 60.0
CONCURRENCY_LIMIT = 4

_COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
_YEAR = re.compile(r"^[0-9]{4}$")
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_RATE_TIMES = deque()
_RATE_LOCK = threading.Lock()
_SLOTS = threading.BoundedSemaphore(CONCURRENCY_LIMIT)
_FETCH = safe_http.fetch_bytes

_ECONOMIC_PLAN = TrustedEconomicPlan(
    product_sku="aion.world_bank.population.latest.v1",
    currency="USD",
    customer_price="0",
    expected_variable_cost="0",
    maximum_variable_cost="0",
    verification_cost="0",
    payment_fee_allowance="0",
    maximum_attempts=1,
    commercial_rights_state="allowed",
    maximum_total_spend_cap="0",
    direct_expected_cost_per_vuo="0",
)


class OfficialDataExecutionError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class PopulationExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    capability: str = Field(default=CAPABILITY, min_length=1, max_length=120)
    country_code: str = Field(min_length=2, max_length=2)
    authorize_external_contact: bool

    @field_validator("capability")
    @classmethod
    def _fixed_capability(cls, value: str) -> str:
        if value != CAPABILITY:
            raise ValueError(f"capability must be {CAPABILITY}")
        return value

    @field_validator("country_code")
    @classmethod
    def _canonical_country_code(cls, value: str) -> str:
        canonical = value.upper()
        if not _COUNTRY_CODE.fullmatch(canonical):
            raise ValueError("country_code must be a two-letter ISO country code")
        return canonical


class PopulationUsefulnessAcknowledgement(BaseModel):
    """Optional requester feedback; never a prerequisite for execution completion."""
    model_config = ConfigDict(extra="forbid")

    usefulness_confirmed: bool
    usefulness_evidence: str

    @field_validator("usefulness_confirmed")
    @classmethod
    def _confirmed(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("usefulness_confirmed must be true")
        return value

    @field_validator("usefulness_evidence")
    @classmethod
    def _fixed_evidence(cls, value: str) -> str:
        if value != "requester_confirms_population_result_was_useful":
            raise ValueError(
                "usefulness_evidence must be "
                "requester_confirms_population_result_was_useful"
            )
        return value


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_json(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return _digest_bytes(encoded)


def _idempotency_key(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not _IDEMPOTENCY_KEY.fullmatch(normalized):
        raise OfficialDataExecutionError(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key must be 1-128 characters using letters, digits, '.', '_', ':' or '-'",
        )
    return normalized


def _allow_execution(now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    cutoff = current - RATE_WINDOW_SECONDS
    with _RATE_LOCK:
        while _RATE_TIMES and _RATE_TIMES[0] <= cutoff:
            _RATE_TIMES.popleft()
        if len(_RATE_TIMES) >= RATE_LIMIT:
            return False
        _RATE_TIMES.append(current)
        return True


def _provider_endpoint(country_code: str) -> str:
    return (
        f"{PROVIDER_BASE}/country/{country_code}/indicator/SP.POP.TOTL"
        "?format=json&mrv=1&per_page=1"
    )


def _economic_policy() -> dict:
    return evaluate_plan(
        _ECONOMIC_PLAN, requested_currency="USD", requester_max_price=None
    )


def _provider_route(country_code: str) -> dict:
    policy = _economic_policy()
    return {
        "supply_tier": "manually_qualified_external_api",
        "provider": {
            "identifier": PROVIDER_IDENTIFIER,
            "name": PROVIDER_NAME,
            "capability": CAPABILITY,
            "endpoint": _provider_endpoint(country_code),
            "authentication_requirement": "none",
            "qualification_state": "eligible",
            "commercial_rights": {
                "state": "known_compatible_with_attribution",
                "license": LICENSE,
                "dataset_url": DATASET_URL,
                "attribution_required": True,
            },
        },
        "candidate_count": 1,
        "selection_reason": "only_eligible_provider_for_fixed_capability",
        "fallback": {
            "available": False,
            "reason": "no_fallback_provider_available",
        },
        "economics": {
            "currency": "USD",
            "provider_maximum_cost": "0",
            "customer_price": "0",
            "variable_cost_funded": True,
            "payment_required": False,
            "margin_policy": "not_applicable_zero_price_zero_variable_cost",
            "policy_evaluation_source": "package_6a_economic_kernel",
            "policy_eligible": policy["policy_eligible"],
            "execution_eligible": policy["execution_eligible"],
            "maximum_total_spend": policy["maximum_total_spend"],
            "verification_cost": policy["verification_cost"],
            "payment_fee_allowance": policy["payment_fee_allowance"],
            "expected_cost_per_verified_outcome": policy[
                "expected_cost_per_verified_outcome"
            ],
            "decision_reasons": policy["decision_reasons"],
        },
        "execution_eligible": policy["execution_eligible"],
    }


def _request_material(payload: PopulationExecutionRequest) -> dict:
    return {
        "capability": payload.capability,
        "country_code": payload.country_code,
        "authorize_external_contact": payload.authorize_external_contact,
    }


def _existing_for_key(
    db: Session, requester_agent_id: int, idempotency_key: str
) -> models.OfficialDataExecution | None:
    return db.scalar(
        select(models.OfficialDataExecution).where(
            models.OfficialDataExecution.requester_agent_id == requester_agent_id,
            models.OfficialDataExecution.idempotency_key == idempotency_key,
        )
    )


def _claim(
    db: Session,
    *,
    requester_agent_id: int,
    payload: PopulationExecutionRequest,
    idempotency_key: str,
) -> tuple[models.OfficialDataExecution, bool]:
    request_digest = _digest_json(_request_material(payload))
    existing = _existing_for_key(db, requester_agent_id, idempotency_key)
    if existing is not None:
        if existing.request_digest != request_digest:
            raise OfficialDataExecutionError(
                409,
                "idempotency_conflict",
                "Idempotency-Key is already bound to different execution material",
            )
        return existing, False

    row = models.OfficialDataExecution(
        execution_id=str(uuid.uuid4()),
        requester_agent_id=requester_agent_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        capability=CAPABILITY,
        country_code=payload.country_code,
        provider_identifier=PROVIDER_IDENTIFIER,
        provider_endpoint=_provider_endpoint(payload.country_code),
        commercial_rights_state="known_compatible_with_attribution",
        provider_maximum_cost="0",
        customer_price="0",
        currency="USD",
        state="claimed",
        failure_class=None,
        outbound_attempts=0,
        http_status=None,
        response_digest=None,
        normalized_result=None,
        verification_state="not_performed",
        verification_method=VERIFICATION_METHOD,
        capability_verified=False,
        useful_outcome=False,
        usefulness_evidence=None,
        created_at=_now(),
        completed_at=None,
        acknowledged_at=None,
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row, True
    except IntegrityError:
        db.rollback()
        existing = _existing_for_key(db, requester_agent_id, idempotency_key)
        if existing is None:
            raise
        if existing.request_digest != request_digest:
            raise OfficialDataExecutionError(
                409,
                "idempotency_conflict",
                "Idempotency-Key is already bound to different execution material",
            )
        return existing, False


def _normalize_population(payload: object, country_code: str) -> dict:
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not isinstance(payload[0], dict)
        or not isinstance(payload[1], list)
    ):
        raise ValueError("malformed_provider_payload")
    metadata = payload[0]
    if str(metadata.get("sourceid") or "") != "2":
        raise ValueError("unexpected_provider_source")
    last_updated = str(metadata.get("lastupdated") or "")
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", last_updated):
        raise ValueError("invalid_provider_freshness")
    try:
        updated_date = datetime.strptime(last_updated, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("invalid_provider_freshness") from exc
    if updated_date > _now().date():
        raise ValueError("invalid_provider_freshness")

    for item in payload[1]:
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        indicator = item.get("indicator")
        country = item.get("country")
        value = item.get("value")
        year = str(item.get("date") or "")
        if (
            not isinstance(indicator, dict)
            or indicator.get("id") != "SP.POP.TOTL"
            or not isinstance(country, dict)
            or str(country.get("id") or "").upper() != country_code
            or not _YEAR.fullmatch(year)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise ValueError("provider_result_verification_failed")
        return {
            "capability": CAPABILITY,
            "country_code": country_code,
            "country_name": str(country.get("value") or "")[:240],
            "country_iso3_code": str(item.get("countryiso3code") or "")[:3],
            "year": int(year),
            "population": value,
            "indicator_id": "SP.POP.TOTL",
            "indicator_name": str(indicator.get("value") or "")[:240],
            "provider_dataset_last_updated": last_updated,
            "freshness": {
                "semantics": "latest_available_not_current_year_claim",
                "observation_year": int(year),
                "provider_dataset_last_updated": last_updated,
            },
            "provider": PROVIDER_NAME,
            "provider_identifier": PROVIDER_IDENTIFIER,
            "source_attribution": "World Bank, World Development Indicators",
            "license": LICENSE,
            "dataset_url": DATASET_URL,
        }
    raise ValueError("provider_returned_no_population_value")


def _failure_class(result: safe_http.FetchResult) -> str:
    error = str(result.error or "")
    lowered = error.lower()
    if result.error == "response_too_large":
        return "response_too_large"
    if result.error == "http_429":
        return "rate_limited"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "ssl" in lowered or "tls" in lowered or "certificate" in lowered:
        return "tls_failure"
    if "gaierror" in lowered or lowered.startswith("dns_"):
        return "dns_failure"
    if lowered in {
        "redirect_rejected",
        "content_encoding_rejected",
        "url_must_be_public_https",
    } or lowered.startswith(("non_public_address:", "too_many_resolved_addresses")):
        return "https_policy_failure"
    if lowered.startswith("http_") or result.status is not None:
        return "provider_http_failure"
    if result.status is None:
        return "connectivity_failure"
    return "provider_failure"


def _record_failure(
    db: Session,
    row: models.OfficialDataExecution,
    *,
    failure_class: str,
    attempts: int = 0,
    status: int | None = None,
    response_digest: str | None = None,
) -> None:
    row.state = "failed"
    row.failure_class = failure_class[:96]
    row.outbound_attempts = max(0, min(int(attempts), 1))
    row.http_status = status
    row.response_digest = response_digest
    row.verification_state = "failed" if response_digest else "not_performed"
    row.capability_verified = False
    row.completed_at = _now()
    db.add(row)
    db.commit()


def _counts(db: Session, requester_agent_id: int) -> tuple[int, int]:
    verified = db.scalar(
        select(func.count()).select_from(models.OfficialDataExecution).where(
            models.OfficialDataExecution.requester_agent_id == requester_agent_id,
            models.OfficialDataExecution.state == "completed",
            models.OfficialDataExecution.capability_verified.is_(True),
        )
    ) or 0
    useful = db.scalar(
        select(func.count()).select_from(models.OfficialDataExecution).where(
            models.OfficialDataExecution.requester_agent_id == requester_agent_id,
            models.OfficialDataExecution.useful_outcome.is_(True),
        )
    ) or 0
    return int(verified), int(useful)


def _serialize(
    db: Session,
    row: models.OfficialDataExecution,
    *,
    idempotent_replay: bool = False,
) -> dict:
    verified_count, useful_count = _counts(db, row.requester_agent_id)
    return {
        "execution_id": row.execution_id,
        "state": row.state,
        "failure_class": row.failure_class,
        "idempotent_replay": idempotent_replay,
        "request": {
            "capability": row.capability,
            "country_code": row.country_code,
            "request_digest": row.request_digest,
            "external_contact_authorized": True,
        },
        "intake_trace": {
            "raw_request": {
                "capability": row.capability,
                "country_code": row.country_code,
                "external_contact_authorized": True,
            },
            "aion_interpretation": {
                "method": "deterministic_fixed_capability_v1",
                "need": "latest_available_population_for_country",
                "country_code": row.country_code,
            },
            "executable_requirement": {
                "provider_identifier": row.provider_identifier,
                "indicator_id": "SP.POP.TOTL",
                "selection_rule": "latest_available_non_null_observation",
            },
            "conversation_intelligence": {
                "state": "not_applicable_structured_api_intake",
                "requester_statement_inferred": False,
            },
        },
        "route": _provider_route(row.country_code),
        "execution": {
            "provider_invoked": row.outbound_attempts > 0,
            "outbound_attempts": row.outbound_attempts,
            "http_status": row.http_status,
            "response_digest": row.response_digest,
            "normalized_result": row.normalized_result,
            "actual_provider_cost": "0",
            "actual_customer_price": "0",
            "currency": "USD",
        },
        "verification": {
            "state": row.verification_state,
            "method": row.verification_method,
            "capability_verified": row.capability_verified,
        },
        "outcome": {
            "machine_completion_state": (
                "machine_verified_result_delivered"
                if row.state == "completed" and row.capability_verified
                else "not_completed"
            ),
            "human_usefulness_confirmation_required": False,
            "optional_requester_feedback_recorded": row.useful_outcome,
            "optional_requester_feedback": row.usefulness_evidence,
            "legacy_vuo_state": (
                "requester_confirmed_verified_useful_outcome"
                if row.useful_outcome
                else "optional_feedback_not_recorded"
                if row.state == "completed"
                else "not_established"
            ),
        },
        "requester_history": {
            "verified_execution_count": verified_count,
            "confirmed_useful_outcome_count": useful_count,
            "returning_requester_recognized_by_authenticated_agent_id": True,
        },
        "timestamps": {
            "created_at": row.created_at.isoformat(),
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            "acknowledged_at": (
                row.acknowledged_at.isoformat() if row.acknowledged_at else None
            ),
        },
        "truth_boundaries": {
            "zero_price_execution_is_not_revenue_or_settlement": True,
            "machine_verified_completion_does_not_require_human_acknowledgement": True,
            "requester_feedback_is_optional_learning_input": True,
            "repository_or_test_execution_is_not_production_use": True,
            "payment_settlement_and_positive_margin_not_claimed": True,
        },
    }


def execute_population_lookup(
    db: Session,
    *,
    requester_agent_id: int,
    payload: PopulationExecutionRequest,
    idempotency_key: str | None,
) -> dict:
    if payload.authorize_external_contact is not True:
        raise OfficialDataExecutionError(
            422,
            "external_contact_not_authorized",
            "authorize_external_contact=true is required",
        )
    policy = _economic_policy()
    if not policy["execution_eligible"]:
        reasons = ", ".join(policy.get("decision_reasons") or ["unknown"])
        raise OfficialDataExecutionError(
            409,
            "economic_policy_denied",
            f"Economic policy denied execution: {reasons}",
        )
    key = _idempotency_key(idempotency_key)
    row, created = _claim(
        db,
        requester_agent_id=requester_agent_id,
        payload=payload,
        idempotency_key=key,
    )
    if not created:
        return _serialize(db, row, idempotent_replay=True)
    if not _allow_execution() or not _SLOTS.acquire(blocking=False):
        _record_failure(db, row, failure_class="rate_limited")
        return _serialize(db, row)

    try:
        result = _FETCH(
            "GET",
            row.provider_endpoint,
            policy=safe_http.FetchPolicy(
                timeout_seconds=TIMEOUT_SECONDS,
                max_response_bytes=MAX_RESPONSE_BYTES,
                max_attempts=1,
                max_resolved_addresses=4,
                user_agent="AION-Official-Data-Execution/0.8.0",
            ),
        )
        if result.error or result.status != 200 or result.body is None:
            _record_failure(
                db,
                row,
                failure_class=_failure_class(result),
                attempts=result.attempts,
                status=result.status,
            )
            return _serialize(db, row)

        response_digest = _digest_bytes(result.body)
        try:
            document = json.loads(result.body.decode("utf-8"))
            normalized = _normalize_population(document, payload.country_code)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            failure = str(exc) if isinstance(exc, ValueError) else "malformed_provider_payload"
            _record_failure(
                db,
                row,
                failure_class=failure,
                attempts=result.attempts,
                status=result.status,
                response_digest=response_digest,
            )
            return _serialize(db, row)

        row.state = "completed"
        row.failure_class = None
        row.outbound_attempts = 1
        row.http_status = 200
        row.response_digest = response_digest
        row.normalized_result = normalized
        row.verification_state = "verified"
        row.capability_verified = True
        row.completed_at = _now()
        db.add(row)
        db.commit()
        db.refresh(row)
        return _serialize(db, row)
    finally:
        _SLOTS.release()


def get_population_execution(
    db: Session, *, requester_agent_id: int, execution_id: str
) -> dict:
    try:
        normalized_id = str(uuid.UUID(str(execution_id)))
    except (TypeError, ValueError, AttributeError):
        raise OfficialDataExecutionError(404, "execution_not_found", "Execution not found")
    row = db.scalar(
        select(models.OfficialDataExecution).where(
            models.OfficialDataExecution.execution_id == normalized_id,
            models.OfficialDataExecution.requester_agent_id == requester_agent_id,
        )
    )
    if row is None:
        raise OfficialDataExecutionError(404, "execution_not_found", "Execution not found")
    return _serialize(db, row)


def acknowledge_population_usefulness(
    db: Session,
    *,
    requester_agent_id: int,
    execution_id: str,
    payload: PopulationUsefulnessAcknowledgement,
) -> dict:
    data = get_population_execution(
        db, requester_agent_id=requester_agent_id, execution_id=execution_id
    )
    row = db.scalar(
        select(models.OfficialDataExecution).where(
            models.OfficialDataExecution.execution_id == data["execution_id"],
            models.OfficialDataExecution.requester_agent_id == requester_agent_id,
        )
    )
    if row is None:
        raise OfficialDataExecutionError(404, "execution_not_found", "Execution not found")
    if row.state != "completed" or not row.capability_verified:
        raise OfficialDataExecutionError(
            409,
            "verified_result_required",
            "Usefulness can be acknowledged only for a verified completed result",
        )
    if row.useful_outcome:
        if row.usefulness_evidence != payload.usefulness_evidence:
            raise OfficialDataExecutionError(
                409,
                "usefulness_conflict",
                "Execution already has different usefulness evidence",
            )
        return _serialize(db, row, idempotent_replay=True)

    row.useful_outcome = True
    row.usefulness_evidence = payload.usefulness_evidence
    row.acknowledged_at = _now()
    db.add(row)
    db.commit()
    db.refresh(row)
    return _serialize(db, row)
