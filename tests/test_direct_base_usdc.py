"""Buyer-funded direct Base USDC payment tests. No test contacts Base or moves money."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import app
from app.payment_models import RouteIntelligencePurchase
from app.services import commercial_router, economic_kernel, route_intelligence_purchase
from app.services.direct_base_usdc import (
    BASE_USDC_ADDRESS,
    DIRECT_ENABLE_ENV,
    ERC20_TRANSFER_TOPIC0,
    direct_base_usdc_readiness,
    verify_direct_base_usdc_transfer,
)
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
)
from app.services.x402_payment_offer import (
    ASSET_CODE_ENV,
    ASSET_DECIMALS_ENV,
    ASSET_ENV,
    NETWORK_ENV,
    PAY_TO_ENV,
)


client = TestClient(app)
PAY_TO = "0x" + "2" * 40
PAYER = "0x" + "3" * 40
TX_HASH = "0x" + "4" * 64
BLOCK_HASH = "0x" + "5" * 64
AMOUNT = "1250000"


@pytest.fixture(autouse=True)
def isolate_direct_payment(monkeypatch):
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()
    for name in (
        DIRECT_ENABLE_ENV,
        QUOTE_ENABLE_ENV,
        CURRENCY_ENV,
        PRICE_ENV,
        MAX_PAYMENT_FEE_ENV,
        NETWORK_ENV,
        ASSET_ENV,
        ASSET_CODE_ENV,
        ASSET_DECIMALS_ENV,
        PAY_TO_ENV,
        "AION_REAL_MONEY_EXECUTION_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
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
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0")
    assert register_paid_route_intelligence_profile() is True
    monkeypatch.setenv(DIRECT_ENABLE_ENV, "1")
    monkeypatch.setenv(NETWORK_ENV, "eip155:8453")
    monkeypatch.setenv(ASSET_ENV, BASE_USDC_ADDRESS)
    monkeypatch.setenv(ASSET_CODE_ENV, "USDC")
    monkeypatch.setenv(ASSET_DECIMALS_ENV, "6")
    monkeypatch.setenv(PAY_TO_ENV, PAY_TO)
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
    def plan(db, *, requester_agent_id, payload):
        assert requester_agent_id == 0
        return _route_result(payload.need)

    monkeypatch.setattr(commercial_router, "plan_commercial_route", plan)


def _topic(address: str) -> str:
    return "0x" + "0" * 24 + address[2:].lower()


def _receipt(*, amount=AMOUNT, token=BASE_USDC_ADDRESS, recipient=PAY_TO):
    return {
        "transactionHash": TX_HASH,
        "status": "0x1",
        "blockNumber": "0x64",
        "blockHash": BLOCK_HASH,
        "logs": [
            {
                "address": token,
                "topics": [
                    ERC20_TRANSFER_TOPIC0,
                    _topic(PAYER),
                    _topic(recipient),
                ],
                "data": "0x" + hex(int(amount))[2:].zfill(64),
            }
        ],
    }


def _rpc_sequence(monkeypatch, *, receipt=None, safe_number="0x64", timestamp=None):
    if receipt is None:
        receipt = _receipt()
    if timestamp is None:
        timestamp = int(datetime.now(timezone.utc).timestamp())
    responses = iter(
        [
            ("ok", "0x2105"),
            ("ok", receipt),
            ("ok", {"number": safe_number}),
            (
                "ok",
                {
                    "hash": BLOCK_HASH,
                    "number": "0x64",
                    "timestamp": hex(timestamp),
                },
            ),
        ]
    )
    monkeypatch.setattr(
        "app.services.direct_base_usdc._rpc",
        lambda method, params: next(responses),
    )


def test_direct_readiness_requires_no_facilitator_credentials(monkeypatch):
    _configure(monkeypatch, real_money=False)
    readiness = direct_base_usdc_readiness()

    assert readiness["payment_offer_configured"] is True
    assert readiness["activation_ready_except_master_gate"] is True
    assert readiness["launch_ready"] is False
    assert readiness["buyer_pays_gas"] is True
    assert readiness["aion_pays_gas"] is False
    assert readiness["facilitator_required"] is False
    assert readiness["facilitator_credentials_required"] is False
    assert readiness["blocking_reasons"] == ["real_money_execution_disabled"]


def test_verifier_accepts_exact_safe_native_usdc_transfer(monkeypatch):
    now = datetime.now(timezone.utc)
    _rpc_sequence(monkeypatch, timestamp=int(now.timestamp()))

    result = verify_direct_base_usdc_transfer(
        TX_HASH,
        expected_asset=BASE_USDC_ADDRESS,
        expected_pay_to=PAY_TO,
        expected_atomic_amount=AMOUNT,
        not_before=now - timedelta(seconds=5),
        not_after=now + timedelta(minutes=10),
    )

    assert result["outcome"] == "settled"
    assert result["payer"] == PAYER
    assert result["amount"] == AMOUNT
    assert result["finality"] == "safe"
    assert result["buyer_paid_gas"] is True
    assert result["aion_broadcast_transaction"] is False


def test_verifier_rejects_wrong_amount(monkeypatch):
    now = datetime.now(timezone.utc)
    _rpc_sequence(monkeypatch, receipt=_receipt(amount="1249999"), timestamp=int(now.timestamp()))

    result = verify_direct_base_usdc_transfer(
        TX_HASH,
        expected_asset=BASE_USDC_ADDRESS,
        expected_pay_to=PAY_TO,
        expected_atomic_amount=AMOUNT,
        not_before=now - timedelta(seconds=5),
        not_after=now + timedelta(minutes=10),
    )
    assert result == {"outcome": "rejected", "code": "payment_amount_mismatch"}


def test_verifier_rejects_wrong_token_or_recipient(monkeypatch):
    now = datetime.now(timezone.utc)
    _rpc_sequence(
        monkeypatch,
        receipt=_receipt(token="0x" + "9" * 40),
        timestamp=int(now.timestamp()),
    )
    result = verify_direct_base_usdc_transfer(
        TX_HASH,
        expected_asset=BASE_USDC_ADDRESS,
        expected_pay_to=PAY_TO,
        expected_atomic_amount=AMOUNT,
        not_before=now - timedelta(seconds=5),
        not_after=now + timedelta(minutes=10),
    )
    assert result == {
        "outcome": "rejected",
        "code": "required_usdc_transfer_not_found",
    }


def test_verifier_waits_until_payment_is_safe(monkeypatch):
    now = datetime.now(timezone.utc)
    responses = iter(
        [
            ("ok", "0x2105"),
            ("ok", _receipt()),
            ("ok", {"number": "0x63"}),
        ]
    )
    monkeypatch.setattr(
        "app.services.direct_base_usdc._rpc",
        lambda method, params: next(responses),
    )
    result = verify_direct_base_usdc_transfer(
        TX_HASH,
        expected_asset=BASE_USDC_ADDRESS,
        expected_pay_to=PAY_TO,
        expected_atomic_amount=AMOUNT,
        not_before=now - timedelta(seconds=5),
        not_after=now + timedelta(minutes=10),
    )
    assert result == {"outcome": "pending", "code": "payment_not_safe_yet"}


def test_verifier_rejects_historical_payment_before_purchase(monkeypatch):
    now = datetime.now(timezone.utc)
    _rpc_sequence(monkeypatch, timestamp=int((now - timedelta(minutes=5)).timestamp()))
    result = verify_direct_base_usdc_transfer(
        TX_HASH,
        expected_asset=BASE_USDC_ADDRESS,
        expected_pay_to=PAY_TO,
        expected_atomic_amount=AMOUNT,
        not_before=now,
        not_after=now + timedelta(minutes=10),
    )
    assert result == {"outcome": "rejected", "code": "payment_predates_purchase"}


def test_direct_purchase_releases_once_and_records_zero_aion_payment_cost(monkeypatch):
    _configure(monkeypatch, real_money=True)
    _mock_plan(monkeypatch)

    prepared = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert prepared.status_code == 402
    body = prepared.json()
    assert body["payment_method"] == "direct_base_usdc_transfer"
    assert body["buyer_pays_gas"] is True
    assert body["facilitator_required"] is False
    purchase_id = body["purchase_id"]

    calls = []

    def settled(*args, **kwargs):
        calls.append(1)
        return {
            "outcome": "settled",
            "transaction": TX_HASH,
            "network": "eip155:8453",
            "payer": PAYER,
            "amount": AMOUNT,
            "finality": "safe",
            "response": {
                "transaction": TX_HASH,
                "network": "eip155:8453",
                "payer": PAYER,
                "amount": AMOUNT,
                "finality": "safe",
            },
        }

    monkeypatch.setattr(
        route_intelligence_purchase,
        "verify_direct_base_usdc_transfer",
        settled,
    )

    paid = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={
            "X-AION-PURCHASE-ID": purchase_id,
            "X-AION-PAYMENT-TX": TX_HASH,
        },
    )
    assert paid.status_code == 200
    data = paid.json()
    assert data["state"] == "entitled"
    assert data["payment"]["method"] == "direct_base_usdc_transfer"
    assert data["payment"]["transaction"] == TX_HASH
    assert data["accounting"]["actual_payment_cost"] == "0"
    assert data["accounting"]["buyer_paid_gas"] is True
    assert data["accounting"]["settled_atomic_amount_source"] == (
        "onchain_base_usdc_transfer_event"
    )
    assert len(calls) == 1

    replay = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={
            "X-AION-PURCHASE-ID": purchase_id,
            "X-AION-PAYMENT-TX": TX_HASH,
        },
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert len(calls) == 1


def test_pending_direct_payment_can_be_reverified_without_second_payment(monkeypatch):
    _configure(monkeypatch, real_money=True)
    _mock_plan(monkeypatch)

    prepared = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    purchase_id = prepared.json()["purchase_id"]
    outcomes = iter(
        [
            {"outcome": "pending", "code": "payment_not_safe_yet"},
            {
                "outcome": "settled",
                "transaction": TX_HASH,
                "network": "eip155:8453",
                "payer": PAYER,
                "amount": AMOUNT,
                "finality": "safe",
                "response": {
                    "transaction": TX_HASH,
                    "payer": PAYER,
                    "amount": AMOUNT,
                    "finality": "safe",
                },
            },
        ]
    )
    monkeypatch.setattr(
        route_intelligence_purchase,
        "verify_direct_base_usdc_transfer",
        lambda *args, **kwargs: next(outcomes),
    )
    headers = {
        "X-AION-PURCHASE-ID": purchase_id,
        "X-AION-PAYMENT-TX": TX_HASH,
    }

    first = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers=headers,
    )
    assert first.status_code == 503
    assert first.json()["code"] == "payment_not_safe_yet"

    second = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["state"] == "entitled"


def test_same_direct_transaction_cannot_buy_two_results(monkeypatch):
    _configure(monkeypatch, real_money=True)
    _mock_plan(monkeypatch)
    monkeypatch.setattr(
        route_intelligence_purchase,
        "verify_direct_base_usdc_transfer",
        lambda *args, **kwargs: {
            "outcome": "settled",
            "transaction": TX_HASH,
            "network": "eip155:8453",
            "payer": PAYER,
            "amount": AMOUNT,
            "finality": "safe",
            "response": {"transaction": TX_HASH, "payer": PAYER, "amount": AMOUNT},
        },
    )

    first = client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    )
    first_id = first.json()["purchase_id"]
    assert client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers={
            "X-AION-PURCHASE-ID": first_id,
            "X-AION-PAYMENT-TX": TX_HASH,
        },
    ).status_code == 200

    second = client.post(
        "/commercial/route-intelligence/purchase", json={"need": "translation"}
    )
    second_id = second.json()["purchase_id"]
    conflict = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "translation"},
        headers={
            "X-AION-PURCHASE-ID": second_id,
            "X-AION-PAYMENT-TX": TX_HASH,
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "payment_replay_conflict"


def test_real_money_off_prepares_nothing(monkeypatch):
    _configure(monkeypatch, real_money=False)
    _mock_plan(monkeypatch)

    response = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert response.status_code == 503
    assert response.json()["code"] == "commercial_payment_not_activated"
    assert response.json()["blocking_reasons"] == ["real_money_execution_disabled"]
    with SessionLocal() as db:
        assert db.scalar(select(RouteIntelligencePurchase)) is None
