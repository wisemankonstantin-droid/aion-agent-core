"""Real PostgreSQL lock observation; opt-in only for disposable CI service."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from sqlalchemy import text, select, func, event
from app import models, schemas
from app.db import engine, SessionLocal
from app.services import joining
from app.services.live_utility import RefreshPolicy, RefreshStrategy, SourceDefinition, SourceTier
from app.services.live_utility_engine import LiveUtilityEngine, RefreshStatus
from app.services.live_utility_sources import AdapterResponse
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
