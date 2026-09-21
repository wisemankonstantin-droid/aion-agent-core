"""Buyer-broadcast Base USDC EIP-3009 tests.

No test contacts Base or moves money. Fixtures model the exact calldata and
events AION must see before a prepared result can be released.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import app
from app.payment_models import RouteIntelligencePurchase
from app.services import commercial_router, economic_kernel, route_intelligence_purchase
from app.services.direct_base_usdc import (
    AUTHORIZATION_USED_TOPIC0,
    BASE_USDC_ADDRESS,
    DIRECT_ENABLE_ENV,
    DIRECT_PAYMENT_METHOD,
    ERC20_TRANSFER_TOPIC0,
    TRANSFER_WITH_AUTHORIZATION_SELECTOR,
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
BROADCASTER = PAYER
TX_HASH = "0x" + "4" * 64
BLOCK_HASH = "0x" + "5" * 64
NONCE = "0x" + "6" * 64
OTHER_NONCE = "0x" + "7" * 64
AMOUNT = "1250000"
VALID_AFTER = 1_700_000_000
VALID_BEFORE = 1_700_000_900
BLOCK_TIMESTAMP = 1_700_000_100


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


def _word_address(address: str) -> str:
    return "0" * 24 + address[2:].lower()


def _word_uint(value: int | str) -> str:
    return hex(int(value))[2:].zfill(64)


def _calldata(
    *,
    payer=PAYER,
    recipient=PAY_TO,
    amount=AMOUNT,
    valid_after=VALID_AFTER,
    valid_before=VALID_BEFORE,
    nonce=NONCE,
):
    words = [
        _word_address(payer),
        _word_address(recipient),
        _word_uint(amount),
        _word_uint(valid_after),
        _word_uint(valid_before),
        nonce[2:].lower(),
        _word_uint(27),
        "8" * 64,
        "9" * 64,
    ]
    return TRANSFER_WITH_AUTHORIZATION_SELECTOR + "".join(words)


def _transaction(*, calldata=None):
    return {
        "hash": TX_HASH,
        "from": BROADCASTER,
        "to": BASE_USDC_ADDRESS,
        "input": calldata or _calldata(),
    }


def _receipt(
    *,
    amount=AMOUNT,
    token=BASE_USDC_ADDRESS,
    recipient=PAY_TO,
    payer=PAYER,
    nonce=NONCE,
    include_authorization=True,
):
    logs = [
        {
            "address": token,
            "topics": [
                ERC20_TRANSFER_TOPIC0,
                _topic(payer),
                _topic(recipient),
            ],
            "data": "0x" + hex(int(amount))[2:].zfill(64),
        }
    ]
    if include_authorization:
        logs.append(
            {
                "address": token,
                "topics": [
                    AUTHORIZATION_USED_TOPIC0,
                    _topic(payer),
                    nonce,
                ],
                "data": "0x",
            }
        )
    return {
        "transactionHash": TX_HASH,
        "status": "0x1",
        "blockNumber": "0x64",
        "blockHash": BLOCK_HASH,
        "logs": logs,
    }


def _rpc_sequence(
    monkeypatch,
    *,
    transaction=None,
    receipt=None,
    safe_number="0x64",
    timestamp=BLOCK_TIMESTAMP,
):
    responses = iter(
        [
            ("ok", "0x2105"),
            ("ok", transaction or _transaction()),
            ("ok", receipt or _receipt()),
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


def _verify(**overrides):
    arguments = {
        "expected_asset": BASE_USDC_ADDRESS,
        "expected_pay_to": PAY_TO,
        "expected_atomic_amount": AMOUNT,
        "expected_authorization_nonce": NONCE,
        "expected_valid_after": VALID_AFTER,
        "expected_valid_before": VALID_BEFORE,
    }
    arguments.update(overrides)
    return verify_direct_base_usdc_transfer(TX_HASH, **arguments)


def test_direct_readiness_requires_no_facilitator_credentials(monkeypatch):
    _configure(monkeypatch, real_money=False)
    readiness = direct_base_usdc_readiness()

    assert readiness["payment_offer_configured"] is True
    assert readiness["activation_ready_except_master_gate"] is True
    assert readiness["launch_ready"] is False
    assert readiness["payment_method"] == DIRECT_PAYMENT_METHOD
    assert readiness["buyer_pays_gas"] is True
    assert readiness["aion_pays_gas"] is False
    assert readiness["aion_broadcasts_transaction"] is False
    assert readiness["facilitator_required"] is False
    assert readiness["facilitator_credentials_required"] is False
    assert readiness["purchase_bound_nonce_required"] is True
    assert readiness["blocking_reasons"] == ["real_money_execution_disabled"]


def test_verifier_accepts_exact_safe_purchase_bound_eip3009_payment(monkeypatch):
    _rpc_sequence(monkeypatch)

    result = _verify()

    assert result["outcome"] == "settled"
    assert result["payer"] == PAYER
    assert result["amount"] == AMOUNT
    assert result["authorization_nonce"] == NONCE
    assert result["finality"] == "safe"
    assert result["aion_broadcast_transaction"] is False
    assert result["facilitator_used"] is False


def test_verifier_rejects_nonce_from_another_purchase(monkeypatch):
    _rpc_sequence(
        monkeypatch,
        transaction=_transaction(calldata=_calldata(nonce=OTHER_NONCE)),
        receipt=_receipt(nonce=OTHER_NONCE),
    )

    assert _verify() == {
        "outcome": "rejected",
        "code": "payment_purchase_nonce_mismatch",
    }


def test_verifier_rejects_wrong_amount_in_signed_authorization(monkeypatch):
    _rpc_sequence(
        monkeypatch,
        transaction=_transaction(calldata=_calldata(amount="1249999")),
        receipt=_receipt(amount="1249999"),
    )

    assert _verify() == {
        "outcome": "rejected",
        "code": "payment_amount_mismatch",
    }


def test_verifier_requires_authorization_used_event(monkeypatch):
    _rpc_sequence(
        monkeypatch,
        receipt=_receipt(include_authorization=False),
    )

    assert _verify() == {
        "outcome": "rejected",
        "code": "required_authorization_used_event_not_found",
    }


def test_verifier_waits_until_payment_is_safe(monkeypatch):
    _rpc_sequence(monkeypatch, safe_number="0x63")

    assert _verify() == {
        "outcome": "pending",
        "code": "payment_not_safe_yet",
    }


def test_two_purchases_publish_different_signed_nonces(monkeypatch):
    _configure(monkeypatch, real_money=True)
    _mock_plan(monkeypatch)

    first = client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    )
    second = client.post(
        "/commercial/route-intelligence/purchase", json={"need": "translation"}
    )

    assert first.status_code == second.status_code == 402
    first_nonce = first.json()["payment_instructions"]["authorization"]["message"]["nonce"]
    second_nonce = second.json()["payment_instructions"]["authorization"]["message"]["nonce"]
    assert first_nonce.startswith("0x") and len(first_nonce) == 66
    assert second_nonce.startswith("0x") and len(second_nonce) == 66
    assert first_nonce != second_nonce


def _settled_for(requirements):
    return {
        "outcome": "settled",
        "transaction": TX_HASH,
        "network": "eip155:8453",
        "payer": PAYER,
        "broadcaster": BROADCASTER,
        "amount": AMOUNT,
        "authorization_nonce": requirements["authorization"]["message"]["nonce"],
        "finality": "safe",
        "response": {
            "transaction": TX_HASH,
            "payer": PAYER,
            "amount": AMOUNT,
            "authorization_nonce": requirements["authorization"]["message"]["nonce"],
            "finality": "safe",
        },
    }


def test_direct_purchase_releases_once_and_records_zero_aion_payment_cost(monkeypatch):
    _configure(monkeypatch, real_money=True)
    _mock_plan(monkeypatch)

    prepared = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
    )
    assert prepared.status_code == 402
    body = prepared.json()
    assert body["payment_method"] == DIRECT_PAYMENT_METHOD
    assert body["buyer_pays_gas"] is True
    assert body["facilitator_required"] is False
    assert body["payment_instructions"]["transfer_method"] == (
        "eip3009_transferWithAuthorization"
    )
    purchase_id = body["purchase_id"]
    nonce = body["payment_instructions"]["authorization"]["message"]["nonce"]

    calls = []

    def settled(*args, **kwargs):
        calls.append(kwargs)
        return {
            "outcome": "settled",
            "transaction": TX_HASH,
            "network": "eip155:8453",
            "payer": PAYER,
            "amount": AMOUNT,
            "authorization_nonce": kwargs["expected_authorization_nonce"],
            "finality": "safe",
            "response": {
                "transaction": TX_HASH,
                "payer": PAYER,
                "amount": AMOUNT,
                "authorization_nonce": kwargs["expected_authorization_nonce"],
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
    assert data["payment"]["method"] == DIRECT_PAYMENT_METHOD
    assert data["payment"]["transaction"] == TX_HASH
    assert data["accounting"]["actual_payment_cost"] == "0"
    assert data["accounting"]["aion_blockchain_gas_cost"] == "0"
    assert data["accounting"]["purchase_bound_authorization_nonce"] == nonce
    assert data["accounting"]["settled_atomic_amount_source"] == (
        "onchain_base_usdc_eip3009_transfer"
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


def test_bad_or_pending_proof_does_not_claim_transaction(monkeypatch):
    _configure(monkeypatch, real_money=True)
    _mock_plan(monkeypatch)

    prepared = client.post(
        "/commercial/route-intelligence/purchase", json={"need": "research"}
    )
    purchase_id = prepared.json()["purchase_id"]
    outcomes = iter(
        [
            {"outcome": "rejected", "code": "payment_purchase_nonce_mismatch"},
            {"outcome": "pending", "code": "payment_not_safe_yet"},
            {
                "outcome": "settled",
                "transaction": TX_HASH,
                "network": "eip155:8453",
                "payer": PAYER,
                "amount": AMOUNT,
                "authorization_nonce": prepared.json()["payment_instructions"][
                    "authorization"
                ]["message"]["nonce"],
                "finality": "safe",
                "response": {"transaction": TX_HASH, "payer": PAYER, "amount": AMOUNT},
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

    rejected = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers=headers,
    )
    assert rejected.status_code == 402
    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        assert row.state == "prepared"
        assert row.transaction_id is None
        assert row.payment_payload_digest is None

    pending = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers=headers,
    )
    assert pending.status_code == 503
    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        assert row.state == "prepared"
        assert row.transaction_id is None

    settled = client.post(
        "/commercial/route-intelligence/purchase",
        json={"need": "research"},
        headers=headers,
    )
    assert settled.status_code == 200
    assert settled.json()["state"] == "entitled"


def test_same_verified_transaction_cannot_buy_two_results(monkeypatch):
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
            "authorization_nonce": kwargs["expected_authorization_nonce"],
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
