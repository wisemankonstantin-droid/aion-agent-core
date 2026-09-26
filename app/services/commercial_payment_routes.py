"""Late-installed commercial payment routes.

The production-first path is buyer-broadcast purchase-bound EIP-3009 Base USDC: the buyer broadcasts
and pays gas, then AION verifies the on-chain Transfer before releasing the
prepared result. x402 exact/upfront remains available as optional compatibility.
"""
from __future__ import annotations

import base64
import json
import sys

from fastapi import Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..db import get_db
from ..public_origin import canonical_public_origin
from .direct_base_usdc import DIRECT_PAYMENT_METHOD, direct_base_usdc_readiness
from .paid_route_intelligence import (
    ROUTE_INTELLIGENCE_SKU,
    configured_route_intelligence_plan,
    register_paid_route_intelligence_profile,
)
from .route_intelligence_purchase import (
    X402_PAYMENT_METHOD,
    RouteIntelligencePurchaseError,
    payment_required_response_data,
    prepare_route_intelligence,
    settle_and_release,
    settle_direct_and_release,
)
from .x402_exact_upfront import (
    build_exact_payment_required,
    encode_exact_payment_required,
    exact_upfront_readiness,
)
from .x402_payment_offer import payment_offer_readiness


MAX_COMMERCIAL_PURCHASE_BODY_BYTES = 16 * 1024


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


def _install_agentcash_openapi_metadata(app) -> None:
    """Expose the paid Route Intelligence contract in AgentCash-compatible OpenAPI.

    Discovery metadata must stay truthful to the live payment surface. This
    function does not activate payment, change price, create a purchase, or
    silently treat USDC as fiat USD.
    """

    if getattr(app.state, "aion_agentcash_openapi_metadata_installed", False):
        return

    original_openapi = app.openapi

    def aion_openapi():
        schema = original_openapi()
        info = schema.setdefault("info", {})
        info["x-guidance"] = (
            "Before external spend, use POST /commercial/route-intelligence/preflight "
            "for a zero-price GO/HOLD/STOP decision. When a qualified route exists, "
            "POST the same bounded need to /commercial/route-intelligence/x402/purchase "
            "and follow the returned x402 exact/upfront payment challenge."
        )

        operation = (
            schema.setdefault("paths", {})
            .setdefault("/commercial/route-intelligence/x402/purchase", {})
            .setdefault("post", {})
        )
        operation["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {
                    "schema": _x402_input_schema(),
                }
            },
        }
        operation.setdefault("responses", {}).setdefault(
            "402", {"description": "Payment Required"}
        )

        plan = configured_route_intelligence_plan()
        readiness = exact_upfront_readiness()
        if plan is not None and readiness["launch_ready"]:
            operation["x-payment-info"] = {
                "price": {
                    "mode": "fixed",
                    "currency": plan.currency,
                    "amount": plan.customer_price,
                },
                "protocols": [{"x402": {}}],
            }
        else:
            operation.pop("x-payment-info", None)
        return schema

    app.openapi = aion_openapi
    app.openapi_schema = None
    app.state.aion_agentcash_openapi_metadata_installed = True


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
            return JSONResponse(
                {
                    "version": 1,
                    "x402Version": 2,
                    "name": "AION SUPREME",
                    "description": (
                        "Before external spend, ask AION to choose and verify a qualified paid "
                        "provider route from a bounded need."
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

    _install_agentcash_openapi_metadata(app)
