"""Late-installed commercial payment routes.

The production-first path is buyer-broadcast purchase-bound EIP-3009 Base USDC: the buyer broadcasts
and pays gas, then AION verifies the on-chain Transfer before releasing the
prepared result. x402 exact/upfront remains available as optional compatibility.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys
import urllib.parse

from fastapi import Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db import get_db
from ..public_origin import canonical_public_origin
from .cdp_x402_facilitator import FacilitatorSettlementError, settle_exact_upfront
from .direct_base_usdc import DIRECT_PAYMENT_METHOD, direct_base_usdc_readiness
from .paid_route_intelligence import (
    ROUTE_INTELLIGENCE_SKU,
    configured_route_intelligence_plan,
    register_paid_route_intelligence_profile,
)
from .route_intelligence_purchase import (
    X402_PAYMENT_METHOD,
    RouteIntelligencePurchaseError,
    _decode_payment_envelope,
    _validate_payment_payload,
    payment_required_response_data,
    prepare_route_intelligence,
    settle_and_release,
    settle_direct_and_release,
)
from .safe_http import FetchPolicy, fetch_bytes, fetch_json
from .x402_exact_upfront import (
    ExactUpfrontError,
    build_exact_payment_required,
    encode_exact_payment_required,
    exact_payment_requirements,
    exact_upfront_readiness,
)
from .x402_payment_offer import payment_offer_readiness


MAX_COMMERCIAL_PURCHASE_BODY_BYTES = 16 * 1024
AGENT_READINESS_AUDIT_PATH = "/commercial/agent-readiness-audit"
AGENT_READINESS_AUDIT_SKU = "aion.agent_readiness_audit.v1"
_AUDIT_POLICY = FetchPolicy(
    timeout_seconds=4.0,
    max_response_bytes=96_000,
    max_attempts=1,
    max_resolved_addresses=4,
    user_agent="AION-Agent-Readiness-Audit/0.8.0",
)



class _CommercialPurchaseBodyLimit:
    """Bound only the anonymous paid-purchase request without buffering unbounded data."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope.get("type") != "http"
            or scope.get("method") != "POST"
            or scope.get("path", "").rstrip("/")
            not in {
                "/commercial/route-intelligence/purchase",
                "/commercial/route-intelligence/x402/purchase",
            }
        ):
            return await self.app(scope, receive, send)

        values = [
            value
            for name, value in scope.get("headers", [])
            if name.lower() == b"content-length"
        ]
        if values:
            try:
                if len(values) != 1:
                    raise ValueError
                raw = values[0].decode("ascii")
                if not raw.isdigit():
                    raise ValueError
                if int(raw) > MAX_COMMERCIAL_PURCHASE_BODY_BYTES:
                    return await JSONResponse(
                        status_code=413,
                        content={"detail": "Commercial purchase request body exceeds 16 KiB"},
                    )(scope, receive, send)
            except (UnicodeDecodeError, ValueError):
                return await JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"},
                )(scope, receive, send)

        buffered = []
        size = 0
        while True:
            message = await receive()
            if message.get("type") != "http.request":
                buffered.append(message)
                break
            size += len(message.get("body", b""))
            if size > MAX_COMMERCIAL_PURCHASE_BODY_BYTES:
                return await JSONResponse(
                    status_code=413,
                    content={"detail": "Commercial purchase request body exceeds 16 KiB"},
                )(scope, receive, send)
            buffered.append(message)
            if not message.get("more_body", False):
                break

        index = 0

        async def replay():
            nonlocal index
            if index < len(buffered):
                item = buffered[index]
                index += 1
                return item
            return await receive()

        return await self.app(scope, replay, send)


