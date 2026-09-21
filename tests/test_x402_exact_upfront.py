"""Controlled exact/upfront fixtures. No test contacts a facilitator or moves money."""

import base64
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import models
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
    build_exact_payment_required,
    exact_upfront_readiness,
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

_ENV_NAMES = (
    QUOTE_ENABLE_ENV,
    CURRENCY_ENV,
    PRICE_ENV,
    MAX_PAYMENT_FEE_ENV,
    EXACT_UPFRONT_ENABLE_ENV,
    NETWORK_ENV,
    ASSET_ENV,
    ASSET_CODE_ENV,
    ASSET_NAME_ENV,
    ASSET_VERSION_ENV,
    ASSET_DECIMALS_ENV,
    PAY_TO_ENV,
    MAX_TIMEOUT_SECONDS_ENV,
    ASSET_TRANSFER_METHOD_ENV,
    "CDP_API_KEY_ID",
    "CDP_API_KEY_SECRET",
)


@pytest.fixture(autouse=True)
def isolate_exact_upfront(monkeypatch):
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AION_PUBLIC_URL", "https://aion.example")
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    yield
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()


def _configure(monkeypatch, *, real_money=True):
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
    monkeypatch.setenv(
        "CDP_API_KEY_SECRET",
        base64.b64encode(bytes(range(64))).decode("ascii"),
    )
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", real_money)


def _route_result(need="research"):
    return {
        "route_version": "commercial_router_v1",
        "state": "qualified_unpriced",
        "need": need,
        "selected_provider": {
            "identifier": "fixture.provider",
            "interaction_url": "https://provider.example/a2a",
            "qualification_state": "declaration_qualified",
            "provider_verification_state": "historical_callability_verified",
        },
        "provider_verification_state": "historical_callability_verified",
        "execution": {
            "mode": "planning_only",
            "provider_interaction_endpoint_contacted": False,
            "payment_rail_contacted": False,
        },
        "truth_boundaries": {
            "historical_callability_is_not_current_job_completion": True,
            "route_plan_is_not_vuo_or_adoption_proof": True,
        },
    }


def _mock_plan(monkeypatch):
    calls = []

    def plan(db, *, requester_agent_id, payload):
        calls.append((requester_agent_id, payload.need))
        return _route_result(payload.need)

    monkeypatch.setattr(commercial_router, "plan_commercial_route", plan)
    return calls


def _latest_preparation() -> RouteIntelligencePurchase:
    with SessionLocal() as db:
        row = db.scalar(
            select(RouteIntelligencePurchase)
            .order_by(RouteIntelligencePurchase.prepared_at.desc(), RouteIntelligencePurchase.id.desc())
            .limit(1)
        )
        assert row is not None
        # Detach only the scalar values used below before the session closes.
        row.purchase_id = str(row.purchase_id)
        row.result_digest = str(row.result_digest)
        db.expunge(row)
        return row


def _payment_header(*, signature_byte="a", purchase_id=None, result_digest=None):
    if purchase_id is None or result_digest is None:
        row = _latest_preparation()
        purchase_id = row.purchase_id
        result_digest = row.result_digest
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


def _settled(transaction="0x" + "4" * 64):
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


def test_exact_upfront_readiness_and_wire_contract_are_fail_closed(monkeypatch):
    readiness = exact_upfront_readiness()
    assert readiness["launch_ready"] is False
    assert readiness["activation_ready_except_master_gate"] is False
    assert "route_intelligence_quote_not_configured" in readiness["blocking_reasons"]
    assert "x402_exact_upfront_disabled" in readiness["blocking_reasons"]
    assert "cdp_api_key_id_missing" in readiness["blocking_reasons"]
    assert "cdp_api_key_secret_missing" in readiness["blocking_reasons"]
    assert "real_money_execution_disabled" in readiness["blocking_reasons"]
    assert readiness["scheme"] == "exact"
    assert readiness["payment_flow"] == "upfront"
    assert readiness["asset_transfer_method"] == "eip3009"

    _configure(monkeypatch, real_money=True)
    ready = exact_upfront_readiness()
    assert ready["launch_ready"] is True
    assert ready["activation_ready_except_master_gate"] is True
    assert ready["blocking_reasons"] == []
    assert ready["facilitator_credentials_locally_valid"] is True
    assert ready["pay_to_address_configured"] is True
    assert ready["asset_code"] == "USDC"
    required = build_exact_payment_required()
    accepted = required["accepts"][0]
    assert accepted["scheme"] == "exact"
    assert accepted["network"] == "eip155:8453"
    assert accepted["amount"] == "1250000"
    assert accepted["extra"] == {
        "name": "USD Coin",
        "version": "2",
        "assetTransferMethod": "eip3009",
        "paymentFlow": "upfront",
    }

    monkeypatch.setenv(ASSET_TRANSFER_METHOD_ENV, "permit2")
    assert exact_upfront_readiness()["payment_offer_configured"] is False
    assert exact_upfront_readiness()["launch_ready"] is False
    assert "asset_transfer_method_not_eip3009" in exact_upfront_readiness()["blocking_reasons"]


