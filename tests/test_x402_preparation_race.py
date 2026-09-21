"""Regression proofs for exact/upfront preparation and settlement-claim binding.

No test contacts a facilitator or moves money.
"""

import base64
import json
import os
import threading
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
from app.services.x402_exact_upfront import (
    EXACT_UPFRONT_ENABLE_ENV,
    bound_exact_payment_requirements,
)
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
    monkeypatch.setenv("CDP_API_KEY_SECRET", base64.b64encode(bytes(range(64))).decode("ascii"))
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


def _payment_header(purchase_id: str, result_digest: str, *, signature_byte="a") -> str:
    requirements = bound_exact_payment_requirements(purchase_id, result_digest)
    payload = {
        "x402Version": 2,
        "resource": {
            "url": "https://aion.example/commercial/route-intelligence/purchase",
            "description": "fixture",
            "mimeType": "application/json",
        },
        "accepted": requirements,
        "payload": {
            "signature": "0x" + signature_byte * 130,
            "authorization": {
                "from": "0x" + "3" * 40,
                "to": requirements["payTo"],
                "value": requirements["amount"],
                "validAfter": "1",
                "validBefore": "4102444800",
                "nonce": "0x" + signature_byte * 64,
            },
        },
    }
    return base64.b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _settled():
    transaction = "0x" + "4" * 64
    return {
        "outcome": "settled",
        "transaction": transaction,
        "network": "eip155:8453",
        "payer": "0x" + "3" * 40,
        "amount": "1250000",
        "response": {
            "success": True,
            "transaction": transaction,
            "network": "eip155:8453",
            "payer": "0x" + "3" * 40,
            "amount": "1250000",
        },
    }


def test_concurrent_different_preparations_release_only_the_bound_snapshot(monkeypatch):
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
        first_purchase_id = first.purchase_id
        first_result_digest = first.result_digest
        duplicate_purchase_id = str(uuid.uuid4())
        duplicate_result_digest = "sha256:" + "f" * 64
        duplicate_requirements = bound_exact_payment_requirements(
            duplicate_purchase_id, duplicate_result_digest
        )
        duplicate = RouteIntelligencePurchase(
            purchase_id=duplicate_purchase_id,
            product_sku=first.product_sku,
            request_digest=first.request_digest,
            request_evidence=first.request_evidence,
            result_digest=duplicate_result_digest,
            prepared_result=_route_result("two"),
            quote_currency=first.quote_currency,
            quote_amount=first.quote_amount,
            network=first.network,
            asset=first.asset,
            asset_code=first.asset_code,
            pay_to=first.pay_to,
            atomic_amount=first.atomic_amount,
            payment_requirements_digest=route_intelligence_purchase._digest(duplicate_requirements),
            state="prepared",
            prepared_at=first.prepared_at + timedelta(microseconds=1),
            expires_at=first.expires_at,
            updated_at=first.updated_at,
        )
        db.add(duplicate)
        db.commit()

    settlement_calls = []

    def settle(payload, requirements):
        settlement_calls.append(requirements["extra"]["aionPurchaseId"])
        return _settled()

    monkeypatch.setattr(route_intelligence_purchase, "settle_exact_upfront", settle)

    paid = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={
            "PAYMENT-SIGNATURE": _payment_header(
                first_purchase_id, first_result_digest
            )
        },
    )
    assert paid.status_code == 200
    assert paid.json()["purchase_id"] == first_purchase_id
    assert paid.json()["prepared_result_digest"] == first_result_digest
    assert paid.json()["result"] == _route_result("one")
    assert settlement_calls == [first_purchase_id]

    with SessionLocal() as db:
        first = db.scalar(
            select(RouteIntelligencePurchase).where(
                RouteIntelligencePurchase.purchase_id == first_purchase_id
            )
        )
        duplicate = db.scalar(
            select(RouteIntelligencePurchase).where(
                RouteIntelligencePurchase.purchase_id == duplicate_purchase_id
            )
        )
        assert first.state == "entitled"
        assert duplicate.state == "prepared"
        assert duplicate.payment_payload_digest is None


