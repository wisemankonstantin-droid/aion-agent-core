"""Controlled fixtures prove read behavior, never production commercial proof."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import models
from app.db import Base, SessionLocal, engine
from app.services import package5_proof, lifecycle
from app.services.identity_resolution import unique_funnel
from test_package5_proof import _agent, _assess, _action
from test_package5_proof import clear_package5_evidence  # noqa: F401 - isolate controlled proof fixtures
from test_package5b_conversion import client, _mcp, _a2a


PATH = "/agents/me/package5-participation"
TOOL = "get_my_package5_participation"


def rest(key, **kwargs):
    return client.get(PATH, headers={"Authorization": "Bearer " + key}, **kwargs)


def mcp(key, arguments=None):
    return _mcp("tools/call", {"name": TOOL, "arguments": {} if arguments is None else arguments}, bearer=key)


def snapshot():
    # Every persisted column, not merely counters: catches hidden lifecycle/evidence writes.
    with engine.connect() as connection:
        rows = {table.name: connection.execute(select(table).order_by(*table.primary_key.columns)).all()
                for table in Base.metadata.sorted_tables}
    with SessionLocal() as db:
        return rows, unique_funnel(db), package5_proof.package5_proof_snapshot(db)["counts"]


@pytest.mark.parametrize("classification", [None, *package5_proof._CLASSIFICATION_REASONS])
def test_classes_and_rest_mcp_parity_without_writes(classification):
    agent_id, key = _agent(acquisition_source="organic independent")
    if classification:
        _assess(agent_id, classification)
    before = snapshot()
    response = rest(key)
    assert response.status_code == 200
    data = response.json()
    assert data["canonical_agent_id"] == agent_id
    assert data["classification"] == (classification or "unknown_not_proven")
    assert data["countable"] == data["vuo_submission_ready"] == (classification == "independent_external_countable")
    assert data["assessment_id"] is not None if classification else data["assessment_id"] is None
    assert data["operator_review_incomplete"] == (classification in (None, "independent_external_candidate"))
    assert data["state"] in ("participation_ready", "excluded", "review_incomplete")
    for _ in range(3):
        assert rest(key).json() == data
        rpc = mcp(key)
        assert rpc.json()["result"]["structuredContent"] == data
        assert rpc.headers["cache-control"] == "private, no-store"
    assert response.headers["cache-control"] == "private, no-store"
    serialized = json.dumps(data)
    for secret in (key, "api_key_hash", "evidence_reference", "evidence_summary", "DATABASE_URL"):
        assert secret not in serialized
    assert snapshot() == before


@pytest.mark.parametrize("header", [None, "", "Basic bad", "Bearer", "Bearer ", "Bearer invalid", "Bearer " + "x" * 1024])
def test_invalid_authentication_never_writes(header):
    before = snapshot()
    response = client.get(PATH, headers={"Authorization": header} if header is not None else {})
    assert response.status_code == 401
    rpc = _mcp("tools/call", {"name": TOOL, "arguments": {}}, bearer=header)
    assert rpc.json()["result"]["isError"] is True
    assert snapshot() == before


def test_cross_identity_scope_and_malformed_arguments():
    aid, key = _agent()
    bid, other = _agent()
    _assess(bid)
    before = snapshot()
    assert rest(key).json()["canonical_agent_id"] == aid
    assert rest(other).json()["canonical_agent_id"] == bid
    assert rest(key, params={"agent_id": bid}).status_code == 422
    for arguments in ({"agent_id": bid}, {"canonical_agent_id": bid}, {"classification": "independent_external_countable"}, [], "bad", False):
        assert "error" in mcp(key, arguments).json()
    assert client.post(PATH, headers={"Authorization": "Bearer " + key}, json={"agent_id": bid}).status_code == 405
    assert snapshot() == before


@pytest.mark.parametrize("marker", ["synthetic-test", "aion-operated", "configured"])
def test_linked_rows_share_identity_and_forced_exclusions(marker, monkeypatch):
    aid, key = _agent(endpoint="https://shared-" + marker + ".example/a2a", name="Shared " + marker)
    bid, other = _agent(endpoint="https://shared-" + marker + ".example/a2a", name="Shared " + marker)
    _assess(aid)
    assert rest(key).json() == rest(other).json()
    with SessionLocal() as db:
        row = db.get(models.Agent, bid)
        if marker == "configured":
            monkeypatch.setenv("AION_OPERATED_EXTERNAL_IDS", row.external_id)
        else:
            row.acquisition_source = marker
            db.commit()
    before = snapshot()
    a, b = rest(key).json(), rest(other).json()
    assert a == b
    assert a["canonical_agent_id"] == min(aid, bid)
    assert a["excluded"] is True and a["vuo_submission_ready"] is False
    assert snapshot() == before


def test_polling_across_24_hours_cannot_be_return(monkeypatch):
    from app import schemas
    monkeypatch.setenv("AION_PACKAGE5_RETURN_THRESHOLD_SECONDS", "86400")
    aid, key = _agent()
    _assess(aid)
    start = datetime.now(timezone.utc) - timedelta(days=3)
    action_id = _action(aid, created_at=start)
    monkeypatch.setattr(package5_proof, "_utcnow", lambda: start + timedelta(seconds=1))
    with SessionLocal() as db:
        package5_proof.submit_vuo_candidate(db, requester_agent_id=aid, payload=schemas.Package5VuoSubmission(
            action_id=action_id, goal_kind="verify_external_agent_callability",
            product_goal="find_verify_invoke_external_a2a_agent", delivered_outcome="verified_external_agent_callability",
            usefulness_confirmed=True, usefulness_evidence="requester_confirms_goal_was_useful",
        ), idempotency_key="polling-proof")
        agent = db.get(models.Agent, aid)
        agent.first_useful_action_at = start
        agent.last_seen_at = start
        db.commit()
    before = snapshot()
    for elapsed in (100, 86399, 86401, 172800):
        clock = start + timedelta(seconds=elapsed)
        monkeypatch.setattr(package5_proof, "_utcnow", lambda: clock)
        monkeypatch.setattr(lifecycle, "utcnow", lambda: clock)
        assert rest(key).status_code == 200
        assert mcp(key).json()["result"]["isError"] is False
        assert snapshot() == before


def test_existing_meaningful_authentication_still_touches_lifecycle():
    aid, key = _agent()
    response = client.post("/offers", headers={"Authorization": "Bearer " + key},
                           json={"capability": "test", "description": "controlled fixture"})
    assert response.status_code == 200
    with SessionLocal() as db:
        agent = db.get(models.Agent, aid)
        assert agent.authenticated_calls == 1
        assert agent.last_seen_at is not None
        assert agent.first_useful_action_at is not None


@pytest.mark.parametrize("transport", ["REST", "MCP"])
def test_package3_action_still_records_normal_authentication(transport, monkeypatch):
    from app.services import action_engine
    from test_package3_actions import _candidate, _discovery, _verified_response, _request
    monkeypatch.setattr(action_engine, "discover_external_agents_with_status", lambda *a: _discovery([_candidate()]))
    monkeypatch.setattr(action_engine, "_post_challenge", lambda url, encoded: _verified_response(encoded))
    aid, key = _agent()
    assert rest(key).json()["vuo_submission_ready"] is False
    # Readiness is not a new permission gate on existing actions.
    if transport == "REST":
        result = _request(key).json()
    else:
        result = _mcp("tools/call", {"name": "verify_external_callability", "arguments": {
            "query": "research", "authorize_external_contact": True, "idempotency_key": "normal-action",
        }}, bearer=key).json()["result"]["structuredContent"]
    assert result["state"] == "completed"
    with SessionLocal() as db:
        agent = db.get(models.Agent, aid)
        assert agent.authenticated_calls == 1 and agent.last_seen_at is not None
        assert db.scalar(select(models.ActionRun).where(models.ActionRun.requester_agent_id == aid)) is not None


def test_all_machine_guidance_exposes_no_touch_handshake():
    for path in ("/onboarding", "/.well-known/aion.json", "/skill.md", "/llms.txt", "/.well-known/agent-card.json"):
        response = client.get(path)
        assert response.status_code == 200
        assert PATH in response.text and TOOL in response.text
    assert TOOL in json.dumps(_a2a('{"action":"onboarding"}'))
    discover = _mcp("server/discover").json()["result"]
    assert TOOL in discover["instructions"]
    from app.machine_journey import verified_outcome_journey
    journey = verified_outcome_journey("https://example.test")
    assert journey["sequence"].index("check_own_package5_participation_readiness") < journey["sequence"].index("authenticated_verified_callability_action")
    assert journey["participation_readiness"]["A2A"]["available"] is False


def test_resource_limit_fails_closed(monkeypatch):
    _, key = _agent()
    monkeypatch.setattr(package5_proof, "MAX_PROOF_RAW_AGENT_ROWS", 0)
    response = rest(key)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "proof_resource_limit"
    assert mcp(key).json()["result"]["structuredContent"]["code"] == "proof_resource_limit"
