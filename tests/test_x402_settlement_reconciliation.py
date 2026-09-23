"""Recovery proofs for pending/ambiguous exact-upfront purchases.

All chain responses are deterministic fixtures. No test contacts a facilitator,
submits PAYMENT-SIGNATURE to reconciliation, or moves money.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import SessionLocal
from app.main import app
from app.payment_models import RouteIntelligencePurchase
from app.services import settlement_reconciliation
from app.services.paid_route_intelligence import ROUTE_INTELLIGENCE_SKU
from app.services.safe_http import FetchResult


client = TestClient(app)
TX = "0x" + "4" * 64
ASSET = "0x" + "1" * 40
PAY_TO = "0x" + "2" * 40
PAYER = "0x" + "3" * 40
AMOUNT = "1250000"


@pytest.fixture(autouse=True)
def isolate_reconciliation_rows():
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()


def _row(*, state="settlement_pending", payer=PAYER) -> str:
    now = datetime.now(timezone.utc)
    purchase_id = str(uuid.uuid4())
    row = RouteIntelligencePurchase(
        purchase_id=purchase_id,
        product_sku=ROUTE_INTELLIGENCE_SKU,
        request_digest="sha256:" + "a" * 64,
        request_evidence={"need": "research"},
        result_digest="sha256:" + "b" * 64,
        prepared_result={"secret_result": "must-not-leak-from-status"},
        quote_currency="USDC",
        quote_amount="1.25",
        network="eip155:8453",
        asset=ASSET,
        asset_code="USDC",
        pay_to=PAY_TO,
        atomic_amount=AMOUNT,
        payment_requirements_digest="sha256:" + "c" * 64,
        state=state,
        payment_payload_digest="sha256:" + "d" * 64,
        transaction_id=TX,
        payer=payer,
        settlement_response_digest="sha256:" + "e" * 64,
        failure_code="settlement_pending" if state == "settlement_pending" else "settlement_ambiguous",
        failure_detail="fixture uncertainty",
        prepared_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=14),
        updated_at=now,
    )
    with SessionLocal() as db:
        db.add(row)
        db.commit()
    return purchase_id


def _topic_address(address: str) -> str:
    return "0x" + "0" * 24 + address[2:].lower()


def _receipt(*, status="0x1", payer=PAYER, pay_to=PAY_TO, amount=AMOUNT):
    return {
        "transactionHash": TX,
        "blockNumber": "0x64",
        "blockHash": "0x" + "5" * 64,
        "status": status,
        "logs": [
            {
                "address": ASSET,
                "topics": [
                    settlement_reconciliation._TRANSFER_TOPIC,
                    _topic_address(payer),
                    _topic_address(pay_to),
                ],
                "data": "0x" + format(int(amount), "064x"),
                "logIndex": "0x0",
            }
        ],
    }


def _rpc_fixture(monkeypatch, *, receipt=None, chain_id="0x2105", finalized="0x70"):
    calls = []

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, connection_factory=None):
        assert method == "POST"
        assert url == "https://mainnet.base.org"
        rpc_method = payload["method"]
        calls.append(rpc_method)
        if rpc_method == "eth_chainId":
            value = chain_id
        elif rpc_method == "eth_getTransactionReceipt":
            assert payload["params"] == [TX]
            value = receipt
        elif rpc_method == "eth_getBlockByNumber":
            assert payload["params"] == ["finalized", False]
            value = {"number": finalized}
        else:
            raise AssertionError(rpc_method)
        return FetchResult(200, b"{}", None, 1), {
            "jsonrpc": "2.0",
            "id": 1,
            "result": value,
        }

    monkeypatch.setattr(settlement_reconciliation, "fetch_json", fake_fetch_json)
    return calls


def test_status_is_read_only_and_never_releases_prepared_result():
    purchase_id = _row()
    response = client.get(f"/commercial/route-intelligence/purchases/{purchase_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "settlement_pending"
    assert body["result_released"] is False
    assert body["result_available_via_idempotent_signed_purchase_replay"] is False
    assert "result" not in body
    assert "secret_result" not in response.text
    assert body["truth_boundaries"]["facilitator_settlement_retried_by_reconciliation"] is False

    with SessionLocal() as db:
        row = db.scalar(
            select(RouteIntelligencePurchase).where(
                RouteIntelligencePurchase.purchase_id == purchase_id
            )
        )
        assert row.state == "settlement_pending"
        assert row.settlement_response_digest == "sha256:" + "e" * 64


def test_reconciliation_rejects_payment_signature_without_any_rpc(monkeypatch):
    purchase_id = _row()
    monkeypatch.setattr(
        settlement_reconciliation,
        "fetch_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RPC must not run")),
    )
    response = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile",
        headers={"PAYMENT-SIGNATURE": "must-not-be-accepted"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "reconciliation_payment_signature_rejected"
    assert response.json()["result_released"] is False


def test_finalized_exact_transfer_promotes_pending_to_entitled_once(monkeypatch):
    purchase_id = _row()
    calls = _rpc_fixture(monkeypatch, receipt=_receipt())

    response = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "entitled"
    assert body["reconciliation"] == {"outcome": "settled", "idempotent": False}
    assert body["result_released"] is False
    assert body["result_available_via_idempotent_signed_purchase_replay"] is True
    assert calls == ["eth_chainId", "eth_getTransactionReceipt", "eth_getBlockByNumber"]

    with SessionLocal() as db:
        row = db.scalar(
            select(RouteIntelligencePurchase).where(
                RouteIntelligencePurchase.purchase_id == purchase_id
            )
        )
        assert row.state == "entitled"
        assert row.transaction_id == TX
        assert row.payer == PAYER
        assert row.entitled_at is not None
        assert row.failure_code is None
        assert row.settlement_response_digest.startswith("sha256:")
        assert row.settlement_response_digest != "sha256:" + "e" * 64

    monkeypatch.setattr(
        settlement_reconciliation,
        "fetch_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("terminal replay must not RPC")),
    )
    replay = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert replay.status_code == 200
    assert replay.json()["state"] == "entitled"
    assert replay.json()["reconciliation"] == {"outcome": "terminal", "idempotent": True}


def test_ambiguous_transaction_can_derive_payer_only_from_exact_finalized_transfer(monkeypatch):
    purchase_id = _row(state="settlement_ambiguous", payer=None)
    _rpc_fixture(monkeypatch, receipt=_receipt())
    response = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert response.status_code == 200
    assert response.json()["state"] == "entitled"
    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        assert row.payer == PAYER


def test_unmined_or_unfinalized_transaction_stays_uncertain(monkeypatch):
    purchase_id = _row()
    calls = _rpc_fixture(monkeypatch, receipt=None)
    response = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert response.status_code == 200
    assert response.json()["state"] == "settlement_pending"
    assert response.json()["reconciliation"] == {
        "outcome": "unresolved",
        "code": "transaction_not_mined",
    }
    assert calls == ["eth_chainId", "eth_getTransactionReceipt"]

    _rpc_fixture(monkeypatch, receipt=_receipt(), finalized="0x63")
    response = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert response.status_code == 200
    assert response.json()["state"] == "settlement_pending"
    assert response.json()["reconciliation"]["code"] == "transaction_not_finalized"


def test_finalized_revert_or_wrong_transfer_becomes_definite_failure(monkeypatch):
    purchase_id = _row()
    _rpc_fixture(monkeypatch, receipt=_receipt(status="0x0"))
    reverted = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert reverted.status_code == 200
    assert reverted.json()["state"] == "settlement_failed"
    assert reverted.json()["failure_code"] == "reconciliation_transaction_reverted"
    assert reverted.json()["result_released"] is False

    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()
    purchase_id = _row(state="settlement_ambiguous")
    _rpc_fixture(monkeypatch, receipt=_receipt(pay_to="0x" + "9" * 40))
    mismatch = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert mismatch.status_code == 200
    assert mismatch.json()["state"] == "settlement_failed"
    assert mismatch.json()["failure_code"] == "reconciliation_exact_transfer_not_proven"
    assert mismatch.json()["result_released"] is False


def test_wrong_rpc_chain_fails_closed_without_state_transition(monkeypatch):
    purchase_id = _row(state="settlement_ambiguous")
    calls = _rpc_fixture(monkeypatch, receipt=_receipt(), chain_id="0x1")
    response = client.post(
        f"/commercial/route-intelligence/purchases/{purchase_id}/reconcile"
    )
    assert response.status_code == 200
    assert response.json()["state"] == "settlement_ambiguous"
    assert response.json()["reconciliation"] == {
        "outcome": "unresolved",
        "code": "reconciliation_chain_mismatch",
    }
    assert calls == ["eth_chainId"]


@pytest.mark.skipif(
    os.getenv("AION_POSTGRES_GATE") != "1",
    reason="requires the disposable PostgreSQL release-gate database",
)
def test_postgres_parallel_reconciliation_is_idempotent(monkeypatch):
    """Two sessions may read the chain, but only one durable state transition wins."""
    purchase_id = _row(state="settlement_ambiguous")
    barrier = threading.Barrier(2)

    def resolved(row):
        barrier.wait(timeout=5)
        return {
            "outcome": "settled",
            "evidence": {
                "authority": "fixture-finalized-receipt",
                "network": row.network,
                "transaction": row.transaction_id,
                "block_number": "0x64",
                "block_hash": "0x" + "5" * 64,
                "finalized_block_number": "0x70",
                "asset": row.asset,
                "pay_to": row.pay_to,
                "atomic_amount": row.atomic_amount,
                "receipt_status": "0x1",
                "payer": PAYER,
                "transfer_log_index": "0x0",
            },
        }

    monkeypatch.setattr(
        settlement_reconciliation, "_resolve_finalized_chain_evidence", resolved
    )
    outcomes = []
    lock = threading.Lock()

    def worker():
        with SessionLocal() as db:
            value = settlement_reconciliation.reconcile_purchase(db, purchase_id)
        with lock:
            outcomes.append((value["state"], value["reconciliation"]["idempotent"]))

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert all(not thread.is_alive() for thread in threads)
    assert len(outcomes) == 2
    assert all(state == "entitled" for state, _ in outcomes)
    assert sorted(idempotent for _, idempotent in outcomes) == [False, True]

    with SessionLocal() as db:
        row = db.scalar(select(RouteIntelligencePurchase))
        assert row.state == "entitled"
        assert row.transaction_id == TX
        assert row.payer == PAYER
        assert row.entitled_at is not None