def test_expired_payment_binding_cannot_slide_to_newer_snapshot(monkeypatch):
    _configure(monkeypatch)
    marker = {"value": "one"}
    monkeypatch.setattr(
        commercial_router,
        "plan_commercial_route",
        lambda db, *, requester_agent_id, payload: _route_result(marker["value"]),
    )

    first_response = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert first_response.status_code == 402
    first_body = first_response.json()
    old_signature = _payment_header(
        first_body["purchase_id"], first_body["prepared_result_digest"], signature_byte="b"
    )

    with SessionLocal() as db:
        first = db.scalar(
            select(RouteIntelligencePurchase).where(
                RouteIntelligencePurchase.purchase_id == first_body["purchase_id"]
            )
        )
        first.expires_at = first.prepared_at
        db.add(first)
        db.commit()

    marker["value"] = "two"
    second_response = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert second_response.status_code == 402
    second_body = second_response.json()
    assert second_body["purchase_id"] != first_body["purchase_id"]
    assert second_body["prepared_result_digest"] != first_body["prepared_result_digest"]

    settlement_calls = []
    monkeypatch.setattr(
        route_intelligence_purchase,
        "settle_exact_upfront",
        lambda payload, requirements: settlement_calls.append(1),
    )

    blocked = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": old_signature},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "preparation_expired"
    assert blocked.json()["result_released"] is False
    assert settlement_calls == []

    with SessionLocal() as db:
        newer = db.scalar(
            select(RouteIntelligencePurchase).where(
                RouteIntelligencePurchase.purchase_id == second_body["purchase_id"]
            )
        )
        assert newer.state == "prepared"
        assert newer.payment_payload_digest is None


@pytest.mark.skipif(
    os.getenv("AION_POSTGRES_GATE") != "1",
    reason="requires the disposable PostgreSQL release-gate database",
)
def test_postgres_parallel_same_payment_claim_contacts_facilitator_once(monkeypatch):
    """Two independent DB sessions cannot both reach the money-moving seam."""
    _configure(monkeypatch)
    monkeypatch.setattr(
        commercial_router,
        "plan_commercial_route",
        lambda db, *, requester_agent_id, payload: _route_result("parallel"),
    )
    prepared = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert prepared.status_code == 402
    body = prepared.json()
    signature = _payment_header(body["purchase_id"], body["prepared_result_digest"], signature_byte="c")

    original_validate = route_intelligence_purchase._validate_payment_payload
    before_claim = threading.Barrier(2)
    calls = []
    calls_lock = threading.Lock()

    def synchronized_validate(data, requirements):
        digest = original_validate(data, requirements)
        before_claim.wait(timeout=5)
        return digest

    def settle(payload, requirements):
        with calls_lock:
            calls.append(requirements["extra"]["aionPurchaseId"])
        return _settled()

    monkeypatch.setattr(route_intelligence_purchase, "_validate_payment_payload", synchronized_validate)
    monkeypatch.setattr(route_intelligence_purchase, "settle_exact_upfront", settle)

    outcomes = []
    outcome_lock = threading.Lock()

    def worker():
        with SessionLocal() as db:
            try:
                value = route_intelligence_purchase.settle_and_release(
                    db, {"need": "research"}, signature
                )
                outcome = ("ok", value["state"], value["idempotent_replay"])
            except route_intelligence_purchase.RouteIntelligencePurchaseError as exc:
                outcome = ("error", exc.code, None)
        with outcome_lock:
            outcomes.append(outcome)

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)

    assert calls == [body["purchase_id"]]
    assert len(outcomes) == 2
    assert any(outcome[0] == "ok" and outcome[1] == "entitled" for outcome in outcomes)
    assert all(
        outcome[0] == "ok"
        or outcome[1] in {"payment_settlement_not_retryable", "payment_claim_conflict"}
        for outcome in outcomes
    )

    with SessionLocal() as db:
        row = db.scalar(
            select(RouteIntelligencePurchase).where(
                RouteIntelligencePurchase.purchase_id == body["purchase_id"]
            )
        )
        assert row is not None
        assert row.state == "entitled"
        assert row.payment_payload_digest is not None
        assert row.transaction_id == "0x" + "4" * 64
