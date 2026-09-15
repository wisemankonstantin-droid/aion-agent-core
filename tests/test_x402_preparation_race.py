"""Regression proof for ambiguous concurrent exact/upfront preparations.

No test contacts a facilitator or moves money.
"""

import base64
import json
from datetime import timedelta
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import app
from app.payment_models import RouteIntelligencePurchase
from app.services import commercial_router, economic_kernel, route_intelligence_purchase
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
)
from app.services.x402_exact_upfront import EXACT_UPFRONT_ENABLE_ENV, exact_payment_requirements
from app.services.x402_payment_offer import (
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


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)
    yield
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()


def _configure(monkeypatch):
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(CURRENCY_ENV, "USDC")
    monkeypatch.setenv(PRICE_ENV, "1.25")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.10")
    assert register_paid_route_intelligence_profile() is True
    monkeypatch.setenv(EXACT_UPFRONT_ENABLE_ENV, "1")
    monkeypatch.setenv(NETWORK_ENV, "eip155:8453")
    monkeypatch.setenv(ASSET_ENV, "0x" + "1" * 40)
    monkeypatch.setenv(ASSET_CODE_ENV, "USDC")
    monkeypatch.setenv(ASSET_NAME_ENV, "USD Coin")
    monkeypatch.setenv(ASSET_VERSION_ENV, "2")
    monkeypatch.setenv(ASSET_DECIMALS_ENV, "6")
    monkeypatch.setenv(PAY_TO_ENV, "0x" + "2" * 40)
    monkeypatch.setenv(MAX_TIMEOUT_SECONDS_ENV, "60")
    monkeypatch.setenv(ASSET_TRANSFER_METHOD_ENV, "eip3009")
    monkeypatch.setenv("CDP_API_KEY_ID", "fixture-key-id")
    monkeypatch.setenv("CDP_API_KEY_SECRET", "fixture-not-used")
    monkeypatch.setenv("AION_PUBLIC_URL", "https://aion.example")
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)


def _route_result(marker: str) -> dict:
    return {
        "route_version": "commercial_router_v1",
        "state": "qualified_unpriced",
        "need": "research",
        "selected_provider": {
            "identifier": f"fixture.{marker}",
            "interaction_url": f"https://{marker}.example/a2a",
            "qualification_state": "declaration_qualified",
            "provider_verification_state": "historical_callability_verified",
        },
        "provider_verification_state": "historical_callability_verified",
        "execution": {
            "mode": "planning_only",
            "provider_interaction_endpoint_contacted": False,
            "payment_rail_contacted": False,
        },
    }


def _payment_header() -> str:
    requirements = exact_payment_requirements()
    payload = {
        "x402Version": 2,
        "resource": {
            "url": "https://aion.example/commercial/route-intelligence/purchase",
            "description": "fixture",
            "mimeType": "application/json",
        },
        "accepted": requirements,
        "payload": {
            "signature": "0x" + "a" * 130,
            "authorization": {
                "from": "0x" + "3" * 40,
                "to": requirements["payTo"],
                "value": requirements["amount"],
                "validAfter": "1",
                "validBefore": "4102444800",
                "nonce": "0x" + "a" * 64,
            },
        },
    }
    return base64.b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def test_different_concurrent_preparations_block_before_facilitator_contact(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        commercial_router,
        "plan_commercial_route",
        lambda db, *, requester_agent_id, payload: _route_result("one"),
    )

    prepared = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert prepared.status_code == 402

    with SessionLocal() as db:
        first = db.scalar(select(RouteIntelligencePurchase))
        assert first is not None
        duplicate = RouteIntelligencePurchase(
            purchase_id=str(uuid.uuid4()),
            product_sku=first.product_sku,
            request_digest=first.request_digest,
            request_evidence=first.request_evidence,
            result_digest="sha256:" + "f" * 64,
            prepared_result=_route_result("two"),
            quote_currency=first.quote_currency,
            quote_amount=first.quote_amount,
            network=first.network,
            asset=first.asset,
            asset_code=first.asset_code,
            pay_to=first.pay_to,
            atomic_amount=first.atomic_amount,
            payment_requirements_digest=first.payment_requirements_digest,
            state="prepared",
            prepared_at=first.prepared_at + timedelta(microseconds=1),
            expires_at=first.expires_at,
            updated_at=first.updated_at,
        )
        db.add(duplicate)
        db.commit()

    settlement_calls = []
    monkeypatch.setattr(
        route_intelligence_purchase,
        "settle_exact_upfront",
        lambda payload, requirements: settlement_calls.append(1),
    )

    blocked = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": _payment_header()},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ambiguous_preparation_binding"
    assert blocked.json()["result_released"] is False
    assert settlement_calls == []

    with SessionLocal() as db:
        rows = list(db.scalars(select(RouteIntelligencePurchase)).all())
        assert len(rows) == 2
        assert all(row.state == "prepared" for row in rows)
        assert all(row.payment_payload_digest is None for row in rows)
