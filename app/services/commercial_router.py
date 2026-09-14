"""Commercial Router V1 launch corrective.

This module preserves the accepted Router implementation in
``commercial_router_legacy`` and narrows only the launch-critical boundaries:
requester privacy, targeted Registry lookup, and trusted MCP Origin handling.
"""
from __future__ import annotations

import os
import re
from typing import Any

from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator
from sqlalchemy.orm import Session

from ..db import get_db
from ..public_origin import PublicOriginError, canonical_public_origin
from ..security import require_participation_reader
from . import commercial_router_legacy as _legacy
from .external_registry import DiscoveryResult, discover_external_agents_with_status
from .external_registry_targeted import discover_external_agent_by_identifier_with_status

# Preserve all existing test/extension seams and public names unless explicitly
# overridden below. This keeps the corrective narrow and source-compatible.
for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

_REJECTED_NEED = "__AION_REJECTED_SENSITIVE_NEED__"
_REJECTED_IDENTIFIER = "__AION_REJECTED_REGISTRY_IDENTIFIER__"
_SENSITIVE_URI = re.compile(r"(?i)(?:\b[a-z][a-z0-9+.-]{1,15}://|\bwww\.)")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|token|password|passwd|secret|credential)\s*[:=]\s*\S+"
)
_BEARER_CREDENTIAL = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}\b")
_TARGET_IDENTIFIER = re.compile(r"^[A-Za-z0-9_@+~-]+(?:\.[A-Za-z0-9_@+~-]+)*$")
_DEFAULT_DISCOVER = discover_external_agents_with_status
_DEFAULT_DISCOVER_BY_IDENTIFIER = discover_external_agent_by_identifier_with_status
_DISCOVER = _DEFAULT_DISCOVER
_DISCOVER_BY_IDENTIFIER = _DEFAULT_DISCOVER_BY_IDENTIFIER

# Keep the launch fail-closed contract visible in the active Router source as
# well as in the preserved implementation it delegates to. These values mirror
# the runtime block returned by ``_legacy._commercial_block``; they are not an
# executable quote or a second economic implementation.
_FAIL_CLOSED_SOURCE_CONTRACT = {
    "provider_price_state": "unknown",
    "provider_maximum_cost": None,
    "commercial_rights_state": "unknown",
    "policy_eligible": False,
    "execution_eligible": False,
}


def _sensitive_need(value: str) -> bool:
    return bool(
        any(ord(character) < 32 or ord(character) == 127 for character in value)
        or _SENSITIVE_URI.search(value)
        or _SECRET_ASSIGNMENT.search(value)
        or _BEARER_CREDENTIAL.search(value)
        or _legacy._LONG_REMOTE_TOKEN.search(value)
    )


