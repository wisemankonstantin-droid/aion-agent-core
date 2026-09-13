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
from typing import Any

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


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _eligible(candidate: dict) -> bool:
    return bool(
        candidate.get("manifest_reachable")
        and candidate.get("card_parseable")
        and candidate.get("declared_a2a_v1_jsonrpc")
        and candidate.get("interaction_url_validated")
        and candidate.get("authentication_requirement") == "none"
        and candidate.get("interaction_url")
    )


def _provider_history(db: Session, identifiers: list[str]) -> dict[str, dict]:
    history = {
        identifier: {
            "recorded_outcomes": 0,
            "verified_callability_outcomes": 0,
            "failed_outcomes": 0,
            "failure_classes": {},
            "last_verified_at": None,
        }
        for identifier in identifiers
    }
    if not identifiers:
        return history

    rows = db.execute(
        select(models.ActionRun, models.ActionOutcome)
        .join(models.ActionOutcome, models.ActionOutcome.action_run_id == models.ActionRun.id)
        .where(models.ActionRun.selected_provider_identifier.in_(identifiers))
    ).all()
    counters = {identifier: Counter() for identifier in identifiers}
    for run, outcome in rows:
        identifier = str(run.selected_provider_identifier or "")
        if identifier not in history:
            continue
        item = history[identifier]
        item["recorded_outcomes"] += 1
        if outcome.callability_verified and outcome.verified_outcome:
            item["verified_callability_outcomes"] += 1
            completed_at = _aware(outcome.completed_at)
            current = item["last_verified_at"]
            if completed_at is not None and (current is None or completed_at > current):
                item["last_verified_at"] = completed_at
        if outcome.failure_class:
            item["failed_outcomes"] += 1
            counters[identifier][str(outcome.failure_class)[:64]] += 1

    for identifier, item in history.items():
        item["failure_classes"] = dict(sorted(counters[identifier].items()))
        if item["last_verified_at"] is not None:
            item["last_verified_at"] = item["last_verified_at"].isoformat()
    return history


def _bounded_candidate(candidate: dict, history: dict) -> dict:
    identifier = str(candidate.get("identifier") or "")[:240]
    verified_count = int(history.get("verified_callability_outcomes") or 0)
    return {
        "source": str(candidate.get("source") or "")[:80] or None,
        "identifier": identifier or None,
        "name": str(candidate.get("name") or "")[:240] or None,
        "description": str(candidate.get("description") or "")[:500],
        "agent_card_url": str(candidate.get("url") or "")[:1000] or None,
        "interaction_url": str(candidate.get("interaction_url") or "")[:1000] or None,
        "protocol_binding": str(candidate.get("protocol_binding") or "")[:40] or None,
        "protocol_version": str(candidate.get("protocol_version") or "")[:40] or None,
        "manifest_reachable": bool(candidate.get("manifest_reachable")),
        "card_parseable": bool(candidate.get("card_parseable")),
        "declared_a2a_v1_jsonrpc": bool(candidate.get("declared_a2a_v1_jsonrpc")),
        "interaction_url_validated": bool(candidate.get("interaction_url_validated")),
        "authentication_requirement": str(candidate.get("authentication_requirement") or "unknown")[:40],
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
    identifiers = [
        str(candidate.get("identifier") or "")[:240]
        for candidate in raw
        if str(candidate.get("identifier") or "")
    ]
    history = _provider_history(db, identifiers)
    candidates = [
        _bounded_candidate(candidate, history.get(str(candidate.get("identifier") or "")[:240], {}))
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
    elif not candidates and discovery.failure_class:
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
                "required_before_current-job_execution": provider_state != "historical_callability_verified",
                "endpoint": "/actions/verify-callability",
                "note": "This existing action requires explicit authorization to contact the provider interaction endpoint.",
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
