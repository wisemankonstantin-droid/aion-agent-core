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
    for name in (QUOTE_ENABLE_ENV, PRICE_ENV, MAX_PAYMENT_FEE_ENV):
        monkeypatch.delenv(name, raising=False)
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


def test_paid_sku_is_recognized_but_unquotable_without_trusted_config():
    parsed = schemas.EconomicPreflightRequest(
        product_sku=ROUTE_INTELLIGENCE_SKU,
        currency="USD",
    )
    assert parsed.product_sku == ROUTE_INTELLIGENCE_SKU
    assert register_paid_route_intelligence_profile() is False
    assert ROUTE_INTELLIGENCE_SKU not in economic_kernel.TRUSTED_PRODUCT_PROFILES

    readiness = route_intelligence_readiness()
    assert readiness["quote_configured"] is False
    assert readiness["real_money_execution_enabled"] is False
    assert readiness["provider_execution_enabled"] is False


def test_quote_registration_requires_complete_config_and_standard_target_margin(monkeypatch):
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(PRICE_ENV, "1")
    assert register_paid_route_intelligence_profile() is False

    # 50% contribution margin clears the constitutional 40% floor but misses
    # AION's 60% standard target, so the first commercial SKU stays disabled.
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.5")
    assert register_paid_route_intelligence_profile() is False

    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.4")
    assert register_paid_route_intelligence_profile() is True
    plan = economic_kernel.TRUSTED_PRODUCT_PROFILES[ROUTE_INTELLIGENCE_SKU]
    evaluated = economic_kernel.evaluate_plan(
        plan,
        requested_currency="USD",
        requester_max_price=None,
    )
    assert evaluated["customer_price"] == "1"
    assert evaluated["maximum_total_spend"] == "0.4"
    assert evaluated["expected_margin_bps"] == 6000
    assert evaluated["policy_eligible"] is True
    assert evaluated["funding_required"] is True
    assert evaluated["execution_eligible"] is False


def test_configured_route_intelligence_creates_quote_but_cannot_activate_money(monkeypatch):
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(PRICE_ENV, "1")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.1")
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
            "currency": "USD",
            "requester_max_price": "1",
        },
    )
    assert response.status_code == 200
    quote = response.json()
    assert quote["product_sku"] == ROUTE_INTELLIGENCE_SKU
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
                currency="USD",
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
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(PRICE_ENV, "2")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.2")
    readiness = route_intelligence_readiness()
    assert readiness["quote_configured"] is True
    assert readiness["policy_eligible"] is True
    assert readiness["expected_margin_bps"] == 9000
    assert readiness["commercial_rights_scope"] == "aion_owned_route_and_verification_intelligence_only"
    assert readiness["provider_execution_enabled"] is False
    assert readiness["real_money_execution_enabled"] is False
