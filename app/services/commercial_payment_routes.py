"""Late-installed commercial payment routes.

The production-first path is buyer-funded direct Base USDC: the buyer broadcasts
and pays gas, then AION verifies the on-chain Transfer before releasing the
prepared result. x402 exact/upfront remains available as optional compatibility.
"""
from __future__ import annotations

import base64
import json
import sys

from fastapi import Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from .direct_base_usdc import direct_base_usdc_readiness
from .paid_route_intelligence import (
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
)
from .route_intelligence_purchase import (
    RouteIntelligencePurchaseError,
    payment_required_response_data,
    prepare_route_intelligence,
    settle_and_release,
    settle_direct_and_release,
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
    }
    accounting = data.get("accounting") or {}
    if accounting.get("settled_atomic_amount_source") in {
        "facilitator_reported",
        "onchain_base_usdc_transfer_event",
    }:
        response["amount"] = accounting["settled_atomic_amount"]
    raw = json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


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
                    "preferred_launch_path": "direct_base_usdc_buyer_pays_gas",
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
                "buyer-funded direct Base USDC; x402 remains optional compatibility."
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
                            "payment_method": "direct_base_usdc_transfer",
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
                        "preferred_launch_path": "direct_base_usdc_buyer_pays_gas",
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
                "No AION membership is required. Preferred launch flow is a buyer-funded "
                "native USDC transfer on Base: the buyer pays gas, submits purchase ID and "
                "transaction hash, and AION releases the frozen result only after read-only "
                "on-chain verification. Legacy x402 exact/upfront remains compatible."
            ),
        )
        app.add_middleware(_CommercialPurchaseBodyLimit)