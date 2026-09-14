"""Late-installed commercial payment routes.

The production-first path is x402 v2 ``exact`` with ``paymentFlow=upfront``:
AION prepares a bounded result before payment, settlement commits before release,
and the same signed EIP-3009 payment identity cannot fund two results. The older
auth-capture builder remains visible as future compatibility readiness only.
"""
from __future__ import annotations

import base64
import json
import sys

from fastapi import Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from .paid_route_intelligence import (
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
)
from .route_intelligence_purchase import (
    RouteIntelligencePurchaseError,
    payment_required_response_data,
    prepare_route_intelligence,
    settle_and_release,
)
from .x402_exact_upfront import (
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
            != "/commercial/route-intelligence/purchase"
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


def _payment_response_header(data: dict) -> str:
    payment = data["payment"]
    response = {
        "success": True,
        "transaction": payment["transaction"],
        "network": payment["network"],
        "payer": payment["payer"],
        "amount": payment["atomic_amount"],
    }
    raw = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def install_commercial_payment_routes(app) -> None:
    register_paid_route_intelligence_profile()
    _patch_mcp_paid_sku_metadata()

    existing = {getattr(route, "path", None) for route in app.router.routes}

    if "/commercial/route-intelligence/payment-readiness" not in existing:
        def readiness_endpoint():
            primary = exact_upfront_readiness()
            return JSONResponse(
                {
                    **primary,
                    "preferred_launch_path": "exact_upfront",
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
                "x402 exact/upfront; auth-capture remains future compatibility."
            ),
        )

    if "/commercial/route-intelligence/purchase" not in existing:
        def purchase_endpoint(
            payload: dict,
            payment_signature: str | None = Header(default=None, alias="PAYMENT-SIGNATURE"),
            db: Session = Depends(get_db),
        ):
            readiness = exact_upfront_readiness()
            try:
                if payment_signature is None:
                    if not readiness["launch_ready"]:
                        return JSONResponse(
                            status_code=503,
                            content={
                                "code": "x402_exact_upfront_not_activated",
                                "product_sku": ROUTE_INTELLIGENCE_SKU,
                                "quote_configured": readiness["quote_configured"],
                                "payment_offer_configured": readiness["payment_offer_configured"],
                                "facilitator_credentials_configured": readiness[
                                    "facilitator_credentials_configured"
                                ],
                                "live_payment_handler_implemented": readiness[
                                    "live_payment_handler_implemented"
                                ],
                                "real_money_execution_enabled": readiness[
                                    "real_money_execution_enabled"
                                ],
                                "aion_membership_required": False,
                            },
                            headers={"Cache-Control": "private, no-store"},
                        )
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

                data = settle_and_release(db, payload, payment_signature)
                return JSONResponse(
                    status_code=200,
                    content=data,
                    headers={
                        "PAYMENT-RESPONSE": _payment_response_header(data),
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
            "/commercial/route-intelligence/purchase",
            purchase_endpoint,
            methods=["POST"],
            include_in_schema=True,
            summary="Purchase a prepared AION Route Intelligence result through x402",
            description=(
                "No AION membership is required. AION first prepares a bounded route "
                "snapshot without revealing it, then exact/upfront x402 settlement must "
                "succeed before that frozen result is released. PAYMENT-SIGNATURE is "
                "never stored raw; duplicate payment identities cannot fund two results."
            ),
        )
        app.add_middleware(_CommercialPurchaseBodyLimit)
