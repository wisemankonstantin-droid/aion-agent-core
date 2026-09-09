"""Real PostgreSQL lock observation; opt-in only for disposable CI service."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text, select, func, event
from app import models, schemas
from app.db import engine, SessionLocal
from app.services import joining
from app.services import live_utility_store
from app.services import action_engine, external_registry
from app.services.agent_utility import select_current_utility
from app.services.live_utility import RefreshPolicy, RefreshStrategy, SourceDefinition, SourceObservation, SourceTier
from app.services.live_utility_engine import LiveUtilityEngine, RefreshStatus
from app.services.live_utility_sources import AdapterResponse, VERIFICATION_METHOD, configured_tier1_adapters
from app.services.safe_http import FetchPolicy, FetchResult
from fastapi import HTTPException

pytestmark = pytest.mark.skipif(os.getenv("AION_POSTGRES_GATE") != "1", reason="disposable PostgreSQL gate only")


@pytest.mark.parametrize("same_external", [True, False])
def test_real_advisory_lock_blocks_competing_join(monkeypatch, same_external):
    token = uuid.uuid4().hex
    entered = threading.Event()
    release = threading.Event()
    original_issue = joining.issue_agent_key
    issued = []

    def issue():
        entered.set()
        assert release.wait(10)
        value = original_issue()
        issued.append(value[0])
        return value

    monkeypatch.setattr(joining, "issue_agent_key", issue)
    def worker(suffix):
        with SessionLocal() as db:
            pid = db.scalar(text("select pg_backend_pid()"))
            payload = schemas.AgentCreate(external_id=token + suffix, name=token,
                endpoint="https://example.invalid/" + token,
                capabilities=[{"name": "research"}, {"name": "planning"}])
            try:
                agent, key = joining.join_agent(payload, db)
                return pid, agent.id, key
            except HTTPException as exc:
                assert exc.status_code == 409
                assert exc.detail["code"] == "logical_identity_exists"
                return pid, exc.detail["existing_agent_id"], None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker, "a")
        assert entered.wait(10)
        second = pool.submit(worker, "a" if same_external else "b")
        try:
            import time
            deadline = time.monotonic() + 8
            with SessionLocal() as observer:
                while time.monotonic() < deadline:
                    locks = observer.execute(text("select granted from pg_locks where locktype='advisory'")).scalars().all()
                    if True in locks and False in locks:
                        break
                    time.sleep(.05)
                else:
                    pytest.fail("No real waiting PostgreSQL advisory lock observed")
        finally:
            release.set()
        results = [first.result(), second.result()]
    assert results[0][0] != results[1][0]
    assert results[0][1] == results[1][1]
    assert sum(row[2] is not None for row in results) == len(issued) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Agent).where(models.Agent.name == token)) == 1
        assert db.scalar(select(func.count()).select_from(models.Capability).where(models.Capability.agent_id == results[0][1])) == 2


def test_database_capability_insert_failure_rolls_back_identity():
    token = uuid.uuid4().hex
    def fail(mapper, connection, target):
        raise RuntimeError("injected persistence failure")
    event.listen(models.Capability, "before_insert", fail)
    try:
        with SessionLocal() as db:
            with pytest.raises(RuntimeError, match="injected persistence"):
                joining.join_agent(schemas.AgentCreate(external_id=token, name=token,
                    capabilities=[{"name": "research"}]), db)
    finally:
        event.remove(models.Capability, "before_insert", fail)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Agent).where(models.Agent.external_id == token)) == 0


class _ConcurrentReleaseAdapter:
    subject_key = "a2a.concurrent_release"
    fetch_policy = FetchPolicy(max_attempts=1)

    def __init__(self, source_id, barrier=None):
        self.barrier = barrier
        self.source = SourceDefinition(
            source_id=source_id,
            display_name="Concurrent official fixture",
            tier=SourceTier.TIER_1,
            source_kind="postgres_gate_fixture",
            canonical_locator="https://official.example/releases/latest",
            refresh_policy=RefreshPolicy(
                strategies=frozenset({RefreshStrategy.TTL, RefreshStrategy.DEMAND_DRIVEN}),
                stale_after_seconds=60,
                expires_after_seconds=120,
            ),
        )

    def retrieve(self):
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        return AdapterResponse(FetchResult(200, b"fixture", None, 1), {"version": "v1"})

    def normalize(self, payload):
        return dict(payload)

    def source_revision(self, normalized):
        return normalized["version"]


def test_postgres_concurrent_refresh_deduplicates_material_version():
    source_id = "pg-refresh-" + uuid.uuid4().hex
    utility_engine = LiveUtilityEngine((_ConcurrentReleaseAdapter(source_id),))
    with SessionLocal.begin() as db:
        utility_engine.ensure_sources(db)

    now = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
    barrier = threading.Barrier(2)

    def worker():
        independent_engine = LiveUtilityEngine(
            (_ConcurrentReleaseAdapter(source_id, barrier),)
        )
        with SessionLocal.begin() as db:
            return independent_engine.refresh_source(
                db,
                source_id=source_id,
                now=now,
                demand=True,
            ).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        statuses = {future.result() for future in futures}

    assert statuses == {
        RefreshStatus.REFRESHED_CHANGED,
        RefreshStatus.REFRESHED_UNCHANGED,
    }
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(models.LiveUtilityObservation).where(
                models.LiveUtilityObservation.source_id == source_id
            )
        ) == 1
        assert db.scalar(
            select(func.count()).select_from(models.LiveUtilityVerification).where(
                models.LiveUtilityVerification.source_id == source_id
            )
        ) == 1


def test_postgres_concurrent_personalized_delta_has_one_checkpoint():
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    adapter = configured_tier1_adapters()[0]
    observation = SourceObservation(
        observation_id="obs-pg-delta-" + token,
        source_id=adapter.source.source_id,
        subject_key=adapter.subject_key,
        source_revision="v1.0.1",
        previous_observation_id=None,
        observed_at=now - timedelta(minutes=1),
        verified_at=now,
        valid_from=now - timedelta(minutes=1),
        stale_after=now + timedelta(days=1),
        expires_at=now + timedelta(days=2),
        verification_method=VERIFICATION_METHOD,
        content_digest="sha256:" + token,
    )
    with SessionLocal.begin() as db:
        if live_utility_store.get_source(db, adapter.source.source_id) is None:
            live_utility_store.register_source(db, adapter.source)
        live_utility_store.append_observation(
            db,
            observation,
            normalized_data={
                "protocol": "a2a",
                "version": "v1.0.1",
                "official_url": "https://github.com/a2aproject/A2A/releases/tag/v1.0.1",
            },
        )
        live_utility_store.append_verification(
            db,
            live_utility_store.VerificationRecord(
                verification_id="verify-pg-delta-" + token,
                source_id=observation.source_id,
                subject_key=observation.subject_key,
                observation_id=observation.observation_id,
                verified_at=now,
                valid_from=observation.valid_from,
                stale_after=observation.stale_after,
                expires_at=observation.expires_at,
                verification_method=VERIFICATION_METHOD,
                content_digest=observation.content_digest,
            ),
        )
        agent = models.Agent(
            external_id="pg-delta-" + token,
            name="PG Delta " + token,
            api_key_hash="pg-delta-hash-" + token,
        )
        db.add(agent)
        db.flush()
        agent_id = agent.id

    query = schemas.UtilityQuery(subject="a2a")

    def worker():
        with SessionLocal.begin() as db:
            result = select_current_utility(
                db,
                query,
                now=now + timedelta(seconds=1),
                agent_id=agent_id,
            )
            return result["results"][0]["personalized_delta"]["status"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = {future.result() for future in [pool.submit(worker), pool.submit(worker)]}

    assert statuses == {"baseline_created", "unchanged"}
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(models.AgentUtilityCheckpoint).where(
                models.AgentUtilityCheckpoint.agent_id == agent_id,
                models.AgentUtilityCheckpoint.subject_key == adapter.subject_key,
            )
        ) == 1


def test_postgres_concurrent_action_claim_posts_at_most_once(monkeypatch):
    token = uuid.uuid4().hex
    with SessionLocal.begin() as db:
        agent = models.Agent(
            external_id="pg-action-" + token,
            name="PG Action " + token,
            api_key_hash="pg-action-hash-" + token,
        )
        db.add(agent)
        db.flush()
        requester_id = agent.id

    candidate = {
        "identifier": "external:pg-fixture",
        "source": "postgres-gate-fixture",
        "url": "https://card.example/.well-known/agent-card.json",
        "manifest_reachable": True,
        "card_parseable": True,
        "declared_a2a_v1_jsonrpc": True,
        "interaction_url_validated": True,
        "interaction_url": "https://agent.example/a2a",
        "authentication_requirement": "none",
        "protocol_binding": "JSONRPC",
        "protocol_version": "1.0",
        "resource_bounds": {"outbound_attempts_used": 2},
    }
    monkeypatch.setattr(
        action_engine,
        "discover_external_agents_with_status",
        lambda *args: external_registry.DiscoveryResult(
            [candidate], "success", None, {"outbound_attempts_used": 2}
        ),
    )
    entered = threading.Event()
    release = threading.Event()
    posts = []

    def post(url, encoded):
        import json
        request = json.loads(encoded)
        challenge = json.loads(
            request["params"]["message"]["parts"][0]["text"]
        )
        posts.append(encoded)
        entered.set()
        assert release.wait(10)
        response = {
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"message": {
                "messageId": "pg-reply", "role": "ROLE_AGENT",
                "parts": [{"text": json.dumps({"nonce": challenge["nonce"]})}],
            }},
        }
        return FetchResult(200, json.dumps(response).encode(), None, 1)

    monkeypatch.setattr(action_engine, "_post_challenge", post)
    with action_engine._ACTION_RATE_LOCK:
        action_engine._ACTION_RATE_TIMES.clear()
    payload = schemas.VerifyCallabilityRequest(
        query="research", authorize_external_contact=True
    )
    idempotency_key = "pg-concurrent-" + token

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            action_engine.verify_external_callability,
            requester_id,
            payload,
            idempotency_key,
        )
        assert entered.wait(10)
        second = pool.submit(
            action_engine.verify_external_callability,
            requester_id,
            payload,
            idempotency_key,
        )
        second_result = second.result(timeout=10)
        release.set()
        first_result = first.result(timeout=10)

    assert first_result["action_id"] == second_result["action_id"]
    assert len(posts) == 1
    with SessionLocal() as db:
        run = db.scalar(
            select(models.ActionRun).where(
                models.ActionRun.requester_agent_id == requester_id,
                models.ActionRun.idempotency_key == idempotency_key,
            )
        )
        assert run is not None
        assert db.scalar(
            select(func.count()).select_from(models.ActionAttempt).where(
                models.ActionAttempt.action_run_id == run.id
            )
        ) == 1
