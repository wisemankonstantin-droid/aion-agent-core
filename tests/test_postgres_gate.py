"""PostgreSQL gate shim preserving the accepted suite with two corrected fixtures.

The original candidate suite is kept byte-for-byte in postgres_gate_legacy.py.
Only two Ambassador transport stubs are replaced so they satisfy the current
correlated A2A response contract instead of returning an empty JSON-RPC result.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


_legacy_path = Path(__file__).with_name("postgres_gate_legacy.py")
_spec = importlib.util.spec_from_file_location("_aion_postgres_gate_legacy", _legacy_path)
_legacy = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_legacy)

pytestmark = _legacy.pytestmark

# Re-export the complete existing PostgreSQL gate. Pytest collects imported test
# functions from this module; the two stale fixtures are overridden below.
for _name in dir(_legacy):
    if _name.startswith("test_") or _name.startswith("Test"):
        globals()[_name] = getattr(_legacy, _name)


def _valid_a2a_response(*args, **kwargs):
    payload = kwargs.get("payload")
    assert isinstance(payload, dict)
    response = {
        "jsonrpc": "2.0",
        "id": payload["id"],
        "result": {
            "message": {
                "messageId": "pg-ambassador-reply",
                "role": "ROLE_AGENT",
                "parts": [{"text": "ack"}],
            }
        },
    }
    return _legacy.FetchResult(200, b"{}", None, 1), response


def test_postgres_concurrent_ambassador_contact_respects_campaign_limit(monkeypatch):
    token = _legacy.uuid.uuid4().hex
    campaign_db_id, _ = _legacy._pg_ambassador_campaign(token, contacts=1)
    target_ids = [
        _legacy._pg_ambassador_target(campaign_db_id, token + suffix)[1]
        for suffix in ("a", "b")
    ]
    with _legacy.SessionLocal() as db:
        targets = [
            (
                target_id,
                _legacy.ambassador.prepare_target(
                    db,
                    target_id=target_id,
                    public_base_url="https://aion.example",
                )["message"],
            )
            for target_id in target_ids
        ]
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    monkeypatch.setattr(_legacy.ambassador.safe_http, "fetch_json", _valid_a2a_response)
    barrier = _legacy.threading.Barrier(2)

    def worker(target):
        target_id, message = target
        with _legacy.SessionLocal() as db:
            barrier.wait(timeout=10)
            try:
                return _legacy.ambassador.send_contact(
                    db,
                    target_id=target_id,
                    message=message,
                    idempotency_key="pg-contact-" + target_id,
                    send=True,
                )["result_class"]
            except _legacy.ambassador.AmbassadorError as exc:
                return exc.code

    with _legacy.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, targets))
    assert sorted(results) == ["campaign_contact_limit_reached", "response_received"]
    with _legacy.SessionLocal() as db:
        assert db.scalar(
            _legacy.select(_legacy.func.count())
            .select_from(_legacy.models.AmbassadorContactAttempt)
            .join(_legacy.models.AmbassadorTarget)
            .where(_legacy.models.AmbassadorTarget.campaign_id == campaign_db_id)
        ) == 1


def test_postgres_concurrent_ambassador_idempotent_replay_posts_once(monkeypatch):
    token = _legacy.uuid.uuid4().hex
    campaign_db_id, _ = _legacy._pg_ambassador_campaign(token, contacts=1)
    _, target_id = _legacy._pg_ambassador_target(campaign_db_id, token)
    with _legacy.SessionLocal() as db:
        message = _legacy.ambassador.prepare_target(
            db,
            target_id=target_id,
            public_base_url="https://aion.example",
        )["message"]
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    calls = []
    calls_lock = _legacy.threading.Lock()

    def respond(*args, **kwargs):
        with calls_lock:
            calls.append(1)
        return _valid_a2a_response(*args, **kwargs)

    monkeypatch.setattr(_legacy.ambassador.safe_http, "fetch_json", respond)
    barrier = _legacy.threading.Barrier(2)

    def worker():
        with _legacy.SessionLocal() as db:
            barrier.wait(timeout=10)
            return _legacy.ambassador.send_contact(
                db,
                target_id=target_id,
                message=message,
                idempotency_key="pg-replay-" + token,
                send=True,
            )

    with _legacy.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert len(calls) == 1
    assert sorted(result["idempotent_replay"] for result in results) == [False, True]
    with _legacy.SessionLocal() as db:
        target_db_id = db.scalar(
            _legacy.select(_legacy.models.AmbassadorTarget.id).where(
                _legacy.models.AmbassadorTarget.target_id == target_id
            )
        )
        assert db.scalar(
            _legacy.select(_legacy.func.count())
            .select_from(_legacy.models.AmbassadorContactAttempt)
            .where(_legacy.models.AmbassadorContactAttempt.target_id == target_db_id)
        ) == 1