def _patch_mcp_paid_sku_metadata() -> None:
    main_module = sys.modules.get("app.main")
    if main_module is None:
        return
    tools = getattr(main_module, "MCP_TOOLS", None)
    if not isinstance(tools, list):
        return
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("name") != "economic_preflight":
            continue
        properties = ((tool.get("inputSchema") or {}).get("properties") or {})
        sku = properties.get("product_sku")
        if not isinstance(sku, dict):
            return
        values = sku.get("enum")
        if not isinstance(values, list):
            return
        if ROUTE_INTELLIGENCE_SKU not in values:
            values.append(ROUTE_INTELLIGENCE_SKU)
        tool["description"] = (
            "Authenticated Package 6A quote/economic-policy preflight from trusted "
            "internal product profiles, including AION-owned Verified Route "
            "Intelligence when explicitly configured. Requester budget is a "
            "preference, not funds. Real payment remains separately gated."
        )
        return


def _x402_resource_url() -> str:
    return (
        canonical_public_origin().rstrip("/")
        + "/commercial/route-intelligence/x402/purchase"
    )


def _x402_input_schema() -> dict:
    return {
        "type": "object",
        "required": ["need"],
        "properties": {
            "need": {"type": "string", "minLength": 1, "maxLength": 128},
            "candidate_identifier": {
                "type": ["string", "null"],
                "minLength": 1,
                "maxLength": 240,
            },
        },
        "additionalProperties": False,
    }



def _agent_readiness_resource_url() -> str:
    return canonical_public_origin().rstrip("/") + AGENT_READINESS_AUDIT_PATH