def _target_identifier_valid(value: str) -> bool:
    return bool(
        value
        and len(value) <= 240
        and _TARGET_IDENTIFIER.fullmatch(value)
        and ".." not in value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


class CommercialRoutePlanRequest(_legacy.CommercialRoutePlanRequest):
    need: str = Field(
        min_length=1,
        max_length=128,
        description=(
            "Public routing need. When candidate_identifier is absent, AION may send "
            "this value to the public A2A Registry. Never include secrets, credentials, "
            "private URLs, or token-like material."
        ),
    )
    candidate_identifier: str | None = Field(
        default=None,
        min_length=1,
        max_length=240,
        description=(
            "Optional public A2A Registry package identifier. When supplied, AION uses "
            "targeted Registry lookup and does not send need to the Registry."
        ),
    )

    @field_validator("need", mode="before")
    @classmethod
    def _privacy_gate(cls, value):
        if isinstance(value, str) and _sensitive_need(value):
            # Raising here would make FastAPI/Pydantic include the original input in
            # the default 422. Replace it with an internal sentinel and reject later.
            return _REJECTED_NEED
        return value

    @field_validator("candidate_identifier", mode="before")
    @classmethod
    def _target_identifier_gate(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and not _target_identifier_valid(value.strip()):
            return _REJECTED_IDENTIFIER
        return value


def _reject_private_request(payload: CommercialRoutePlanRequest) -> None:
    if payload.need == _REJECTED_NEED:
        raise HTTPException(
            status_code=422,
            detail=(
                "Commercial route need must not contain URLs, credentials, secrets, "
                "or token-like material"
            ),
        )
    if payload.candidate_identifier == _REJECTED_IDENTIFIER:
        raise HTTPException(
            status_code=422,
            detail="candidate_identifier must be a bounded public Registry identifier",
        )


def _targeted_discovery(identifier: str) -> DiscoveryResult:
    """Use the direct identifier path in production without ever passing ``need``.

    Older Router tests/extensions monkeypatch only ``_DISCOVER``. Preserve that
    seam without weakening the privacy contract: if and only if the generic seam
    was explicitly replaced while the targeted seam remains the production
    default, call the replacement with the public identifier itself, never with
    requester need. Normal runtime always uses the direct Registry detail helper.
    """

    if _DISCOVER_BY_IDENTIFIER is not _DEFAULT_DISCOVER_BY_IDENTIFIER:
        return _DISCOVER_BY_IDENTIFIER(identifier)
    if _DISCOVER is not _DEFAULT_DISCOVER:
        return _DISCOVER(identifier, MAX_ROUTE_CANDIDATES)
    return _DISCOVER_BY_IDENTIFIER(identifier)


def plan_commercial_route(
    db: Session,
    *,
    requester_agent_id: int,
    payload: CommercialRoutePlanRequest,
) -> dict:
    _reject_private_request(payload)

    # Authentication scopes the planning surface but intentionally records no
    # lifecycle/commercial evidence in V1.
    _ = requester_agent_id
    if payload.candidate_identifier is not None:
        discovery: DiscoveryResult = _targeted_discovery(payload.candidate_identifier)
        discovery_mode = "registry_identifier_lookup"
        need_sent_to_registry = False
    else:
        discovery = _DISCOVER(payload.need, MAX_ROUTE_CANDIDATES)
        discovery_mode = "registry_need_search"
        need_sent_to_registry = True

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
        relevant = [
            candidate
            for candidate in candidates
            if candidate.get("identifier") == payload.candidate_identifier
        ]

    eligible = [
        candidate
        for candidate in relevant
        if candidate["qualification_state"] == "declaration_qualified"
    ]
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
    outbound_attempts = int(
        (discovery.resource_bounds or {}).get("outbound_attempts_used") or 0
    )
    next_actions: list[dict[str, Any]] = []
    if selected is not None:
        next_actions.append(
            {
                "action": "verify_external_callability",
                "required_before_current-job_execution": True,
                "endpoint": "/actions/verify-callability",
                "note": (
                    "Historical evidence affects ranking only. Fresh current-job "
                    "verification still requires explicit authorization to contact this "
                    "interaction endpoint."
                ),
            }
        )
    else:
        next_actions.append(
            {
                "action": "refine_need_or_add_supply_adapter",
                "required": True,
                "note": (
                    "No safely qualified provider was selected from the bounded "
                    "discovery result."
                ),
            }
        )
    next_actions.extend(
        [
            {
                "action": "resolve_trusted_provider_pricing_and_commercial_rights",
                "required": True,
                "note": (
                    "An executable quote requires a trusted provider price/max-cost "
                    "source and known commercial rights."
                ),
            },
            {
                "action": "economic_preflight_after_trusted_pricing",
                "required": True,
                "note": (
                    "AION must re-evaluate maximum spend and contribution margin "
                    "before any paid execution."
                ),
            },
            {
                "action": "real_payment_human_gate",
                "required": True,
                "note": (
                    "Real-money activation remains a separate Human Gate even after "
                    "an executable quote exists."
                ),
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
            "mode": discovery_mode,
            "need_sent_to_public_registry": need_sent_to_registry,
            "resource_bounds": dict(discovery.resource_bounds or {}),
            "result_count": len(candidates),
        },
        "candidates": candidates,
        "selected_provider": selected,
        "provider_verification_state": provider_state,
        "commercial": _commercial_block(payload, selected=selected),
        "execution": {
            "mode": "planning_only",
            "external_discovery_performed": outbound_attempts > 0,
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
            "need_sent_to_public_registry": need_sent_to_registry,
        },
    }


class _TrustedMcpOrigin:
    """Reject Host-header origin spoofing before the legacy MCP route check."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("path", "").rstrip("/") != "/mcp":
            return await self.app(scope, receive, send)

        origins = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"origin"
        ]
        if not origins:
            return await self.app(scope, receive, send)
        if len(origins) != 1:
            return await JSONResponse(
                status_code=403,
                content={"detail": "Origin is not allowed"},
            )(scope, receive, send)
        try:
            origin = origins[0].decode("ascii").strip().rstrip("/")
        except UnicodeDecodeError:
            return await JSONResponse(
                status_code=403,
                content={"detail": "Origin is not allowed"},
            )(scope, receive, send)

        configured = {
            item.strip().rstrip("/")
            for item in os.getenv("AION_ALLOWED_ORIGINS", "").split(",")
            if item.strip()
        }
        try:
            configured.add(canonical_public_origin().rstrip("/"))
        except PublicOriginError:
            return await JSONResponse(
                status_code=503,
                content={"detail": "Trusted public origin is unavailable"},
            )(scope, receive, send)
        if origin not in configured:
            return await JSONResponse(
                status_code=403,
                content={"detail": "Origin is not allowed"},
            )(scope, receive, send)
        return await self.app(scope, receive, send)


def install_commercial_router(app) -> None:
    if any(
        getattr(route, "path", None) == "/commercial/routes/plan"
        for route in app.router.routes
    ):
        return

    def endpoint(
        payload: CommercialRoutePlanRequest,
        agent=Depends(require_participation_reader),
        db: Session = Depends(get_db),
    ):
        data = plan_commercial_route(
            db,
            requester_agent_id=agent.id,
            payload=payload,
        )
        return JSONResponse(data, headers={"Cache-Control": "private, no-store"})

    app.add_api_route(
        "/commercial/routes/plan",
        endpoint,
        methods=["POST"],
        include_in_schema=True,
        summary="Plan a bounded commercial route without executing or paying",
        description=(
            "Authenticated planning only. Without candidate_identifier, need may be "
            "sent to the public A2A Registry; never place secrets, credentials, private "
            "URLs, or token-like material in need. With candidate_identifier, AION uses "
            "targeted Registry lookup and does not send need. No provider execution, "
            "payment, reserve, settlement, economic operation, VUO, or adoption proof "
            "is created by route planning."
        ),
    )
    app.add_middleware(_legacy._CommercialRouteBodyLimit)
    app.add_middleware(_TrustedMcpOrigin)