def test_readiness_distinguishes_invalid_pay_to_and_invalid_credentials(monkeypatch):
    _configure(monkeypatch, real_money=False)
    monkeypatch.setenv(PAY_TO_ENV, "not-an-address")
    monkeypatch.setenv("CDP_API_KEY_SECRET", "present-but-invalid")

    readiness = exact_upfront_readiness()

    assert readiness["pay_to_address_configured"] is False
    assert readiness["facilitator_credentials_configured"] is True
    assert readiness["facilitator_credentials_locally_valid"] is False
    assert "pay_to_address_invalid" in readiness["blocking_reasons"]
    assert "cdp_api_key_secret_invalid" in readiness["blocking_reasons"]
    assert readiness["launch_ready"] is False


def test_disabled_real_money_gate_returns_503_without_preparing_or_creating_membership(monkeypatch):
    _configure(monkeypatch, real_money=False)
    calls = _mock_plan(monkeypatch)
    with SessionLocal() as db:
        agents_before = db.scalar(select(func.count()).select_from(models.Agent)) or 0
    response = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "commercial_payment_not_activated"
    assert calls == []
    with SessionLocal() as db:
        assert (db.scalar(select(func.count()).select_from(RouteIntelligencePurchase)) or 0) == 0
        assert (db.scalar(select(func.count()).select_from(models.Agent)) or 0) == agents_before


def test_unpaid_request_prepares_but_does_not_reveal_result_or_create_membership(monkeypatch):
    _configure(monkeypatch)
    calls = _mock_plan(monkeypatch)
    with SessionLocal() as db:
        agents_before = db.scalar(select(func.count()).select_from(models.Agent)) or 0
    response = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert response.status_code == 402
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["scheme"] == "exact" and body["payment_flow"] == "upfront"
    assert body["aion_membership_required"] is False
    assert "result" not in body and "selected_provider" not in response.text
    assert body["prepared_result_digest"].startswith("sha256:")
    assert "PAYMENT-REQUIRED" in response.headers
    required = json.loads(base64.b64decode(response.headers["PAYMENT-REQUIRED"]))
    accepted = required["accepts"][0]
    assert accepted["extra"]["paymentFlow"] == "upfront"
    assert accepted["extra"]["aionPurchaseId"] == body["purchase_id"]
    assert accepted["extra"]["aionPreparedResultDigest"] == body["prepared_result_digest"]
    assert calls == [(0, "research")]
    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        assert row is not None and row.state == "prepared"
        assert row.payment_payload_digest is None
        assert (db.scalar(select(func.count()).select_from(models.Agent)) or 0) == agents_before


def test_settlement_releases_frozen_result_once_and_replay_returns_same_entitlement(monkeypatch):
    _configure(monkeypatch)
    _mock_plan(monkeypatch)
    settlement_calls = []

    def settle(payload, requirements):
        settlement_calls.append((payload, requirements))
        return _settled()

    monkeypatch.setattr(route_intelligence_purchase, "settle_exact_upfront", settle)
    unsigned = client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    )
    assert unsigned.status_code == 402
    signature = _payment_header()

    paid = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": signature},
    )
    assert paid.status_code == 200
    data = paid.json()
    assert data["state"] == "entitled"
    assert data["result"] == _route_result("research")
    assert data["aion_membership_created"] is False
    assert data["commercial_proof_created"] is False
    assert data["idempotent_replay"] is False
    assert "PAYMENT-RESPONSE" in paid.headers
    assert len(settlement_calls) == 1

    replay = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": signature},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["prepared_result_digest"] == data["prepared_result_digest"]
    assert len(settlement_calls) == 1

    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        serialized = json.dumps({
            "digest": row.payment_payload_digest,
            "transaction": row.transaction_id,
            "payer": row.payer,
            "failure": row.failure_detail,
        })
        assert row.state == "entitled"
        assert signature not in serialized
        assert row.payment_payload_digest.startswith("sha256:")
        assert row.transaction_id == "0x" + "4" * 64
        assert row.accounting_evidence == {
            "schema": "first_sat_accounting_v1",
            "payment_method": "x402_exact_upfront",
            "currency": "USDC",
            "quoted_gross_revenue": "1.25",
            "quoted_atomic_amount": "1250000",
            "settled_atomic_amount": "1250000",
            "known_provider_cost": "0",
            "actual_payment_cost": None,
            "actual_aion_operating_cost": None,
            "configured_payment_fee_allowance": "0.1",
            "budgeted_contribution_after_fee_allowance": "1.15",
            "budgeted_margin_bps_after_fee_allowance": 9200,
            "fee_allowance_is_not_observed_cost": True,
            "settled_atomic_amount_source": "facilitator_reported",
            "exact_contribution_margin_available": False,
            "unknown_cost_reasons": [
                "aion_operating_cost_not_metered",
                "facilitator_settlement_contract_has_no_payment_fee_field",
            ],
            "settlement_recorded": True,
        }