def _normalize_audit_origin(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or len(raw) > 512:
        raise ValueError("url must be a bounded public HTTPS URL or hostname")
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urllib.parse.urlparse(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("url must be public HTTPS")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("url has invalid port") from exc
    host = parsed.hostname.rstrip(".").lower()
    if not host or len(host) > 253:
        raise ValueError("url hostname is invalid")
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("url port is invalid")
    return "https://" + host + (f":{port}" if port and port != 443 else "")


def _json_surface(origin: str, path: str) -> tuple[dict, object | None]:
    result, data = fetch_json(
        "GET",
        origin + path,
        policy=_AUDIT_POLICY,
    )
    return {
        "status": result.status,
        "reachable": result.status is not None,
        "ok": bool(result.status == 200 and isinstance(data, dict)),
        "error": result.error,
    }, data


def _text_surface(origin: str, path: str) -> dict:
    result = fetch_bytes(
        "GET",
        origin + path,
        headers={"Accept": "text/plain, text/markdown;q=0.9, */*;q=0.1"},
        policy=_AUDIT_POLICY,
    )
    return {
        "status": result.status,
        "reachable": result.status is not None,
        "ok": bool(result.status == 200 and result.body),
        "error": result.error,
        "bytes": len(result.body or b""),
    }


def _agent_readiness_audit(origin: str) -> dict:
    x402, x402_data = _json_surface(origin, "/.well-known/x402")
    openapi, openapi_data = _json_surface(origin, "/openapi.json")
    agent_card, card_data = _json_surface(origin, "/.well-known/agent-card.json")
    llms = _text_surface(origin, "/llms.txt")

    x402_resources = (
        x402_data.get("resources")
        if isinstance(x402_data, dict)
        else None
    )
    x402["resource_count"] = len(x402_resources) if isinstance(x402_resources, list) else 0
    x402["ok"] = bool(x402["ok"] and x402["resource_count"] > 0)

    base_domain_ok = None
    if isinstance(x402_resources, list):
        for resource in x402_resources[:20]:
            accepts = resource.get("accepts") if isinstance(resource, dict) else None
            if not isinstance(accepts, list):
                continue
            for accept in accepts[:10]:
                if not isinstance(accept, dict) or accept.get("network") != "eip155:8453":
                    continue
                extra = accept.get("extra") if isinstance(accept.get("extra"), dict) else {}
                base_domain_ok = bool(
                    extra.get("name") == "USD Coin"
                    and str(extra.get("version")) == "2"
                )
                break
            if base_domain_ok is not None:
                break
    x402["base_usdc_eip712_domain_ok"] = base_domain_ok

    openapi_paths = (
        openapi_data.get("paths")
        if isinstance(openapi_data, dict)
        and isinstance(openapi_data.get("paths"), dict)
        else {}
    )
    openapi["path_count"] = len(openapi_paths)
    openapi["mcp_declared"] = any(
        str(path).rstrip("/") == "/mcp" for path in openapi_paths
    )

    skills = (
        card_data.get("skills")
        if isinstance(card_data, dict)
        else None
    )
    agent_card["skill_count"] = len(skills) if isinstance(skills, list) else 0

    weighted = (
        (30 if x402["ok"] else 0)
        + (25 if openapi["ok"] else 0)
        + (25 if agent_card["ok"] else 0)
        + (20 if llms["ok"] else 0)
    )
    if weighted >= 90:
        verdict = "ready"
    elif weighted >= 70:
        verdict = "mostly_ready"
    elif weighted >= 40:
        verdict = "partial"
    else:
        verdict = "weak"

    fixes = []
    if not x402["ok"]:
        fixes.append("publish a live /.well-known/x402 manifest with at least one priced resource")
    elif base_domain_ok is False:
        fixes.append('for Base USDC advertise EIP-712 extra.name="USD Coin" and version="2"')
    if not openapi["ok"]:
        fixes.append("publish machine-readable /openapi.json")
    if not agent_card["ok"]:
        fixes.append("publish /.well-known/agent-card.json with bounded skills")
    if not llms["ok"]:
        fixes.append("publish /llms.txt for machine discovery")

    return {
        "product_sku": AGENT_READINESS_AUDIT_SKU,
        "origin": origin,
        "score": weighted,
        "verdict": verdict,
        "checks": {
            "x402": x402,
            "openapi": openapi,
            "agent_card": agent_card,
            "llms_txt": llms,
        },
        "prioritized_fixes": fixes,
        "truth_boundaries": {
            "public_surfaces_only": True,
            "no_private_auth_attempted": True,
            "no_provider_payment_attempted": True,
            "no_claim_that_surface_presence_proves_sales": True,
        },
    }


def _agent_readiness_payment_required(requirements: dict) -> dict:
    return {
        "x402Version": 2,
        "error": "PAYMENT-SIGNATURE header is required",
        "resource": {
            "url": _agent_readiness_resource_url(),
            "description": (
                "Audit an AI agent/API before spending: x402, OpenAPI, agent card, "
                "llms.txt and MCP declaration readiness with a structured score and fixes."
            ),
            "mimeType": "application/json",
            "serviceName": "AION Agent Readiness Audit",
            "tags": [
                "agent-readiness",
                "x402",
                "verification",
                "pre-spend",
                "openapi",
            ],
        },
        "accepts": [requirements],
    }


def _agent_readiness_manifest_resource(plan) -> dict:
    return {
        "name": "Audit an AI agent or paid API before spending",
        "resource": _agent_readiness_resource_url(),
        "method": "GET",
        "description": (
            "Give AION a public HTTPS URL or hostname. After x402 settlement, "
            "receive a deterministic readiness score, surface evidence and prioritized fixes "
            "for x402, OpenAPI, agent-card, llms.txt and MCP declaration."
        ),
        "price": f"{plan.customer_price} {plan.currency}",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                    "description": "Public HTTPS URL or hostname to audit",
                }
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        "accepts": [exact_payment_requirements()],
    }


def _audit_payment_response_header(settlement: dict, requirements: dict) -> str:
    response = {
        "success": True,
        "transaction": settlement["transaction"],
        "network": settlement["network"],
        "payer": settlement["payer"],
        "amount": str(requirements["amount"]),
    }
    raw = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _install_agent_readiness_audit(app) -> None:
    if any(
        getattr(route, "path", None) == AGENT_READINESS_AUDIT_PATH
        for route in app.router.routes
    ):
        return

    def endpoint(
        url: str,
        payment_signature: str | None = Header(
            default=None,
            alias="PAYMENT-SIGNATURE",
        ),
    ):
        try:
            origin = _normalize_audit_origin(url)
        except ValueError as exc:
            return JSONResponse(
                status_code=422,
                content={
                    "code": "invalid_audit_target",
                    "message": str(exc),
                    "product_sku": AGENT_READINESS_AUDIT_SKU,
                },
                headers={"Cache-Control": "private, no-store"},
            )

        readiness = exact_upfront_readiness()
        if not readiness["launch_ready"]:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "x402_exact_upfront_not_activated",
                    "product_sku": AGENT_READINESS_AUDIT_SKU,
                    "blocking_reasons": readiness["blocking_reasons"],
                },
                headers={"Cache-Control": "private, no-store"},
            )

        try:
            requirements = exact_payment_requirements()
        except ExactUpfrontError as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "code": exc.code,
                    "message": exc.message,
                    "product_sku": AGENT_READINESS_AUDIT_SKU,
                },
                headers={"Cache-Control": "private, no-store"},
            )

        if payment_signature is None:
            required = _agent_readiness_payment_required(requirements)
            return JSONResponse(
                status_code=402,
                content=required,
                headers={
                    "PAYMENT-REQUIRED": encode_exact_payment_required(required),
                    "Cache-Control": "private, no-store",
                },
            )

        try:
            payment_payload = _decode_payment_envelope(payment_signature)
            _validate_payment_payload(payment_payload, requirements)
            settlement = settle_exact_upfront(payment_payload, requirements)
        except RouteIntelligencePurchaseError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "code": exc.code,
                    "message": exc.message,
                    "product_sku": AGENT_READINESS_AUDIT_SKU,
                    "result_released": False,
                },
                headers={"Cache-Control": "private, no-store"},
            )
        except FacilitatorSettlementError as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "code": exc.code,
                    "message": exc.message,
                    "product_sku": AGENT_READINESS_AUDIT_SKU,
                    "result_released": False,
                },
                headers={"Cache-Control": "private, no-store"},
            )

        outcome = settlement.get("outcome")
        if outcome != "settled":
            status = 402 if outcome == "rejected" else 202 if outcome == "pending" else 503
            return JSONResponse(
                status_code=status,
                content={
                    "code": "payment_" + str(outcome or "unknown"),
                    "detail": settlement.get("code") or settlement.get("detail"),
                    "product_sku": AGENT_READINESS_AUDIT_SKU,
                    "result_released": False,
                },
                headers={"Cache-Control": "private, no-store"},
            )

        report = _agent_readiness_audit(origin)
        evidence = {
            "event": "stateless_agent_readiness_audit_settled",
            "product_sku": AGENT_READINESS_AUDIT_SKU,
            "transaction": settlement["transaction"],
            "payer": settlement["payer"],
            "network": settlement["network"],
            "atomic_amount": str(requirements["amount"]),
            "target_digest": hashlib.sha256(origin.encode("utf-8")).hexdigest(),
            "score": report["score"],
        }
        print(
            "AION_STATELESS_AUDIT_SETTLED "
            + json.dumps(evidence, sort_keys=True, separators=(",", ":")),
            flush=True,
        )
        plan = configured_route_intelligence_plan()
        return JSONResponse(
            status_code=200,
            content={
                "state": "delivered",
                "product_sku": AGENT_READINESS_AUDIT_SKU,
                "result": report,
                "payment": {
                    "method": "x402_exact_upfront",
                    "scheme": "exact",
                    "payment_flow": "upfront",
                    "transaction": settlement["transaction"],
                    "network": settlement["network"],
                    "payer": settlement["payer"],
                    "amount": plan.customer_price if plan is not None else None,
                    "currency": plan.currency if plan is not None else None,
                    "atomic_amount": str(requirements["amount"]),
                },
                "aion_membership_created": False,
                "database_required": False,
            },
            headers={
                "PAYMENT-RESPONSE": _audit_payment_response_header(
                    settlement, requirements
                ),
                "Cache-Control": "private, no-store",
            },
        )

    app.add_api_route(
        AGENT_READINESS_AUDIT_PATH,
        endpoint,
        methods=["GET"],
        include_in_schema=True,
        summary="Audit an AI agent or paid API before spending",
        description=(
            "Stateless paid x402 audit. Give a public HTTPS URL or hostname and receive "
            "a structured readiness score for x402, OpenAPI, agent card, llms.txt and "
            "MCP declaration. No AION membership or database state is required."
        ),
        responses={
            402: {"description": "x402 exact/upfront payment required"},
        },
    )


