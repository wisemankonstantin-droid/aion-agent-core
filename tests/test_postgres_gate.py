"""Real PostgreSQL lock observation; opt-in only for disposable CI service."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text, select, func, event
from app import models, schemas
from app.db import engine, SessionLocal
from app.services import joining
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
