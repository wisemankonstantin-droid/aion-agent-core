from datetime import datetime, timedelta, timezone
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import models
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.services import live_utility_store
from app.services.live_utility import SourceObservation
from app.services.live_utility_sources import (
    VERIFICATION_METHOD,
    configured_tier1_adapters,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_surface_live_utility_rows():
    yield
    with SessionLocal.begin() as db:
        db.execute(delete(models.AgentUtilityCheckpoint))
        db.execute(
            delete(models.LiveUtilityVerification).where(
                models.LiveUtilityVerification.verification_id.like("verify-surface-%")
            )
        )
        db.execute(
            delete(models.LiveUtilityObservation).where(
                models.LiveUtilityObservation.observation_id.like("obs-surface-%")
            )
        )
        for adapter in configured_tier1_adapters():
            remaining = db.scalar(
                select(func.count()).select_from(models.LiveUtilityObservation).where(
                    models.LiveUtilityObservation.source_id == adapter.source.source_id
                )
            )
            if not remaining:
                db.execute(
                    delete(models.LiveUtilitySource).where(
                        models.LiveUtilitySource.source_id == adapter.source.source_id
                    )
                )


def _seed_public_a2a():
    now = datetime.now(timezone.utc)
    adapter = configured_tier1_adapters()[0]
    with SessionLocal() as db:
        if live_utility_store.get_source(db, adapter.source.source_id) is None:
            live_utility_store.register_source(db, adapter.source)
        latest = live_utility_store.get_latest_normalized_observation(
            db,
            source_id=adapter.source.source_id,
            subject_key=adapter.subject_key,
        )
        observation = SourceObservation(
            observation_id="obs-surface-" + uuid.uuid4().hex,
            source_id=adapter.source.source_id,
            subject_key=adapter.subject_key,
            source_revision="v1.0.1",
            previous_observation_id=latest[0].observation_id if latest else None,
            observed_at=now - timedelta(minutes=1),
            verified_at=now,
            valid_from=now - timedelta(minutes=1),
            stale_after=now + timedelta(days=7),
            expires_at=now + timedelta(days=30),
            verification_method=VERIFICATION_METHOD,
            content_digest="sha256:" + uuid.uuid4().hex,
        )
        normalized = {
            "protocol": "a2a",
            "version": "v1.0.1",
            "release_name": "A2A v1.0.1",
            "published_at": now.isoformat(),
            "official_url": "https://github.com/a2aproject/A2A/releases/tag/v1.0.1",
            "prerelease": False,
            "draft": False,
            "release_id": 1,
        }
        live_utility_store.append_observation(
            db,
            observation,
            normalized_data=normalized,
        )
        live_utility_store.append_verification(
            db,
            live_utility_store.VerificationRecord(
                verification_id="verify-surface-" + uuid.uuid4().hex,
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
        db.commit()


def _agent_count():
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(models.Agent))


def _mcp_call(arguments):
    payload = {
        "jsonrpc": "2.0",
        "id": "utility-test",
        "method": "tools/call",
        "params": {
            "name": "get_live_utility",
            "arguments": arguments,
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    }
    return client.post(
        "/mcp",
        headers={
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "get_live_utility",
            "Accept": "application/json, text/event-stream",
        },
        json=payload,
    )


def _a2a_call(command):
    from app.main import A2A_RUNTIME

    if A2A_RUNTIME.get("status") != "mounted":
        pytest.skip("a2a-sdk not installed in this local test environment")
    payload = {
        "jsonrpc": "2.0",
        "id": "utility-a2a-test",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "msg-" + uuid.uuid4().hex,
                "role": "ROLE_USER",
                "parts": [{"text": json.dumps(command)}],
            }
        },
    }
    response = client.post(
        "/a2a/v1",
        headers={"A2A-Version": "1.0"},
        json=payload,
    )
    assert response.status_code == 200, response.text
    rpc = response.json()
    assert "error" not in rpc, rpc
    return json.loads(rpc["result"]["message"]["parts"][0]["text"])


def _context():
    return {
        "supported_protocols": ["a2a"],
        "supported_protocol_versions": {"a2a": ["1.0.1"]},
    }


def test_anonymous_rest_first_contact_returns_evidence_without_membership():
    _seed_public_a2a()
    before = _agent_count()
    response = client.get("/first-contact")
    assert response.status_code == 200
    body = response.json()
    result = body["live_utility"]["results"][0]
    assert body["membership_required"] is False
    assert result["source"]["tier"] == "tier_1"
    assert result["evidence"]["verification_level"] == "source_observation_verified"
    assert result["freshness"]["state"] == "fresh"
    assert _agent_count() == before


def test_rest_utility_uses_shared_compatibility_logic_without_membership():
    _seed_public_a2a()
    before = _agent_count()
    response = client.post(
        "/utility/query",
        json={"subject": "a2a", "context": _context()},
    )
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["compatibility"]["decision"] == "compatible"
    assert result["current_eligibility"] is True
    assert result["action"]["safe_to_use_as_current_reference"] is True
    assert _agent_count() == before


def test_machine_request_body_is_bounded_before_utility_logic():
    response = client.post(
        "/utility/query",
        content=b"{" + (b" " * (64 * 1024)) + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


def test_authenticated_rest_utility_reconstructs_durable_delta():
    _seed_public_a2a()
    joined = client.post(
        "/agents",
        json={
            "external_id": "utility-delta-" + uuid.uuid4().hex,
            "name": "Utility Delta Agent",
        },
    ).json()
    headers = {"Authorization": f"Bearer {joined['agent_key']}"}
    payload = {"subject": "a2a", "context": _context()}

    baseline = client.post("/utility/query", headers=headers, json=payload)
    assert baseline.json()["results"][0]["personalized_delta"]["status"] == "baseline_created"
    repeated = client.post("/utility/query", headers=headers, json=payload)
    assert repeated.json()["results"][0]["personalized_delta"]["status"] == "unchanged"
    with SessionLocal() as db:
        checkpoint = db.scalar(
            select(models.AgentUtilityCheckpoint).where(
                models.AgentUtilityCheckpoint.agent_id == joined["agent"]["id"]
            )
        )
        assert checkpoint is not None


def test_mcp_tool_discovery_and_evidence_aware_call():
    _seed_public_a2a()
    before = _agent_count()
    listed = client.post(
        "/mcp",
        headers={
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/list",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
    )
    assert "get_live_utility" in {
        tool["name"] for tool in listed.json()["result"]["tools"]
    }
    response = _mcp_call({"subject": "a2a", "context": _context()})
    assert response.status_code == 200
    result = response.json()["result"]["structuredContent"]["results"][0]
    assert result["compatibility"]["decision"] == "compatible"
    assert result["evidence"]["verification_method"] == VERIFICATION_METHOD
    assert _agent_count() == before


def test_mcp_rejects_unbounded_context():
    response = _mcp_call(
        {"subject": "a2a", "context": {"supported_protocols": ["a2a"] * 9}}
    )
    assert response.status_code == 200
    assert response.json()["error"]["code"] == -32602


def test_a2a_live_utility_and_first_contact_preserve_evidence_and_membership():
    _seed_public_a2a()
    before = _agent_count()
    utility = _a2a_call(
        {"action": "live_utility", "subject": "a2a", "context": _context()}
    )
    result = utility["results"][0]
    assert result["compatibility"]["decision"] == "compatible"
    assert result["freshness"]["state"] == "fresh"
    rest_result = client.post(
        "/utility/query",
        json={"subject": "a2a", "context": _context()},
    ).json()["results"][0]
    mcp_result = _mcp_call(
        {"subject": "a2a", "context": _context()}
    ).json()["result"]["structuredContent"]["results"][0]
    for shared in (rest_result, mcp_result):
        assert shared["source"] == result["source"]
        assert shared["evidence"] == result["evidence"]
        assert shared["freshness"] == result["freshness"]
        assert shared["compatibility"] == result["compatibility"]
    first_contact = _a2a_call({"action": "first_contact", "subject": "a2a"})
    assert first_contact["live_utility"]["results"][0]["source"]["tier"] == "tier_1"
    assert _agent_count() == before


def test_a2a_rejects_unbounded_utility_context_without_membership():
    before = _agent_count()
    response = _a2a_call(
        {
            "action": "live_utility",
            "subject": "a2a",
            "context": {"supported_protocols": ["a2a"] * 9},
        }
    )
    assert response["status"] == "invalid_request"
    assert response["membership_required"] is False
    assert _agent_count() == before
