"""Production-first x402 v2 ``exact`` + ``upfront`` payment contract.

The contract is intentionally separate from the future auth-capture escrow path.
With ``upfront`` the facilitator settles before AION releases the prepared
resource, matching AION's PAY BEFORE EXECUTION law without pretending that a
settled payment is a reserve.
"""
from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
import json
import os
import re

from ..public_origin import canonical_public_origin
from . import economic_kernel
from .paid_route_intelligence import (
    ROUTE_INTELLIGENCE_SKU,
    configured_route_intelligence_plan,
    route_intelligence_readiness,
)
from .x402_payment_offer import (
    ASSET_CODE_ENV,
    ASSET_DECIMALS_ENV,
    ASSET_ENV,
    ASSET_NAME_ENV,
    ASSET_TRANSFER_METHOD_ENV,
    ASSET_VERSION_ENV,
    MAX_TIMEOUT_SECONDS_ENV,
    NETWORK_ENV,
    PAY_TO_ENV,
)


EXACT_UPFRONT_ENABLE_ENV = "AION_X402_EXACT_UPFRONT_ENABLED"
LIVE_EXACT_SETTLEMENT_HANDLER_IMPLEMENTED = True

_CAIP_EVM = re.compile(r"^eip155:[1-9][0-9]{0,18}$")
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ASSET_CODE = re.compile(r"^[A-Z][A-Z0-9]{2,15}$")
_TOKEN_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,64}$")
_TOKEN_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,16}$")


class ExactUpfrontError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _bounded_int(name: str, *, minimum: int, maximum: int) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip().isdigit():
        return None
    value = int(raw.strip())
    return value if minimum <= value <= maximum else None


def _address(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value if _EVM_ADDRESS.fullmatch(value) else None


def _base_units(amount: str, decimals: int) -> str | None:
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return None
    scaled = value * (Decimal(10) ** decimals)
    if scaled < 0 or scaled != scaled.to_integral_value():
        return None
    return str(int(scaled))


def configured_exact_upfront_offer() -> dict | None:
    if os.getenv(EXACT_UPFRONT_ENABLE_ENV) != "1":
        return None
    plan = configured_route_intelligence_plan()
    if plan is None:
        return None

    network = (os.getenv(NETWORK_ENV) or "").strip()
    asset = _address(ASSET_ENV)
    asset_code = (os.getenv(ASSET_CODE_ENV) or "").strip()
    token_name = (os.getenv(ASSET_NAME_ENV) or "").strip()
    token_version = (os.getenv(ASSET_VERSION_ENV) or "").strip()
    decimals = _bounded_int(ASSET_DECIMALS_ENV, minimum=0, maximum=18)
    pay_to = _address(PAY_TO_ENV)
    max_timeout = _bounded_int(MAX_TIMEOUT_SECONDS_ENV, minimum=1, maximum=3600)
    transfer_method = (os.getenv(ASSET_TRANSFER_METHOD_ENV) or "").strip()

    if not _CAIP_EVM.fullmatch(network):
        return None
    if asset is None or pay_to is None or decimals is None or max_timeout is None:
        return None
    if not _ASSET_CODE.fullmatch(asset_code) or asset_code != plan.currency:
        return None
    if not _TOKEN_NAME.fullmatch(token_name) or not _TOKEN_VERSION.fullmatch(token_version):
        return None
    if transfer_method not in {"eip3009", "permit2"}:
        return None

    amount = _base_units(plan.customer_price, decimals)
    if amount is None or int(amount) <= 0:
        return None

    return {
        "network": network,
        "asset": asset,
        "asset_code": asset_code,
        "token_name": token_name,
        "token_version": token_version,
        "asset_decimals": decimals,
        "pay_to": pay_to,
        "atomic_amount": amount,
        "quote_currency": plan.currency,
        "quote_amount": plan.customer_price,
        "max_timeout_seconds": max_timeout,
        "asset_transfer_method": transfer_method,
    }


def exact_payment_requirements() -> dict:
    offer = configured_exact_upfront_offer()
    if offer is None:
        raise ExactUpfrontError(
            "x402_exact_upfront_not_configured",
            "Bounded x402 exact upfront offer is not fully configured",
        )
    return {
        "scheme": "exact",
        "network": offer["network"],
        "amount": offer["atomic_amount"],
        "asset": offer["asset"],
        "payTo": offer["pay_to"],
        "maxTimeoutSeconds": offer["max_timeout_seconds"],
        "extra": {
            "name": offer["token_name"],
            "version": offer["token_version"],
            "assetTransferMethod": offer["asset_transfer_method"],
            "paymentFlow": "upfront",
        },
    }


def build_exact_payment_required() -> dict:
    requirements = exact_payment_requirements()
    resource_url = (
        canonical_public_origin().rstrip("/")
        + "/commercial/route-intelligence/purchase"
    )
    return {
        "x402Version": 2,
        "error": "PAYMENT-SIGNATURE header is required",
        "resource": {
            "url": resource_url,
            "description": (
                "AION Verified Route Intelligence: a prepared bounded route and "
                "verification evidence result"
            ),
            "mimeType": "application/json",
        },
        "accepts": [requirements],
    }


def encode_exact_payment_required(payment_required: dict) -> str:
    raw = json.dumps(
        payment_required,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def exact_upfront_readiness() -> dict:
    product = route_intelligence_readiness()
    offer = configured_exact_upfront_offer()
    credentials_present = bool(
        (os.getenv("CDP_API_KEY_ID") or "").strip()
        and (os.getenv("CDP_API_KEY_SECRET") or "").strip()
    )
    configured = offer is not None
    return {
        "product_sku": ROUTE_INTELLIGENCE_SKU,
        "protocol": "x402",
        "x402_version": 2,
        "scheme": "exact",
        "payment_flow": "upfront",
        "quote_configured": bool(product.get("quote_configured")),
        "payment_offer_configured": configured,
        "facilitator_credentials_configured": credentials_present,
        "live_payment_handler_implemented": LIVE_EXACT_SETTLEMENT_HANDLER_IMPLEMENTED,
        "real_money_execution_enabled": bool(economic_kernel.REAL_MONEY_EXECUTION_ENABLED),
        "launch_ready": bool(
            configured
            and credentials_present
            and LIVE_EXACT_SETTLEMENT_HANDLER_IMPLEMENTED
            and economic_kernel.REAL_MONEY_EXECUTION_ENABLED
        ),
        "asset_code": offer["asset_code"] if offer else None,
        "network": offer["network"] if offer else None,
        "purchase_endpoint": "/commercial/route-intelligence/purchase",
        "truth_boundaries": {
            "settlement_happens_before_resource_release": True,
            "upfront_settlement_is_not_a_reserve": True,
            "buyer_membership_required": False,
            "requester_budget_is_not_funds": True,
            "no_hidden_fx": True,
            "raw_payment_signature_persisted": False,
        },
    }
