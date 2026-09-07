import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import models, schemas
from app.db import SessionLocal
from app.services import joining
from app.services.joining import join_agent


def _payload(external_id=None, *, name="Atomic Join", endpoint=None, capabilities=None):
    return schemas.AgentCreate(
        external_id=external_id or f"atomic-{uuid.uuid4().hex}",
        name=name,
        endpoint=endpoint,
        protocol="A2A" if endpoint else "REST",
        capabilities=capabilities or [{"name": "research"}, {"name": "planning"}],
    )


def _join_in_separate_session(payload, barrier):
    with SessionLocal() as db:
        # Open an independent database connection before both workers proceed.
        connection_id = id(db.connection().connection)
        barrier.wait(timeout=5)
        try:
            agent, key = join_agent(payload, db)
            return "created", agent.id, key, connection_id
        except HTTPException as exc:
            return "rejected", exc.status_code, exc.detail, connection_id


def test_successful_join_persists_identity_and_all_initial_capabilities():
    payload = _payload()
    with SessionLocal() as db:
        agent, key = join_agent(payload, db)
        agent_id = agent.id
        assert key.startswith("aion_")

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Agent).where(models.Agent.id == agent_id)) == 1
        assert db.scalar(select(func.count()).select_from(models.Capability).where(models.Capability.agent_id == agent_id)) == 2


def test_sequential_logical_duplicate_keeps_existing_contract():
    endpoint = f"https://example.invalid/{uuid.uuid4().hex}/agent-card.json"
    first = _payload(name="Canonical Identity", endpoint=endpoint)
    second = _payload(name="Canonical Identity", endpoint=endpoint)
    with SessionLocal() as db:
        created, _ = join_agent(first, db)
        created_id = created.id
        with pytest.raises(HTTPException) as exc_info:
            join_agent(second, db)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "logical_identity_exists"
    assert exc_info.value.detail["existing_agent_id"] == created_id


def test_exact_external_id_concurrent_joins_use_one_identity_and_one_credential(monkeypatch):
    external_id = f"atomic-race-{uuid.uuid4().hex}"
    payload = _payload(external_id)
    key_calls = []

    def issue_once():
        raw = f"aion_test_{uuid.uuid4().hex}"
        key_calls.append(raw)
        return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()

    monkeypatch.setattr(joining, "issue_agent_key", issue_once)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda item: _join_in_separate_session(item, barrier), [payload, payload]))

    created = [row for row in results if row[0] == "created"]
    rejected = [row for row in results if row[0] == "rejected"]
    assert len(created) == 1
    assert len(rejected) == 1
    assert rejected[0][1] == 409
    assert rejected[0][2]["code"] == "logical_identity_exists"
    assert len(key_calls) == 1
    assert len({row[3] for row in results}) == 2

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Agent).where(models.Agent.external_id == external_id)) == 1


def test_strong_logical_identity_concurrent_joins_use_one_identity_and_one_credential(monkeypatch):
    endpoint = f"https://example.invalid/{uuid.uuid4().hex}/agent-card.json"
    first = _payload(f"atomic-first-{uuid.uuid4().hex}", name="Durable Agent", endpoint=endpoint)
    second = _payload(f"atomic-second-{uuid.uuid4().hex}", name="Durable Agent", endpoint=endpoint)
    key_calls = []
    real_issue = joining.issue_agent_key

    def tracked_issue():
        value = real_issue()
        key_calls.append(value[0])
        return value

    monkeypatch.setattr(joining, "issue_agent_key", tracked_issue)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda item: _join_in_separate_session(item, barrier), [first, second]))

    created = [row for row in results if row[0] == "created"]
    rejected = [row for row in results if row[0] == "rejected"]
    assert len(created) == 1
    assert len(rejected) == 1
    assert rejected[0][1] == 409
    assert rejected[0][2]["code"] == "logical_identity_exists"
    assert "canonical_endpoint_plus_declared_identity" in rejected[0][2]["evidence"]
    assert len(key_calls) == 1
    assert len({row[3] for row in results}) == 2

    with SessionLocal() as db:
        rows = db.scalars(select(models.Agent).where(models.Agent.endpoint == endpoint)).all()
        assert len(rows) == 1


def test_capability_failure_rolls_back_agent_identity(monkeypatch):
    payload = _payload(capabilities=[{"name": "valid"}, {"name": "fails"}])

    def fail_on_second(name):
        if name == "fails":
            raise ValueError("injected capability normalization failure")
        return name

    monkeypatch.setattr(joining, "normalize_capability", fail_on_second)
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="injected capability"):
            join_agent(payload, db)

    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Agent).where(models.Agent.external_id == payload.external_id)) == 0


def test_postgresql_locks_are_database_scoped_and_deterministic():
    calls = []

    class _Dialect:
        name = "postgresql"

    class _Bind:
        dialect = _Dialect()

    class _Session:
        def get_bind(self):
            return _Bind()

        def execute(self, statement, params):
            calls.append((str(statement), params["lock_key"]))

    payload = _payload("postgres-lock", name="Postgres Lock", endpoint="https://example.invalid/a2a")
    joining._serialize_logical_identity(payload, _Session())
    first = list(calls)
    calls.clear()
    joining._serialize_logical_identity(payload, _Session())
    assert first == calls
    assert first
    assert all("pg_advisory_xact_lock" in statement for statement, _ in first)