def _payment_response_header(data: dict) -> str:
    payment = data["payment"]
    response = {
        "success": True,
        "transaction": payment["transaction"],
        "network": payment["network"],
        "payer": payment["payer"],
    }
    accounting = data.get("accounting") or {}
    if accounting.get("settled_atomic_amount_source") in {
        "facilitator_reported",
        "onchain_base_usdc_eip3009_transfer",
    }:
        response["amount"] = accounting["settled_atomic_amount"]
    raw = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")



class PreSpendPreflightError(ValueError):
    """Bounded public pre-spend request validation error."""


def pre_spend_preflight_data(db: Session, payload: dict) -> dict:
    """Return the canonical zero-price GO/HOLD/STOP pre-spend decision.

    This helper is transport-neutral so REST, MCP and A2A can expose the same
    bounded decision contract without duplicating commercial or payment logic.
    It creates no purchase, payment, entitlement or provider interaction.
    """
    allowed = {"need", "candidate_identifier"}
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise PreSpendPreflightError(
            "Preflight accepts only need and optional candidate_identifier"
        )
    try:
        from .commercial_router import CommercialRoutePlanRequest, plan_commercial_route

        request = CommercialRoutePlanRequest.model_validate(
            {
                "need": payload.get("need"),
                "candidate_identifier": payload.get("candidate_identifier"),
                "currency": "USD",
            }
        )
        plan = plan_commercial_route(
            db,
            requester_agent_id=0,
            payload=request,
        )
    except (ValidationError, HTTPException) as exc:
        raise PreSpendPreflightError(
            "Preflight request failed bounded validation"
        ) from exc

    selected = plan.get("selected_provider") is not None
    state = str(plan.get("state") or "unknown")
    qualified_count = sum(
        1
        for candidate in plan.get("candidates") or []
        if candidate.get("qualification_state") == "declaration_qualified"
    )
    payment = direct_base_usdc_readiness()

    if state == "discovery_unavailable":
        decision = "HOLD"
    elif selected and payment["launch_ready"]:
        decision = "GO"
    elif selected:
        decision = "HOLD"
    else:
        decision = "STOP"

    next_action = {
        "action": (
            "purchase_route_intelligence"
            if decision == "GO"
            else "retry_or_refine_need"
            if decision == "HOLD"
            else "change_need_or_candidate"
        ),
        "method": "POST" if decision == "GO" else None,
        "url": (
            "/commercial/route-intelligence/purchase"
            if decision == "GO"
            else None
        ),
        "same_request_body": decision == "GO",
    }
    return {
        "action": "aion_pre_spend_preflight",
        "decision": decision,
        "reason_code": state,
        "qualified_route_available": selected,
        "qualified_candidate_count": qualified_count,
        "route_details_released": False,
        "route_details_available_after_purchase": bool(selected),
        "membership_required": False,
        "payment_required": False,
        "paid_route_launch_ready": bool(payment["launch_ready"]),
        "next_action": next_action,
        "buyer_guide": (
            "https://github.com/wisemankonstantin-droid/"
            "aion-agent-core/blob/main/docs/FIRST_SAT_BUYER.md"
        ),
        "truth_boundaries": {
            "preflight_is_not_purchase": True,
            "preflight_creates_no_payment_or_entitlement": True,
            "provider_interaction_endpoint_contacted": False,
            "payment_rail_contacted": False,
            "public_registry_or_manifest_discovery_may_occur": True,
            "selected_provider_identity_withheld_until_paid_route_intelligence": True,
        },
    }

