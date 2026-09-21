"""Fail-closed commercial readiness for AION-owned Verified Route Intelligence.

This module deliberately does not activate a payment rail, provider execution,
or real-money state transitions. It only makes one AION-owned paid SKU eligible
for Economic Kernel quoting when an operator supplies a bounded trusted asset,
price, and maximum merchant-side payment fee. Missing or economically invalid
config leaves the SKU unregistered and therefore unquotable.
"""
from __future__ import annotations

from decimal import Decimal
import os

from . import economic_kernel
from .economic_kernel import (
    STANDARD_TARGET_MARGIN_BPS,
    TRUSTED_PRODUCT_PROFILES,
    EconomicKernelError,
    TrustedEconomicPlan,
    canonical_currency,
    canonical_money,
    evaluate_plan,
)

ROUTE_INTELLIGENCE_SKU = "aion.verified.route_intelligence.v1"
QUOTE_ENABLE_ENV = "AION_ROUTE_INTELLIGENCE_QUOTE_ENABLED"
CURRENCY_ENV = "AION_ROUTE_INTELLIGENCE_CURRENCY"
PRICE_ENV = "AION_ROUTE_INTELLIGENCE_PRICE"
MAX_PAYMENT_FEE_ENV = "AION_ROUTE_INTELLIGENCE_MAX_PAYMENT_FEE"


def _configured_money(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        value, canonical = canonical_money(raw.strip())
    except EconomicKernelError:
        return None
    if value < 0:
        return None
    return canonical


def _configured_currency() -> str | None:
    raw = os.getenv(CURRENCY_ENV)
    if raw is None or not raw.strip():
        return None
    try:
        return canonical_currency(raw.strip())
    except EconomicKernelError:
        return None


def configured_route_intelligence_plan() -> TrustedEconomicPlan | None:
    """Return a trusted plan only when the full bounded quote config is valid.

    Route Intelligence is AION-owned routing/verification evidence. It does not
    include resale of a third-party provider result. Current direct variable
    provider spend is zero; the configured payment fee is treated
    conservatively as both expected and maximum variable monetary cost.

    Currency is explicit and exact. AION does not silently treat a stablecoin
    such as USDC as fiat USD and does not invent an FX conversion.
    """
    if os.getenv(QUOTE_ENABLE_ENV) != "1":
        return None

    currency = _configured_currency()
    price = _configured_money(PRICE_ENV)
    maximum_payment_fee = _configured_money(MAX_PAYMENT_FEE_ENV)
    if currency is None or price is None or maximum_payment_fee is None:
        return None
    if Decimal(price) <= 0:
        return None

    plan = TrustedEconomicPlan(
        product_sku=ROUTE_INTELLIGENCE_SKU,
        currency=currency,
        customer_price=price,
        expected_variable_cost="0",
        maximum_variable_cost="0",
        verification_cost="0",
        payment_fee_allowance=maximum_payment_fee,
        maximum_attempts=1,
        commercial_rights_state="allowed",
        maximum_total_spend_cap=maximum_payment_fee,
        direct_expected_cost_per_vuo=maximum_payment_fee,
    )

    try:
        evaluated = evaluate_plan(
            plan,
            requested_currency=currency,
            requester_max_price=None,
        )
    except EconomicKernelError:
        return None

    # The Economic Constitution has a 40% hard floor, while AION targets 60%+
    # for standard paid work. The first commercial SKU should not launch below
    # the target merely because it clears the absolute floor.
    if not evaluated["policy_eligible"]:
        return None
    if int(evaluated["expected_margin_bps"]) < STANDARD_TARGET_MARGIN_BPS:
        return None
    return plan


def register_paid_route_intelligence_profile() -> bool:
    """Register the SKU for quoting only; real-money execution remains disabled."""
    plan = configured_route_intelligence_plan()
    if plan is None:
        TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
        return False
    TRUSTED_PRODUCT_PROFILES[ROUTE_INTELLIGENCE_SKU] = plan
    return True


def route_intelligence_readiness() -> dict:
    plan = configured_route_intelligence_plan()
    if plan is None:
        reasons = []
        if os.getenv(QUOTE_ENABLE_ENV) != "1":
            reasons.append("route_intelligence_quote_disabled")
        if _configured_currency() is None:
            reasons.append("route_intelligence_currency_missing_or_invalid")
        price = _configured_money(PRICE_ENV)
        if price is None or Decimal(price) <= 0:
            reasons.append("route_intelligence_price_missing_invalid_or_nonpositive")
        if _configured_money(MAX_PAYMENT_FEE_ENV) is None:
            reasons.append("route_intelligence_maximum_payment_fee_missing_or_invalid")
        if not reasons:
            reasons.append("route_intelligence_quote_economically_ineligible")
        return {
            "product_sku": ROUTE_INTELLIGENCE_SKU,
            "quote_configured": False,
            "real_money_execution_enabled": bool(economic_kernel.REAL_MONEY_EXECUTION_ENABLED),
            "provider_execution_enabled": False,
            "reason": "trusted_asset_price_or_max_payment_fee_missing_or_economically_ineligible",
            "blocking_reasons": reasons,
        }
    evaluated = evaluate_plan(
        plan,
        requested_currency=plan.currency,
        requester_max_price=None,
    )
    return {
        "product_sku": ROUTE_INTELLIGENCE_SKU,
        "quote_configured": True,
        "currency": evaluated["currency"],
        "customer_price": evaluated["customer_price"],
        "maximum_payment_fee": evaluated["payment_fee_allowance"],
        "expected_margin_bps": evaluated["expected_margin_bps"],
        "minimum_margin_bps": evaluated["minimum_margin_bps"],
        "standard_target_margin_bps": evaluated["standard_target_margin_bps"],
        "policy_eligible": evaluated["policy_eligible"],
        "real_money_execution_enabled": bool(economic_kernel.REAL_MONEY_EXECUTION_ENABLED),
        "provider_execution_enabled": False,
        "commercial_rights_scope": "aion_owned_route_and_verification_intelligence_only",
        "fx_assumption_used": False,
        "blocking_reasons": [],
    }
