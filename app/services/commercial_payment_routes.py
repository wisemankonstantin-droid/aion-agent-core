"""Late-installed buyer payment readiness and x402 402 contract routes.

The current repository contains no live payment handler. These routes therefore
fail closed in normal runtime and never accept PAYMENT-SIGNATURE or claim funds
were authorized/reserved. They expose the exact future x402 v2 wire contract
only when every code-owned and operator-owned activation gate is true.
"""
from __future__ import annotations

import sys

from fastapi import Header
from fastapi.responses import JSONResponse

from .paid_route_intelligence import ROUTE_INTELLIGENCE_SKU
from .x402_payment_offer import (
    X402PaymentOfferError,
    build_payment_required,
    encode_payment_required,
    payment_offer_readiness,
)


def _patch_mcp_paid_sku_metadata() -> None:
    """Keep late-bound MCP tools/list truthful without rewriting main.py.

    ``install_commercial_router`` is called after ``MCP_TOOLS`` has been built.
    We only widen the existing economic_preflight enum to the already-supported
    schema SKU; no new MCP mutation surface is added here.
    """
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
            "preference, not funds. Real payment, reserve, spend and settlement "
            "remain fail-closed until the live payment handler is separately activated."
        )
        return


def install_commercial_payment_routes(app) -> None:
    _patch_mcp_paid_sku_metadata()

    existing = {getattr(route, "path", None) for route in app.router.routes}

    if "/commercial/route-intelligence/payment-readiness" not in existing:
        def readiness_endpoint():
            return JSONResponse(
                payment_offer_readiness(),
                headers={"Cache-Control": "public, max-age=60"},
            )

        app.add_api_route(
            "/commercial/route-intelligence/payment-readiness",
            readiness_endpoint,
            methods=["GET"],
            include_in_schema=True,
            summary="Read Route Intelligence x402 payment readiness",
            description=(
                "Read-only truth surface. It does not create a quote, payment "
                "authorization, reserve, settlement, revenue, VUO or adoption proof."
            ),
        )

    if "/commercial/route-intelligence/purchase" not in existing:
        def purchase_endpoint(
            payment_signature: str | None = Header(default=None, alias="PAYMENT-SIGNATURE"),
        ):
            readiness = payment_offer_readiness()

            # AION membership or an AION-issued API key is intentionally NOT a
            # prerequisite for seeing the payment requirement. A future live
            # handler must authorize the economic scope from the rail-verified
            # payment capability itself, without adding owner-identity friction.
            #
            # Current accepted code has no live signature processor at all. Never
            # parse, echo, persist or reinterpret a signed payload. A later reviewed
            # activation commit must replace this branch with authenticated rail
            # verification before the code-owned live-handler gate can be enabled.
            if payment_signature is not None:
                return JSONResponse(
                    status_code=503,
                    content={
                        "code": "x402_live_payment_handler_not_implemented",
                        "product_sku": ROUTE_INTELLIGENCE_SKU,
                        "payment_signature_accepted": False,
                        "aion_membership_required": False,
                        "retryable_after_handler_activation": True,
                    },
                    headers={"Cache-Control": "private, no-store"},
                )

            if not readiness["launch_ready"]:
                return JSONResponse(
                    status_code=503,
                    content={
                        "code": "x402_payment_rail_not_activated",
                        "product_sku": ROUTE_INTELLIGENCE_SKU,
                        "quote_configured": readiness["quote_configured"],
                        "payment_offer_configured": readiness["payment_offer_configured"],
                        "live_payment_handler_implemented": readiness[
                            "live_payment_handler_implemented"
                        ],
                        "real_money_execution_enabled": readiness[
                            "real_money_execution_enabled"
                        ],
                        "aion_membership_required": False,
                        "quote_endpoint": readiness["quote_endpoint"],
                    },
                    headers={"Cache-Control": "private, no-store"},
                )

            # This branch cannot be reached in accepted V1 code because the
            # code-owned live-handler gate is false. It proves the exact x402 v2
            # 402 wire contract for the future reviewed activation commit.
            try:
                payment_required = build_payment_required()
            except X402PaymentOfferError as exc:
                return JSONResponse(
                    status_code=503,
                    content={"code": exc.code, "message": exc.message},
                    headers={"Cache-Control": "private, no-store"},
                )
            return JSONResponse(
                status_code=402,
                content={
                    "code": "payment_required",
                    "product_sku": ROUTE_INTELLIGENCE_SKU,
                    "protocol": "x402",
                    "x402_version": 2,
                    "aion_membership_required": False,
                },
                headers={
                    "PAYMENT-REQUIRED": encode_payment_required(payment_required),
                    "Cache-Control": "private, no-store",
                },
            )

        app.add_api_route(
            "/commercial/route-intelligence/purchase",
            purchase_endpoint,
            methods=["POST"],
            include_in_schema=True,
            summary="Purchase AION Verified Route Intelligence through x402",
            description=(
                "Buyer payment surface. AION membership/API-key authentication is not "
                "required merely to receive the x402 payment requirement. Current "
                "accepted code remains fail-closed: until a separately reviewed live "
                "payment handler and real-money gate are enabled it returns 503 and "
                "never accepts PAYMENT-SIGNATURE. When all gates are active, the "
                "unpaid response uses x402 v2 HTTP 402 with PAYMENT-REQUIRED."
            ),
        )