def test_same_payment_identity_cannot_fund_a_different_need(monkeypatch):
    _configure(monkeypatch)
    _mock_plan(monkeypatch)
    monkeypatch.setattr(
        route_intelligence_purchase, "settle_exact_upfront", lambda payload, requirements: _settled()
    )
    assert client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    ).status_code == 402
    signature = _payment_header()
    assert client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": signature},
    ).status_code == 200

    assert client.post(
        "/commercial/route-intelligence/purchase", json={"need": "translation"}
    ).status_code == 402
    conflict = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "translation"},
        headers={"PAYMENT-SIGNATURE": signature},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "payment_request_binding_mismatch"
    assert conflict.json()["result_released"] is False


def test_pending_settlement_releases_nothing_and_is_never_auto_retried(monkeypatch):
    _configure(monkeypatch)
    _mock_plan(monkeypatch)
    calls = []

    def pending(payload, requirements):
        calls.append(1)
        return {
            "outcome": "pending",
            "code": "settlement_pending",
            "transaction": "0x" + "5" * 64,
            "network": "eip155:8453",
            "payer": "0x" + "3" * 40,
            "detail": "confirmation unknown",
            "response": {
                "success": False,
                "errorReason": "settlement_pending",
                "transaction": "0x" + "5" * 64,
                "network": "eip155:8453",
            },
        }

    monkeypatch.setattr(route_intelligence_purchase, "settle_exact_upfront", pending)
    assert client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    ).status_code == 402
    signature = _payment_header(signature_byte="b")
    first = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": signature},
    )
    assert first.status_code == 503
    assert first.json()["code"] == "settlement_pending"
    assert first.json()["result_released"] is False
    assert len(calls) == 1

    retry = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": signature},
    )
    assert retry.status_code == 409
    assert retry.json()["code"] == "payment_settlement_not_retryable"
    assert len(calls) == 1
    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        assert row.state == "settlement_pending"
        assert row.prepared_result == _route_result("research")
        assert row.accounting_evidence["settlement_recorded"] is False
        assert row.accounting_evidence["settled_atomic_amount"] is None


def test_settlement_without_reported_amount_keeps_observed_amount_unknown(monkeypatch):
    _configure(monkeypatch)
    _mock_plan(monkeypatch)
    settlement = _settled()
    del settlement["response"]["amount"]
    monkeypatch.setattr(
        route_intelligence_purchase,
        "settle_exact_upfront",
        lambda payload, requirements: settlement,
    )
    assert client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    ).status_code == 402

    paid = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": _payment_header()},
    )

    assert paid.status_code == 200
    payment_response = json.loads(base64.b64decode(paid.headers["PAYMENT-RESPONSE"]))
    assert "amount" not in payment_response
    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        assert row.accounting_evidence["settlement_recorded"] is True
        assert row.accounting_evidence["settled_atomic_amount"] is None
        assert row.accounting_evidence["settled_atomic_amount_source"] == "not_reported"


def test_malformed_or_mismatched_signed_payment_never_contacts_facilitator(monkeypatch):
    _configure(monkeypatch)
    _mock_plan(monkeypatch)
    calls = []
    monkeypatch.setattr(
        route_intelligence_purchase,
        "settle_exact_upfront",
        lambda payload, requirements: calls.append(1),
    )
    assert client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    ).status_code == 402

    malformed = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": "not-base64"},
    )
    assert malformed.status_code == 400
    assert calls == []

    payload = json.loads(base64.b64decode(_payment_header()))
    payload["accepted"]["amount"] = "1"
    mismatched = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    response = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={"PAYMENT-SIGNATURE": mismatched},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "payment_requirement_mismatch"
    assert calls == []