def install_commercial_payment_routes(app) -> None:
    register_paid_route_intelligence_profile()
    _install_agent_readiness_audit(app)
    _patch_mcp_paid_sku_metadata()

    existing = {getattr(route, "path", None) for route in app.router.routes}

    if "/commercial/route-intelligence/payment-readiness" not in existing:
        def readiness_endpoint():
            primary = direct_base_usdc_readiness()
            return JSONResponse(
                {
                    **primary,
                    "preferred_launch_path": "direct_base_usdc_eip3009_buyer_broadcast",
                    "legacy_x402_exact_upfront_compatibility": exact_upfront_readiness(),
                    "future_auth_capture_compatibility": payment_offer_readiness(),
                },
                headers={"Cache-Control": "public, max-age=60"},
            )

        app.add_api_route(
            "/commercial/route-intelligence/payment-readiness",
            readiness_endpoint,
            methods=["GET"],
            include_in_schema=True,
            summary="Read Route Intelligence payment readiness",
            description=(
                "Read-only truth surface. It creates no payment, entitlement, revenue, "
                "VUO, membership or adoption evidence. Production-first semantics are "
                "buyer-broadcast purchase-bound EIP-3009 Base USDC; x402 remains optional compatibility."
            ),
        )

    if "/.well-known/x402" not in existing:
        def x402_manifest_endpoint():
            readiness = exact_upfront_readiness()
            plan = configured_route_intelligence_plan()
            resources = []
            if readiness["launch_ready"] and plan is not None:
                resources.append(
                    {
                        "name": "Choose and verify a paid provider before external spend",
                        "resource": _x402_resource_url(),
                        "method": "POST",
                        "description": (
                            "Use before an agent pays for an external API or agent service. "
                            "Give AION a bounded need; AION selects and verifies a qualified "
                            "provider route, freezes the result, and releases it only after "
                            "x402 exact/upfront settlement."
                        ),
                        "price": f"{plan.customer_price} {plan.currency}",
                        "inputSchema": _x402_input_schema(),
                        "accepts": build_exact_payment_required(
                            resource_url=_x402_resource_url()
                        )["accepts"],
                    }
                )
                resources.append(_agent_readiness_manifest_resource(plan))
            return JSONResponse(
                {
                    "version": 1,
                    "x402Version": 2,
                    "name": "AION SUPREME",
                    "description": (
                        "Machine-first pre-spend verification: choose/verify a provider or audit "
                        "an agent/API's machine readiness before paying."
                    ),
                    "resources": resources,
                },
                headers={"Cache-Control": "public, max-age=60"},
            )

        for manifest_path in (
            "/.well-known/x402",
            "/.well-known/x402.json",
            "/.well-known/x402-services.json",
        ):
            app.add_api_route(
                manifest_path,
                x402_manifest_endpoint,
                methods=["GET"],
                include_in_schema=False,
            )

    if "/commercial/route-intelligence/preflight" not in existing:
        def preflight_endpoint(
            payload: dict,
            db: Session = Depends(get_db),
        ):
            try:
                data = pre_spend_preflight_data(db, payload)
            except PreSpendPreflightError as exc:
                return JSONResponse(
                    status_code=422,
                    content={
                        "code": "invalid_pre_spend_preflight",
                        "message": str(exc),
                        "membership_required": False,
                        "payment_required": False,
                    },
                    headers={"Cache-Control": "private, no-store"},
                )
            return JSONResponse(
                data,
                headers={"Cache-Control": "private, no-store"},
            )

        app.add_api_route(
            "/commercial/route-intelligence/preflight",
            preflight_endpoint,
            methods=["POST"],
            include_in_schema=True,
            summary="Check whether AION has a qualified route before external spend",
            description=(
                "Zero-price, no-membership pre-spend decision surface. It may perform bounded "
                "public registry/manifest discovery, but never contacts a provider interaction "
                "endpoint, creates a payment, or releases the selected paid route."
            ),
        )

    if "/commercial/route-intelligence/x402/purchase" not in existing:
        def x402_purchase_endpoint(
            payload: dict,
            payment_signature: str | None = Header(
                default=None,
                alias="PAYMENT-SIGNATURE",
            ),
            db: Session = Depends(get_db),
        ):
            readiness = exact_upfront_readiness()
            if not readiness["launch_ready"]:
                return JSONResponse(
                    status_code=503,
                    content={
                        "code": "x402_exact_upfront_not_activated",
                        "product_sku": ROUTE_INTELLIGENCE_SKU,
                        "blocking_reasons": readiness["blocking_reasons"],
                        "aion_membership_required": False,
                        "result_released": False,
                    },
                    headers={"Cache-Control": "private, no-store"},
                )

            # External x402 indexers commonly probe a declared POST resource with
            # an empty JSON object to learn its live quote. A valid buyer request
            # still needs a bounded need so AION can freeze a real result and
            # bind payment to that purchase. For the empty, unsigned discovery
            # probe only, expose the configured standard quote without creating
            # a purchase row or contacting the commercial router.
            if payment_signature is None and payload == {}:
                payment_required = build_exact_payment_required(
                    resource_url=_x402_resource_url()
                )
                payment_required["error"] = (
                    "Valid Route Intelligence request body is required before "
                    "purchase-bound payment; this challenge is discovery-only"
                )
                return JSONResponse(
                    status_code=402,
                    content=payment_required,
                    headers={
                        "PAYMENT-REQUIRED": encode_exact_payment_required(
                            payment_required
                        ),
                        "Cache-Control": "private, no-store",
                    },
                )

            try:
                if payment_signature is not None:
                    data = settle_and_release(db, payload, payment_signature)
                    return JSONResponse(
                        status_code=200,
                        content=data,
                        headers={
                            "PAYMENT-RESPONSE": _payment_response_header(data),
                            "Cache-Control": "private, no-store",
                        },
                    )

                row = prepare_route_intelligence(
                    db,
                    payload,
                    payment_method=X402_PAYMENT_METHOD,
                )
                info = payment_required_response_data(
                    row,
                    x402_resource_url=_x402_resource_url(),
                )
                payment_required = info.pop("payment_required")
                return JSONResponse(
                    status_code=402,
                    content=payment_required,
                    headers={
                        "PAYMENT-REQUIRED": encode_exact_payment_required(
                            payment_required
                        ),
                        "Cache-Control": "private, no-store",
                    },
                )
            except RouteIntelligencePurchaseError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "code": exc.code,
                        "message": exc.message,
                        "product_sku": ROUTE_INTELLIGENCE_SKU,
                        "aion_membership_required": False,
                        "result_released": False,
                    },
                    headers={"Cache-Control": "private, no-store"},
                )

        app.add_api_route(
            "/commercial/route-intelligence/x402/purchase",
            x402_purchase_endpoint,
            methods=["POST"],
            include_in_schema=True,
            summary="Choose and verify a paid provider before external spend",
            description=(
                "Use when an agent needs to decide which paid external API or agent service "
                "to call. Submit a bounded need; AION prepares a qualified provider route "
                "and verification evidence, returns x402 payment terms, and releases the "
                "frozen result only after exact/upfront settlement. No AION membership is required."
            ),
        )

    if "/commercial/route-intelligence/purchase" not in existing:
        def purchase_endpoint(
            payload: dict,
            payment_signature: str | None = Header(default=None, alias="PAYMENT-SIGNATURE"),
            direct_purchase_id: str | None = Header(default=None, alias="X-AION-PURCHASE-ID"),
            direct_transaction: str | None = Header(default=None, alias="X-AION-PAYMENT-TX"),
            db: Session = Depends(get_db),
        ):
            direct_readiness = direct_base_usdc_readiness()
            x402_readiness = exact_upfront_readiness()
            try:
                direct_proof_present = bool(direct_purchase_id or direct_transaction)
                if direct_proof_present:
                    if not direct_purchase_id or not direct_transaction:
                        raise RouteIntelligencePurchaseError(
                            400,
                            "direct_payment_proof_incomplete",
                            "Both X-AION-PURCHASE-ID and X-AION-PAYMENT-TX are required",
                        )
                    if not direct_readiness["launch_ready"]:
                        return JSONResponse(
                            status_code=503,
                            content={
                                "code": "direct_base_usdc_not_activated",
                                "product_sku": ROUTE_INTELLIGENCE_SKU,
                                "payment_offer_configured": direct_readiness[
                                    "payment_offer_configured"
                                ],
                                "real_money_execution_enabled": direct_readiness[
                                    "real_money_execution_enabled"
                                ],
                                "blocking_reasons": direct_readiness["blocking_reasons"],
                                "aion_membership_required": False,
                                "result_released": False,
                            },
                            headers={"Cache-Control": "private, no-store"},
                        )
                    data = settle_direct_and_release(
                        db,
                        payload,
                        purchase_id=direct_purchase_id,
                        transaction_hash=direct_transaction,
                    )
                    return JSONResponse(
                        status_code=200,
                        content=data,
                        headers={
                            "PAYMENT-RESPONSE": _payment_response_header(data),
                            "Cache-Control": "private, no-store",
                        },
                    )

                if payment_signature is not None:
                    if not x402_readiness["launch_ready"]:
                        return JSONResponse(
                            status_code=503,
                            content={
                                "code": "x402_exact_upfront_not_activated",
                                "product_sku": ROUTE_INTELLIGENCE_SKU,
                                "blocking_reasons": x402_readiness["blocking_reasons"],
                                "aion_membership_required": False,
                                "result_released": False,
                            },
                            headers={"Cache-Control": "private, no-store"},
                        )
                    data = settle_and_release(db, payload, payment_signature)
                    return JSONResponse(
                        status_code=200,
                        content=data,
                        headers={
                            "PAYMENT-RESPONSE": _payment_response_header(data),
                            "Cache-Control": "private, no-store",
                        },
                    )

                if direct_readiness["launch_ready"]:
                    row = prepare_route_intelligence(db, payload)
                    info = payment_required_response_data(row)
                    required = info.pop("payment_required")
                    return JSONResponse(
                        status_code=402,
                        content={
                            "code": "payment_required",
                            "payment_method": DIRECT_PAYMENT_METHOD,
                            "payment_flow": "upfront",
                            "buyer_pays_gas": True,
                            "facilitator_required": False,
                            "aion_membership_required": False,
                            "payment_instructions": required,
                            **info,
                        },
                        headers={"Cache-Control": "private, no-store"},
                    )

                if x402_readiness["launch_ready"]:
                    row = prepare_route_intelligence(db, payload)
                    info = payment_required_response_data(row)
                    required = info.pop("payment_required")
                    return JSONResponse(
                        status_code=402,
                        content={
                            "code": "payment_required",
                            "protocol": "x402",
                            "x402_version": 2,
                            "scheme": "exact",
                            "payment_flow": "upfront",
                            "aion_membership_required": False,
                            **info,
                        },
                        headers={
                            "PAYMENT-REQUIRED": encode_exact_payment_required(required),
                            "Cache-Control": "private, no-store",
                        },
                    )

                return JSONResponse(
                    status_code=503,
                    content={
                        "code": "commercial_payment_not_activated",
                        "product_sku": ROUTE_INTELLIGENCE_SKU,
                        "preferred_launch_path": "direct_base_usdc_eip3009_buyer_broadcast",
                        "payment_offer_configured": direct_readiness[
                            "payment_offer_configured"
                        ],
                        "real_money_execution_enabled": direct_readiness[
                            "real_money_execution_enabled"
                        ],
                        "blocking_reasons": direct_readiness["blocking_reasons"],
                        "legacy_x402_blocking_reasons": x402_readiness[
                            "blocking_reasons"
                        ],
                        "aion_membership_required": False,
                    },
                    headers={"Cache-Control": "private, no-store"},
                )
            except RouteIntelligencePurchaseError as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={
                        "code": exc.code,
                        "message": exc.message,
                        "product_sku": ROUTE_INTELLIGENCE_SKU,
                        "aion_membership_required": False,
                        "result_released": False,
                    },
                    headers={"Cache-Control": "private, no-store"},
                )

        app.add_api_route(
            "/commercial/route-intelligence/purchase",
            purchase_endpoint,
            methods=["POST"],
            include_in_schema=True,
            summary="Purchase a prepared AION Route Intelligence result",
            description=(
                "No AION membership is required. Preferred launch flow is buyer-broadcast "
                "purchase-bound EIP-3009 native USDC on Base: the buyer or its selected "
                "broadcaster pays gas, submits purchase ID and transaction hash, and AION "
                "releases the frozen result only after read-only on-chain verification. "
                "Legacy x402 exact/upfront remains compatible."
            ),
        )
        app.add_middleware(_CommercialPurchaseBodyLimit)