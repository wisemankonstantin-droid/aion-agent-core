"""Fail-closed buyer-facing x402 v2 auth-capture payment requirement builder.

This module only constructs and validates public payment requirements. It does
not verify PAYMENT-SIGNATURE, contact a facilitator, hold funds, capture funds,
or settle money. The public route must not advertise a payable 402 until a
separately reviewed live handler exists.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
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


OFFER_ENABLE_ENV = "AION_X402_PAYMENT_OFFER_ENABLED"
NETWORK_ENV = "AION_X402_NETWORK"
ASSET_ENV = "AION_X402_ASSET"
ASSET_NAME_ENV = "AION_X402_ASSET_NAME"
ASSET_VERSION_ENV = "AION_X402_ASSET_VERSION"
ASSET_DECIMALS_ENV = "AION_X402_ASSET_DECIMALS"
PAY_TO_ENV = "AION_X402_PAY_TO"
AUTH_CAPTURE_ESCROW_ENV = "AION_X402_AUTH_CAPTURE_ESCROW"
CAPTURE_AUTHORIZER_ENV = "AION_X402_CAPTURE_AUTHORIZER"
RECEIVER_AUTHORIZER_ENV = "AION_X402_RECEIVER_AUTHORIZER"
FEE_RECIPIENT_ENV = "AION_X402_FEE_RECIPIENT"
MIN_FEE_BPS_ENV = "AION_X402_MIN_FEE_BPS"
MAX_FEE_BPS_ENV = "AION_X402_MAX_FEE_BPS"
MAX_TIMEOUT_SECONDS_ENV = "AION_X402_MAX_TIMEOUT_SECONDS"
CAPTURE_WINDOW_SECONDS_ENV = "AION_X402_CAPTURE_WINDOW_SECONDS"
REFUND_WINDOW_SECONDS_ENV = "AION_X402_REFUND_WINDOW_SECONDS"
ASSET_TRANSFER_METHOD_ENV = "AION_X402_ASSET_TRANSFER_METHOD"

# This is intentionally code-owned, not an environment flag. A production
# payment handler must be implemented, reviewed and tested before changing it.
LIVE_PAYMENT_HANDLER_IMPLEMENTED = False

_CAIP_EVM = re.compile(r"^eip155:[1-9][0-9]{0,18}$")
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TOKEN_NAME = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_TOKEN_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,16}$")


class X402PaymentOfferError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _bounded_int(name: str, *, minimum: int, maximum: int) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip() or not raw.strip().isdigit():
        return None
    value = int(raw.strip())
    if value < minimum or value > maximum:
        return None
    return value


def _address(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value if _EVM_ADDRESS.fullmatch(value) else None


def _exact_base_units(amount: str, decimals: int) -> str | None:
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return None
    scaled = value * (Decimal(10) ** decimals)
    if scaled < 0 or scaled != scaled.to_integral_value():
        return None
    return str(int(scaled))


def _configured_offer(*, now: datetime | None = None) -> dict | None:
    if os.getenv(OFFER_ENABLE_ENV) != "1":
        return None
    plan = configured_route_intelligence_plan()
    if plan is None:
        return None

    network = (os.getenv(NETWORK_ENV) or "").strip()
    asset = _address(ASSET_ENV)
    pay_to = _address(PAY_TO_ENV)
    escrow = _address(AUTH_CAPTURE_ESCROW_ENV)
    capture_authorizer = _address(CAPTURE_AUTHORIZER_ENV)
    receiver_authorizer = _address(RECEIVER_AUTHORIZER_ENV)
    fee_recipient = _address(FEE_RECIPIENT_ENV)
    asset_name = (os.getenv(ASSET_NAME_ENV) or "").strip()
    asset_version = (os.getenv(ASSET_VERSION_ENV) or "").strip()
    decimals = _bounded_int(ASSET_DECIMALS_ENV, minimum=0, maximum=18)
    min_fee_bps = _bounded_int(MIN_FEE_BPS_ENV, minimum=0, maximum=10000)
    max_fee_bps = _bounded_int(MAX_FEE_BPS_ENV, minimum=0, maximum=10000)
    max_timeout = _bounded_int(MAX_TIMEOUT_SECONDS_ENV, minimum=1, maximum=3600)
    capture_window = _bounded_int(CAPTURE_WINDOW_SECONDS_ENV, minimum=60, maximum=7 * 24 * 3600)
    refund_window = _bounded_int(REFUND_WINDOW_SECONDS_ENV, minimum=120, maximum=30 * 24 * 3600)
    transfer_method = (os.getenv(ASSET_TRANSFER_METHOD_ENV) or "").strip()

    if not _CAIP_EVM.fullmatch(network):
        return None
    if None in {
        asset,
        pay_to,
        escrow,
        capture_authorizer,
        receiver_authorizer,
        fee_recipient,
        decimals,
        min_fee_bps,
        max_fee_bps,
        max_timeout,
        capture_window,
        refund_window,
    }:
        return None
    if not _TOKEN_NAME.fullmatch(asset_name) or not _TOKEN_VERSION.fullmatch(asset_version):
        return None
    if asset_name != plan.currency:
        return None
    if min_fee_bps > max_fee_bps:
        return None
    if refund_window <= capture_window:
        return None
    if transfer_method not in {"eip3009", "permit2"}:
        return None

    amount = _exact_base_units(plan.customer_price, decimals)
    if amount is None:
        return None

    timestamp = now or datetime.now(timezone.utc)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise X402PaymentOfferError("invalid_clock", "Payment requirement clock must be timezone-aware")
    capture_deadline = int((timestamp + timedelta(seconds=capture_window)).timestamp())
    refund_deadline = int((timestamp + timedelta(seconds=refund_window)).timestamp())

    return {
        "network": network,
        "asset": asset,
        "asset_name": asset_name,
        "asset_version": asset_version,
        "asset_decimals": decimals,
        "amount": amount,
        "pay_to": pay_to,
        "auth_capture_escrow": escrow,
        "capture_authorizer": capture_authorizer,
        "receiver_authorizer": receiver_authorizer,
        "fee_recipient": fee_recipient,
        "min_fee_bps": min_fee_bps,
        "max_fee_bps": max_fee_bps,
        "max_timeout_seconds": max_timeout,
        "capture_deadline": capture_deadline,
        "refund_deadline": refund_deadline,
        "asset_transfer_method": transfer_method,
        "quote_currency": plan.currency,
        "quote_amount": plan.customer_price,
    }


def payment_offer_readiness() -> dict:
    product = route_intelligence_readiness()
    offer = _configured_offer()
    configured = offer is not None
    return {
        "product_sku": ROUTE_INTELLIGENCE_SKU,
        "quote_configured": bool(product.get("quote_configured")),
        "payment_offer_configured": configured,
        "protocol": "x402",
        "x402_version": 2,
        "scheme": "auth-capture",
        "payment_flow": "escrow",
        "live_payment_handler_implemented": LIVE_PAYMENT_HANDLER_IMPLEMENTED,
        "real_money_execution_enabled": bool(economic_kernel.REAL_MONEY_EXECUTION_ENABLED),
        "launch_ready": bool(
            configured
            and LIVE_PAYMENT_HANDLER_IMPLEMENTED
            and economic_kernel.REAL_MONEY_EXECUTION_ENABLED
        ),
        "payment_signature_accepted_now": bool(
            configured
            and LIVE_PAYMENT_HANDLER_IMPLEMENTED
            and economic_kernel.REAL_MONEY_EXECUTION_ENABLED
        ),
        "quote_endpoint": "/economic/preflight",
        "purchase_endpoint": "/commercial/route-intelligence/purchase",
        "truth_boundaries": {
            "payment_requirement_is_not_authorization": True,
            "payment_signature_is_not_reserve_until_verified_and_authorized": True,
            "stablecoin_is_not_silently_treated_as_fiat": True,
            "no_fx_assumption": True,
        },
    }


def build_payment_required(*, now: datetime | None = None) -> dict:
    offer = _configured_offer(now=now)
    if offer is None:
        raise X402PaymentOfferError(
            "x402_payment_offer_not_configured",
            "Bounded x402 auth-capture payment offer is not fully configured",
        )
    resource_url = canonical_public_origin().rstrip("/") + "/commercial/route-intelligence/purchase"
    return {
        "x402Version": 2,
        "error": "PAYMENT-SIGNATURE header is required",
        "resource": {
            "url": resource_url,
            "description": "AION Verified Route Intelligence: bounded route and verification evidence",
            "mimeType": "application/json",
        },
        "accepts": [
            {
                "scheme": "auth-capture",
                "network": offer["network"],
                "amount": offer["amount"],
                "asset": offer["asset"],
                "payTo": offer["pay_to"],
                "maxTimeoutSeconds": offer["max_timeout_seconds"],
                "extra": {
                    "name": offer["asset_name"],
                    "version": offer["asset_version"],
                    "authCaptureEscrow": offer["auth_capture_escrow"],
                    "captureAuthorizer": offer["capture_authorizer"],
                    "operatorType": "delegated",
                    "receiverAuthorizer": offer["receiver_authorizer"],
                    "policy": "0x0000000000000000000000000000000000000000",
                    "paymentFlow": "escrow",
                    "captureMode": "deferred",
                    "captureDeadline": offer["capture_deadline"],
                    "refundDeadline": offer["refund_deadline"],
                    "minFeeBps": offer["min_fee_bps"],
                    "maxFeeBps": offer["max_fee_bps"],
                    "feeRecipient": offer["fee_recipient"],
                    "assetTransferMethod": offer["asset_transfer_method"],
                },
            }
        ],
    }


def encode_payment_required(payment_required: dict) -> str:
    raw = json.dumps(
        payment_required,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")
