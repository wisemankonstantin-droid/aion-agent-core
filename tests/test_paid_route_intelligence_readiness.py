"""Commercial readiness tests do not perform real payments or provider execution."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import models, schemas
from app.db import SessionLocal
from app.main import app
from app.security import hash_key
from app.services import economic_kernel
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
    route_intelligence_readiness,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_paid_route_intelligence(monkeypatch):
    for name in (
        QUOTE_ENABLE_ENV,
        CURRENCY_ENV,
        PRICE_ENV,
        MAX_PAYMENT_FEE_ENV,
        economic_kernel.REAL_MONEY_ENABLE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    with SessionLocal() as db:
        db.execute(delete(models.EconomicTransition))
        db.execute(delete(models.EconomicOperation))
        db.commit()
    yield
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    with SessionLocal() as db:
        db.execute(delete(models.EconomicTransition))
        db.execute(delete(models.EconomicOperation))
        db.commit()


def _agent():
    token = uuid.uuid4().hex
    key = "aion_route_intel_" + token
    with SessionLocal() as db:
        row = models.Agent(
            external_id="route-intel-" + token,
            name="Route Intelligence " + token,
            protocol="REST",
            api_key_hash=hash_key(key),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, key


def _configure_quote(monkeypatch, *, currency="USDC", price="1", fee="0.1"):
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(CURRENCY_ENV, currency)
    monkeypatch.setenv(PRICE_ENV, price)
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, fee)




def test_owner_real_money_gate_is_explicit_and_fail_closed(monkeypatch):
    monkeypatch.delenv(economic_kernel.REAL_MONEY_ENABLE_ENV, raising=False)
    assert economic_kernel.configured_real_money_execution_enabled() is False

    for value in ("", "0", "true", "TRUE", "yes", " 1", "1 "):
        monkeypatch.setenv(economic_kernel.REAL_MONEY_ENABLE_ENV, value)
        assert economic_kernel.configured_real_money_execution_enabled() is False

    monkeypatch.setenv(economic_kernel.REAL_MONEY_ENABLE_ENV, "1")
    assert economic_kernel.configured_real_money_execution_enabled() is True


def test_route_readiness_reports_owner_gate_without_enabling_provider_execution(monkeypatch):
    _configure_quote(monkeypatch, price="2", fee="0.2")
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    readiness = route_intelligence_readiness()
    assert readiness["quote_configured"] is True
    assert readiness["real_money_execution_enabled"] is True
    assert readiness["provider_execution_enabled"] is False


def test_paid_sku_is_recognized_but_unquotable_without_trusted_config():
    parsed = schemas.EconomicPreflightRequest(
        product_sku=ROUTE_INTELLIGENCE_SKU,
        currency="USDC",
    )
    assert parsed.product_sku == ROUTE_INTELLIGENCE_SKU
    assert register_paid_route_intelligence_profile() is False
    assert ROUTE_INTELLIGENCE_SKU not in economic_kernel.TRUSTED_PRODUCT_PROFILES

    readiness = route_intelligence_readiness()
    assert readiness["quote_configured"] is False
    assert readiness["real_money_execution_enabled"] is False
    assert readiness["provider_execution_enabled"] is False


def test_quote_registration_requires_explicit_asset_complete_config_and_target_margin(monkeypatch):
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(PRICE_ENV, "1")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.1")
    assert register_paid_route_intelligence_profile() is False

    monkeypatch.setenv(CURRENCY_ENV, "usd")
    assert register_paid_route_intelligence_profile() is False

    # 50% contribution margin clears the constitutional 40% floor but misses
    # AION's 60% standard target, so the first commercial SKU stays disabled.
    monkeypatch.setenv(CURRENCY_ENV, "USDC")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.5")
    assert register_paid_route_intelligence_profile() is False

    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.4")
    assert register_paid_route_intelligence_profile() is True
    plan = economic_kernel.TRUSTED_PRODUCT_PROFILES[ROUTE_INTELLIGENCE_SKU]
    evaluated = economic_kernel.evaluate_plan(
        plan,
        requested_currency="USDC",
        requester_max_price=None,
    )
    assert evaluated["currency"] == "USDC"
    assert evaluated["customer_price"] == "1"
    assert evaluated["maximum_total_spend"] == "0.4"
    assert evaluated["expected_margin_bps"] == 6000
    assert evaluated["policy_eligible"] is True
    assert evaluated["funding_required"] is True
    assert evaluated["execution_eligible"] is False


def test_configured_route_intelligence_creates_quote_but_cannot_activate_money(monkeypatch):
    _configure_quote(monkeypatch)
    assert register_paid_route_intelligence_profile() is True

    agent_id, key = _agent()
    response = client.post(
        "/economic/preflight",
        headers={
            "Authorization": "Bearer " + key,
            "Idempotency-Key": "route-intel-" + uuid.uuid4().hex,
        },
        json={
            "product_sku": ROUTE_INTELLIGENCE_SKU,
            "currency": "USDC",
            "requester_max_price": "1",
        },
    )
    assert response.status_code == 200
    quote = response.json()
    assert quote["product_sku"] == ROUTE_INTELLIGENCE_SKU
    assert quote["currency"] == "USDC"
    assert quote["customer_price"] == "1"
    assert quote["maximum_total_spend"] == "0.1"
    assert quote["expected_margin_bps"] == 9000
    assert quote["policy_eligible"] is True
    assert quote["execution_eligible"] is False
    assert quote["payment_authorized"] is False
    assert quote["reserve_established"] is False
    assert quote["settlement_completed"] is False
    assert quote["truth_boundaries"]["real_money_adapter_enabled"] is False
    assert "payment_not_authorized" in quote["decision_reasons"]
    assert "reserve_not_established" in quote["decision_reasons"]
    assert "real_money_adapter_disabled" in quote["decision_reasons"]

    fiat_mismatch = client.post(
        "/economic/preflight",
        headers={
            "Authorization": "Bearer " + key,
            "Idempotency-Key": "route-intel-fiat-mismatch-" + uuid.uuid4().hex,
        },
        json={
            "product_sku": ROUTE_INTELLIGENCE_SKU,
            "currency": "USD",
            "requester_max_price": "1",
        },
    )
    assert fiat_mismatch.status_code == 422
    assert fiat_mismatch.json()["detail"]["code"] == "currency_mismatch"

    with SessionLocal() as db:
        with pytest.raises(economic_kernel.EconomicKernelError) as exc:
            economic_kernel.apply_economic_transition(
                db,
                requester_agent_id=agent_id,
                operation_id=quote["operation_id"],
                to_state="payment_authorized",
                idempotency_key="no-real-money",
                evidence_reference="not-a-real-rail",
                amount="1",
                currency="USDC",
            )
        assert exc.value.code == "real_money_adapter_disabled"

        operation = economic_kernel.get_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=quote["operation_id"],
        )
        assert operation["state"] == "quoted"
        assert operation["real_settlement_revenue"] == "0"
        assert operation["settlement_completed"] is False


def test_readiness_truth_scope_is_aion_owned_intelligence_only(monkeypatch):
    _configure_quote(monkeypatch, price="2", fee="0.2")
    readiness = route_intelligence_readiness()
    assert readiness["quote_configured"] is True
    assert readiness["currency"] == "USDC"
    assert readiness["policy_eligible"] is True
    assert readiness["expected_margin_bps"] == 9000
    assert readiness["commercial_rights_scope"] == "aion_owned_route_and_verification_intelligence_only"
    assert readiness["fx_assumption_used"] is False
    assert readiness["provider_execution_enabled"] is False
    assert readiness["real_money_execution_enabled"] is False
