"""Runtime wiring tests for the fail-closed paid Route Intelligence profile."""

from fastapi import FastAPI

from app.services import economic_kernel
from app.services.commercial_payment_routes import install_commercial_payment_routes
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
    ROUTE_INTELLIGENCE_SKU,
)


def _clear_profile():
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)


def test_runtime_installer_registers_valid_paid_profile_from_environment(monkeypatch):
    _clear_profile()
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(CURRENCY_ENV, "USDC")
    monkeypatch.setenv(PRICE_ENV, "1")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.1")

    install_commercial_payment_routes(FastAPI())

    plan = economic_kernel.TRUSTED_PRODUCT_PROFILES[ROUTE_INTELLIGENCE_SKU]
    assert plan.currency == "USDC"
    assert plan.customer_price == "1"
    assert plan.payment_fee_allowance == "0.1"
    _clear_profile()


def test_runtime_installer_removes_stale_profile_when_config_is_missing(monkeypatch):
    _clear_profile()
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(CURRENCY_ENV, "USDC")
    monkeypatch.setenv(PRICE_ENV, "1")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.1")
    install_commercial_payment_routes(FastAPI())
    assert ROUTE_INTELLIGENCE_SKU in economic_kernel.TRUSTED_PRODUCT_PROFILES

    monkeypatch.delenv(QUOTE_ENABLE_ENV)
    install_commercial_payment_routes(FastAPI())
    assert ROUTE_INTELLIGENCE_SKU not in economic_kernel.TRUSTED_PRODUCT_PROFILES
