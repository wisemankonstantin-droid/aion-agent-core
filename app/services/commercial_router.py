"""Commercial Router V1: bounded supply qualification and fail-closed route planning.

V1 deliberately does not create an economic operation, contact a provider's
interaction endpoint, or touch a payment rail. External discovery may contact a
public registry and declared agent-card URLs under the existing bounded discovery
policy. A route is never executable while provider price, maximum cost, or
commercial rights are unknown.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from ipaddress import ip_address
import re
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..security import require_participation_reader
from .economic_kernel import (
    MINIMUM_MARGIN_BPS,
    REAL_MONEY_EXECUTION_ENABLED,
    STANDARD_TARGET_MARGIN_BPS,
    EconomicKernelError,
    canonical_currency,
    canonical_money,
)
from .external_registry import DiscoveryResult, discover_external_agents_with_status


ROUTE_VERSION = "commercial_router_v1"
MAX_ROUTE_CANDIDATES = 5
MAX_COMMERCIAL_ROUTE_BODY_BYTES = 16 * 1024
_DISCOVER = discover_external_agents_with_status
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:@/+~-]{1,240}$")
_REMOTE_SECRET = re.compile(
    r"(?i)\b(?:Bearer\s+[^\s,;]+|(?:api[_-]?key|password|passwd|secret|token|credential)\s*[:=]\s*[^\s,;]+)"
)
_LONG_REMOTE_TOKEN = re.compile(r"\b(?=[A-Za-z0-9_+/=-]{40,}\b)(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_+/=-]+\b")
_URL_SECRET_PATH = re.compile(
    r"(?i)(?:^|/)(?:bearer|api[_-]?key|password|passwd|secret|token|credential)(?:$|[/=:._-])"
)
_CANONICAL_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")


def _bounded_identifier(value: object) -> str | None:
    identifier = str(value or "")
    if (
        not identifier
        or not _IDENTIFIER.fullmatch(identifier)
        or any(ord(character) < 32 or ord(character) == 127 for character in identifier)
    ):
        return None
    return identifier


def _safe_remote_text(value: object, maximum: int) -> str | None:
    text = "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " "
        for character in str(value or "")
    )
    text = _REMOTE_SECRET.sub("[REDACTED_REMOTE_SECRET]", text)
    text = _LONG_REMOTE_TOKEN.sub("[REDACTED_REMOTE_SECRET]", text)
    text = " ".join(text.split())[:maximum]
    return text or None


def _url_parts(value: object):
    text = str(value or "")
    if not text or len(text) > 1_000 or any(ord(character) <= 32 or ord(character) == 127 for character in text):
        return None
    try:
        parsed = urlsplit(text)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return None
        _ = parsed.port
        try:
            if not ip_address(parsed.hostname).is_global:
                return None
        except ValueError:
            pass
        decoded_path = unquote(parsed.path)
        if _URL_SECRET_PATH.search(decoded_path) or _LONG_REMOTE_TOKEN.search(decoded_path):
            return None
        return text, parsed
    except (TypeError, ValueError):
        return None


def _safe_display_url(value: object) -> str | None:
    result = _url_parts(value)
    if result is None:
        return None
    _, parsed = result
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _safe_interaction_url(value: object) -> str | None:
    result = _url_parts(value)
    if result is None:
        return None
    text, parsed = result
    if parsed.query or parsed.fragment:
        return None
    return text


def _provider_key(candidate: dict) -> tuple[str, str, str, str] | None:
    identifier = _bounded_identifier(candidate.get("identifier"))
    interaction_url = _safe_interaction_url(candidate.get("interaction_url"))
    binding = str(candidate.get("protocol_binding") or "").upper()
    version = str(candidate.get("protocol_version") or "")
    if (
        identifier is None
        or interaction_url is None
        or binding != "JSONRPC"
        or version != "1.0"
    ):
        return None
    return identifier, interaction_url, binding, version


class CommercialRoutePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    need: str = Field(min_length=1, max_length=128)
    currency: str = Field(default="USD", min_length=3, max_length=16)
    requester_max_price: str | None = Field(default=None, max_length=32)
    candidate_identifier: str | None = Field(default=None, min_length=1, max_length=240)

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        try:
            return canonical_currency(value)
        except EconomicKernelError as exc:
            raise ValueError(exc.message) from exc

    @field_validator("requester_max_price")
    @classmethod
    def _budget(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            _, canonical = canonical_money(value)
            return canonical
        except EconomicKernelError as exc:
            raise ValueError(exc.message) from exc

    @field_validator("need", "candidate_identifier")
    @classmethod
    def _bounded_text(cls, value: str | None) -> str | None:
        if value is not None and any(
            ord(character) < 32 or ord(character) == 127 for character in value
        ):
            raise ValueError("Control characters are not permitted")
        return value


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _eligible(candidate: dict) -> bool:
    return bool(
        _provider_key(candidate)
        and candidate.get("manifest_reachable")
        and candidate.get("card_parseable")
        and candidate.get("declared_a2a_v1_jsonrpc")
        and candidate.get("interaction_url_validated")
        and candidate.get("authentication_requirement") == "none"
        and _safe_interaction_url(candidate.get("interaction_url"))
    )


def _provider_history(db: Session, provider_keys: list[tuple[str, str, str, str]]) -> dict[tuple[str, str, str, str], dict]:
    history = {
        provider_key: {
            "recorded_outcomes": 0,
            "verified_callability_outcomes": 0,
            "failed_outcomes": 0,
            "failure_classes": {},
            "last_verified_at": None,
        }
        for provider_key in provider_keys
    }
    if not provider_keys:
        return history

    identifiers = sorted({provider_key[0] for provider_key in provider_keys})

    rows = db.execute(
        select(models.ActionRun, models.ActionOutcome, models.ActionVerification)
        .join(models.ActionOutcome, models.ActionOutcome.action_run_id == models.ActionRun.id)
        .outerjoin(
            models.ActionVerification,
            (models.ActionVerification.action_run_id == models.ActionRun.id)
            & (models.ActionVerification.action_outcome_id == models.ActionOutcome.id),
        )
        .where(models.ActionRun.selected_provider_identifier.in_(identifiers))
    ).all()
    counters = {provider_key: Counter() for provider_key in provider_keys}
    for run, outcome, verification in rows:
        provider_key = (
            str(run.selected_provider_identifier or ""),
            str(run.interaction_url or ""),
            str(run.protocol_binding or "").upper(),
            str(run.protocol_version or ""),
        )
        if provider_key not in history:
            continue
        item = history[provider_key]
        item["recorded_outcomes"] += 1
        if (
            run.state == "completed"
            and outcome.callability_verified
            and outcome.verified_outcome
            and outcome.proof_present
            and verification is not None
            and verification.action_run_id == run.id
            and verification.action_outcome_id == outcome.id
            and verification.verification_method == "a2a_nonce_roundtrip_v1"
            and verification.state == "verified"
            and bool(_CANONICAL_SHA256.fullmatch(str(verification.challenge_digest or "")))
            and bool(_CANONICAL_SHA256.fullmatch(str(verification.proof_digest or "")))
        ):
            item["verified_callability_outcomes"] += 1
            completed_at = _aware(verification.verified_at)
            current = item["last_verified_at"]
            if completed_at is not None and (current is None or completed_at > current):
                item["last_verified_at"] = completed_at
        if outcome.failure_class:
            item["failed_outcomes"] += 1
            counters[provider_key][str(outcome.failure_class)[:64]] += 1

    for provider_key, item in history.items():
        item["failure_classes"] = dict(sorted(counters[provider_key].items()))
        if item["last_verified_at"] is not None:
            item["last_verified_at"] = item["last_verified_at"].isoformat()
    return history


def _bounded_candidate(candidate: dict, history: dict) -> dict:
    identifier = _bounded_identifier(candidate.get("identifier"))
    verified_count = int(history.get("verified_callability_outcomes") or 0)
    return {
        "source": _safe_remote_text(candidate.get("source"), 80),
        "identifier": identifier,
        "name": _safe_remote_text(candidate.get("name"), 240),
        "description": _safe_remote_text(candidate.get("description"), 500) or "",
        "agent_card_url": _safe_display_url(candidate.get("url")),
        "interaction_url": _safe_interaction_url(candidate.get("interaction_url")),
        "protocol_binding": _safe_remote_text(candidate.get("protocol_binding"), 40),
        "protocol_version": _safe_remote_text(candidate.get("protocol_version"), 40),
        "manifest_reachable": bool(candidate.get("manifest_reachable")),
        "card_parseable": bool(candidate.get("card_parseable")),
        "declared_a2a_v1_jsonrpc": bool(candidate.get("declared_a2a_v1_jsonrpc")),
        "interaction_url_validated": bool(candidate.get("interaction_url_validated")),
        "authentication_requirement": _safe_remote_text(candidate.get("authentication_requirement") or "unknown", 40),
        "qualification_state": "declaration_qualified" if _eligible(candidate) else "ineligible",
        "registry_verified_claim": candidate.get("registry_verified_claim") if isinstance(candidate.get("registry_verified_claim"), bool) else None,
        "registry_verified_claim_semantics": "registry_claim_only_not_aion_verification",
        "provider_verification_state": (
            "historical_callability_verified"
            if verified_count > 0
            else "declaration_qualified_only"
            if _eligible(candidate)
            else "not_qualified"
        ),
        "verified_work_history": {
            "recorded_outcomes": int(history.get("recorded_outcomes") or 0),
            "verified_callability_outcomes": verified_count,
            "failed_outcomes": int(history.get("failed_outcomes") or 0),
            "failure_classes": dict(history.get("failure_classes") or {}),
            "last_verified_at": history.get("last_verified_at"),
        },
    }


def _ranking_key(candidate: dict) -> tuple:
    history = candidate["verified_work_history"]
    return (
        -int(history["verified_callability_outcomes"]),
        int(history["failed_outcomes"]),
        str(candidate.get("identifier") or ""),
        str(candidate.get("interaction_url") or ""),
    )


def _commercial_block(payload: CommercialRoutePlanRequest, *, selected: dict | None) -> dict:
    reasons = [
        "provider_price_unknown",
        "unknown_maximum_cost",
        "commercial_rights_unknown",
        "margin_not_computable",
        "payment_not_authorized",
        "reserve_not_established",
        "real_money_adapter_disabled",
    ]
    if selected is None:
        reasons.insert(0, "no_qualified_provider")
    return {
        "currency": payload.currency,
        "requester_max_price": payload.requester_max_price,
        "requester_budget_semantics": "preference_not_funds",
        "provider_price_state": "unknown",
        "provider_expected_cost": None,
        "provider_maximum_cost": None,
        "verification_cost": None,
        "payment_fee_allowance": None,
        "aion_routing_fee": None,
        "customer_price": None,
        "expected_contribution_amount": None,
        "expected_margin_bps": None,
        "minimum_margin_bps": MINIMUM_MARGIN_BPS,
        "standard_target_margin_bps": STANDARD_TARGET_MARGIN_BPS,
        "commercial_rights_state": "unknown",
        "funding_state": "not_evaluated_provider_cost_unknown",
        "policy_eligible": False,
        "execution_eligible": False,
        "decision_reasons": reasons,
    }


def plan_commercial_route(
    db: Session,
    *,
    requester_agent_id: int,
    payload: CommercialRoutePlanRequest,
) -> dict:
    # requester_agent_id is intentionally not persisted in V1; authentication
    # scopes the route-planning surface without manufacturing lifecycle evidence.
    _ = requester_agent_id
    discovery: DiscoveryResult = _DISCOVER(payload.need, MAX_ROUTE_CANDIDATES)
    raw = list(discovery.results[:MAX_ROUTE_CANDIDATES])
    provider_keys = sorted({
        provider_key
        for candidate in raw
        if (provider_key := _provider_key(candidate)) is not None
    })
    history = _provider_history(db, provider_keys)
    candidates = [
        _bounded_candidate(candidate, history.get(_provider_key(candidate), {}))
        for candidate in raw
    ]

    relevant = candidates
    if payload.candidate_identifier is not None:
        relevant = [candidate for candidate in candidates if candidate.get("identifier") == payload.candidate_identifier]

    eligible = [candidate for candidate in relevant if candidate["qualification_state"] == "declaration_qualified"]
    selected = sorted(eligible, key=_ranking_key)[0] if eligible else None

    if payload.candidate_identifier is not None and not relevant:
        state = "candidate_not_found"
    elif payload.candidate_identifier is not None and relevant and selected is None:
        state = "candidate_ineligible"
    elif selected is not None:
        state = "qualified_unpriced"
    elif discovery.failure_class:
        state = "discovery_unavailable"
    else:
        state = "no_eligible_candidate"

    provider_state = selected["provider_verification_state"] if selected else "none_selected"
    outbound_attempts = int((discovery.resource_bounds or {}).get("outbound_attempts_used") or 0)
    next_actions: list[dict[str, Any]] = []
    if selected is not None:
        next_actions.append(
            {
                "action": "verify_external_callability",
                "required_before_current-job_execution": True,
                "endpoint": "/actions/verify-callability",
                "note": "Historical evidence affects ranking only. Fresh current-job verification still requires explicit authorization to contact this interaction endpoint.",
            }
        )
    else:
        next_actions.append(
            {
                "action": "refine_need_or_add_supply_adapter",
                "required": True,
                "note": "No safely qualified provider was selected from the bounded discovery result.",
            }
        )
    next_actions.extend(
        [
            {
                "action": "resolve_trusted_provider_pricing_and_commercial_rights",
                "required": True,
                "note": "An executable quote requires a trusted provider price/max-cost source and known commercial rights.",
            },
            {
                "action": "economic_preflight_after_trusted_pricing",
                "required": True,
                "note": "AION must re-evaluate maximum spend and contribution margin before any paid execution.",
            },
            {
                "action": "real_payment_human_gate",
                "required": True,
                "note": "Real-money activation remains a separate Human Gate even after an executable quote exists.",
            },
        ]
    )

    return {
        "route_version": ROUTE_VERSION,
        "state": state,
        "need": payload.need,
        "supply_source": "global_a2a_registry",
        "discovery": {
            "status": discovery.status,
            "failure_class": discovery.failure_class,
            "resource_bounds": dict(discovery.resource_bounds or {}),
            "result_count": len(candidates),
        },
        "candidates": candidates,
        "selected_provider": selected,
        "provider_verification_state": provider_state,
        "commercial": _commercial_block(payload, selected=selected),
        "execution": {
            "mode": "planning_only",
            "external_discovery_performed": True,
            "registry_or_manifest_discovery_contact_may_have_occurred": outbound_attempts > 0,
            "provider_interaction_endpoint_contacted": False,
            "provider_execution_started": False,
            "payment_rail_contacted": False,
            "economic_operation_created": False,
            "real_money_execution_enabled": bool(REAL_MONEY_EXECUTION_ENABLED),
        },
        "next_actions": next_actions,
        "truth_boundaries": {
            "registry_verified_claim_is_not_aion_verification": True,
            "declaration_is_not_callability_proof": True,
            "historical_callability_is_not_current_job_completion": True,
            "route_plan_is_not_executable_quote": True,
            "route_plan_is_not_authorization_reserve_payment_settlement_or_revenue": True,
            "route_plan_is_not_vuo_or_adoption_proof": True,
            "requester_budget_is_not_funds": True,
            "no_provider_price_assumed": True,
        },
    }


class _CommercialRouteBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path", "").rstrip("/") != "/commercial/routes/plan"
        ):
            return await self.app(scope, receive, send)

        lengths = [value for name, value in scope.get("headers", []) if name.lower() == b"content-length"]
        if lengths:
            try:
                if len(lengths) != 1:
                    raise ValueError
                raw = lengths[0].decode("ascii")
                if not raw.isdigit():
                    raise ValueError
                if int(raw) > MAX_COMMERCIAL_ROUTE_BODY_BYTES:
                    return await JSONResponse(status_code=413, content={"detail": "Commercial route request exceeds 16 KiB"})(scope, receive, send)
            except (UnicodeDecodeError, ValueError):
                return await JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})(scope, receive, send)

        total = 0
        buffered = []
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                buffered.append(message)
                break
            total += len(message.get("body", b""))
            if total > MAX_COMMERCIAL_ROUTE_BODY_BYTES:
                return await JSONResponse(status_code=413, content={"detail": "Commercial route request exceeds 16 KiB"})(scope, receive, send)
            buffered.append(message)
            if not message.get("more_body", False):
                break

        index = 0

        async def replay():
            nonlocal index
            if index < len(buffered):
                message = buffered[index]
                index += 1
                return message
            return await receive()

        return await self.app(scope, replay, send)


def install_commercial_router(app) -> None:
    if any(getattr(route, "path", None) == "/commercial/routes/plan" for route in app.router.routes):
        return

    def endpoint(
        payload: CommercialRoutePlanRequest,
        agent=Depends(require_participation_reader),
        db: Session = Depends(get_db),
    ):
        data = plan_commercial_route(db, requester_agent_id=agent.id, payload=payload)
        return JSONResponse(data, headers={"Cache-Control": "private, no-store"})

    app.add_api_route(
        "/commercial/routes/plan",
        endpoint,
        methods=["POST"],
        include_in_schema=True,
        summary="Plan a bounded commercial route without executing or paying",
    )
    app.add_middleware(_CommercialRouteBodyLimit)
