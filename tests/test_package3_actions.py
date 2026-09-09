import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models, schemas
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.services import action_engine
from app.services.safe_http import FetchResult


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_action_process_guards():
    with action_engine._ACTION_RATE_LOCK:
        action_engine._ACTION_RATE_TIMES.clear()


def _join():
    external_id = "action-" + uuid.uuid4().hex
    response = client.post("/agents", json={"external_id": external_id, "name": external_id})
    assert response.status_code == 200
    body = response.json()
    return body["agent"]["id"], body["agent_key"]


def _candidate(**overrides):
    result = {
        "identifier": "external:test-agent",
        "source": "test-registry",
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
    result.update(overrides)
    return result


def _verified_response(encoded):
    request = json.loads(encoded)
    challenge = json.loads(request["params"]["message"]["parts"][0]["text"])
    body = {
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {
            "message": {
                "messageId": "reply-1",
                "role": "ROLE_AGENT",
                "parts": [{"text": json.dumps({"nonce": challenge["nonce"]})}],
            }
        },
    }
    return FetchResult(200, json.dumps(body).encode(), None, 1)


def _request(key, *, idem=None, payload=None):
    return client.post(
        "/actions/verify-callability",
        headers={
            "Authorization": f"Bearer {key}",
            "Idempotency-Key": idem or uuid.uuid4().hex,
        },
        json=payload
        or {"query": "research", "authorize_external_contact": True},
    )


def _mcp(key, name, arguments):
    params = {
        "name": name,
        "arguments": arguments,
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {key}",
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
    )


def test_unauthenticated_or_unauthorized_requests_never_contact(monkeypatch):
    contacts = []
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: contacts.append(a))
    assert _request("invalid").status_code == 401
    _, key = _join()
    for payload in (
        {"query": "research"},
        {"query": "research", "authorize_external_contact": False},
    ):
        response = _request(key, payload=payload)
        assert response.status_code == 422
    assert contacts == []


def test_requester_cannot_supply_url_message_headers_or_method(monkeypatch):
    contacts = []
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: contacts.append(a))
    _, key = _join()
    base = {"query": "research", "authorize_external_contact": True}
    for extra in ("url", "message", "headers", "method", "credentials"):
        response = _request(key, payload={**base, extra: "forbidden"})
        assert response.status_code == 422
    assert contacts == []


def test_no_result_and_credentialed_candidate_make_no_post(monkeypatch):
    _, key = _join()
    posts = []
    monkeypatch.setattr(action_engine, "_post_challenge", lambda *a: posts.append(a))
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [])
    assert _request(key).json()["failure_class"] == "no_result"
    monkeypatch.setattr(
        action_engine,
        "discover_external_agents",
        lambda *a: [_candidate(authentication_requirement="credentials_required")],
    )
    assert _request(key).json()["failure_class"] == "permission_missing"
    assert posts == []


def test_unknown_auth_and_candidate_identifier_mismatch_are_not_invoked(monkeypatch):
    _, key = _join()
    posts = []
    monkeypatch.setattr(action_engine, "_post_challenge", lambda *a: posts.append(a))
    monkeypatch.setattr(
        action_engine,
        "discover_external_agents",
        lambda *a: [_candidate(authentication_requirement="unknown")],
    )
    assert _request(key).json()["failure_class"] == "permission_missing"
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [_candidate()])
    response = _request(
        key,
        payload={
            "query": "research",
            "candidate_identifier": "external:not-the-result",
            "authorize_external_contact": True,
        },
    )
    assert response.json()["failure_class"] == "capability_not_found"
    assert posts == []


def test_interaction_destination_is_revalidated_and_private_resolution_is_not_contacted(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [_candidate()])
    monkeypatch.setattr(
        action_engine.safe_http,
        "resolve_public_https",
        lambda *a, **k: (None, (), "non_public_address:127.0.0.1"),
    )
    contacts = []
    monkeypatch.setattr(action_engine, "_ACTION_CONNECTION_FACTORY", lambda *a: contacts.append(a))
    result = _request(key).json()
    assert result["failure_class"] == "unsafe_destination"
    assert result["attempts"][0]["delivery_state"] == "not_sent"
    assert contacts == []


@pytest.mark.parametrize(
    ("fetch_result", "failure"),
    [
        (FetchResult(302, None, "redirect_rejected", 1), "protocol_failure"),
        (FetchResult(200, None, "response_too_large", 1), "response_too_large"),
        (FetchResult(None, None, "TimeoutError:timed out", 1), "unknown_delivery_state"),
        (FetchResult(200, b"not-json", None, 1), "protocol_failure"),
    ],
)
def test_bounded_transport_failures_are_precise_and_never_retried(
    monkeypatch, fetch_result, failure
):
    _, key = _join()
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [_candidate()])
    calls = []
    monkeypatch.setattr(
        action_engine,
        "_post_challenge",
        lambda *a: calls.append(a) or fetch_result,
    )
    result = _request(key).json()
    assert result["failure_class"] == failure
    assert len(calls) == 1
    assert result["limits"]["remote_post_attempts"] == 1
    if failure == "unknown_delivery_state":
        assert result["state"] == "ambiguous"


def test_valid_protocol_without_nonce_is_not_verified(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [_candidate()])
    def response(encoded):
        request = json.loads(encoded)
        body = {"jsonrpc": "2.0", "id": request["id"], "result": {"message": {
            "messageId": "reply", "role": "ROLE_AGENT", "parts": [{"text": "reachable"}]
        }}}
        return FetchResult(200, json.dumps(body).encode(), None, 1)
    monkeypatch.setattr(action_engine, "_post_challenge", lambda url, encoded: response(encoded))
    outcome = _request(key).json()["outcome"]
    assert outcome["protocol_response_received"] is True
    assert outcome["callability_verified"] is False
    assert outcome["capability_verified"] is False
    assert outcome["verified_outcome"] is False
    assert outcome["failure_class"] == "verification_failed"


def test_nonterminal_a2a_task_is_bounded_without_polling():
    action_id = str(uuid.uuid4())
    body = {
        "jsonrpc": "2.0",
        "id": action_id,
        "result": {"task": {
            "id": "remote-task", "contextId": "remote-context",
            "status": {"state": "TASK_STATE_WORKING"},
        }},
    }
    evidence = action_engine._protocol_evidence(
        json.dumps(body).encode(), action_id, "nonce"
    )
    assert evidence["failure_class"] == "async_result_not_supported_v1"
    assert evidence["verified_outcome"] is False


def test_action_transport_policy_is_fixed_and_single_attempt(monkeypatch):
    captured = {}
    def fetch(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return FetchResult(None, None, "connection_failed", 1)
    monkeypatch.setattr(action_engine.safe_http, "fetch_bytes", fetch)
    action_engine._post_challenge("https://agent.example/a2a", b"{}")
    assert captured["method"] == "POST"
    assert captured["payload"] == b"{}"
    assert captured["headers"] == {
        "Content-Type": "application/json", "A2A-Version": "1.0"
    }
    assert captured["policy"].max_attempts == 1
    assert captured["policy"].max_response_bytes == 128 * 1024
    assert captured["policy"].timeout_seconds == 5.0


def test_query_and_idempotency_bounds_fail_before_discovery(monkeypatch):
    contacts = []
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: contacts.append(a))
    _, key = _join()
    assert _request(
        key, payload={"query": "x" * 129, "authorize_external_contact": True}
    ).status_code == 422
    response = _request(key, idem="x" * 129)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_idempotency_key"
    assert contacts == []


def test_end_to_end_success_is_durable_idempotent_and_separates_evidence(monkeypatch):
    requester_id, key = _join()
    with SessionLocal() as db:
        starting_agents = db.scalar(select(func.count()).select_from(models.Agent))
        reputation = db.get(models.Agent, requester_id).reputation
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [_candidate()])
    posts = []
    monkeypatch.setattr(
        action_engine,
        "_post_challenge",
        lambda url, encoded: posts.append((url, encoded)) or _verified_response(encoded),
    )
    idem = uuid.uuid4().hex
    first = _request(key, idem=idem)
    assert first.status_code == 200
    result = first.json()
    assert result["outcome"]["callability_verified"] is True
    assert result["outcome"]["verified_outcome"] is True
    assert result["outcome"]["capability_verified"] is False
    assert result["verification"]["method"] == "a2a_nonce_roundtrip_v1"
    assert result["telemetry"]["cost_amount"] is None
    assert result["telemetry"]["cost_currency"] is None
    assert len(posts) == 1
    outbound = json.loads(posts[0][1])
    assert outbound["method"] == "SendMessage"
    assert set(outbound["params"]) == {"message", "configuration"}

    replay = _request(key, idem=idem).json()
    assert replay["action_id"] == result["action_id"]
    assert replay["idempotent_replay"] is True
    status = client.get(
        f"/actions/{result['action_id']}", headers={"Authorization": f"Bearer {key}"}
    ).json()
    assert status["outcome"] == result["outcome"]
    assert len(posts) == 1

    with SessionLocal() as db:
        run = db.scalar(select(models.ActionRun).where(models.ActionRun.action_id == result["action_id"]))
        assert db.scalar(select(func.count()).select_from(models.ActionAttempt).where(models.ActionAttempt.action_run_id == run.id)) == 1
        assert db.scalar(select(func.count()).select_from(models.ActionOutcome).where(models.ActionOutcome.action_run_id == run.id)) == 1
        assert db.scalar(select(func.count()).select_from(models.ActionVerification).where(models.ActionVerification.action_run_id == run.id)) == 1
        assert db.scalar(select(func.count()).select_from(models.Agent)) == starting_agents
        assert db.get(models.Agent, requester_id).reputation == reputation
        persisted = json.dumps({column.name: getattr(run, column.name) for column in run.__table__.columns}, default=str)
        assert "reply-1" not in persisted


def test_idempotency_conflict_and_concurrent_replay_never_make_second_post(monkeypatch):
    requester_id, _ = _join()
    payload = schemas.VerifyCallabilityRequest(query="research", authorize_external_contact=True)
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [_candidate()])
    entered = threading.Event()
    release = threading.Event()
    posts = []
    def post(url, encoded):
        posts.append(encoded)
        entered.set()
        assert release.wait(10)
        return _verified_response(encoded)
    monkeypatch.setattr(action_engine, "_post_challenge", post)
    idem = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(action_engine.verify_external_callability, requester_id, payload, idem)
        assert entered.wait(10)
        second = pool.submit(action_engine.verify_external_callability, requester_id, payload, idem)
        replay = second.result(timeout=10)
        release.set()
        completed = first.result(timeout=10)
    assert replay["action_id"] == completed["action_id"]
    assert len(posts) == 1
    changed = schemas.VerifyCallabilityRequest(query="planning", authorize_external_contact=True)
    with pytest.raises(action_engine.ActionServiceError) as conflict:
        action_engine.verify_external_callability(requester_id, changed, idem)
    assert conflict.value.status_code == 409
    assert conflict.value.code == "idempotency_conflict"
    assert len(posts) == 1


def test_in_progress_restart_read_is_conservative_and_never_resends(monkeypatch):
    requester_id, _ = _join()
    action_id = str(uuid.uuid4())
    with SessionLocal.begin() as db:
        run = models.ActionRun(
            action_id=action_id, requester_agent_id=requester_id, idempotency_key=uuid.uuid4().hex,
            request_digest="sha256:" + "0" * 64, requested_query="research",
            requested_candidate_identifier=None, authorize_external_contact=True,
            state="invoking", created_at=action_engine._utcnow(), started_at=action_engine._utcnow(),
            discovery_attempt_count=1, action_attempt_count=0, request_bytes=1,
        )
        db.add(run)
        db.flush()
        db.add(models.ActionAttempt(
            action_run_id=run.id, attempt_number=1, method="POST",
            state="dispatching", delivery_state="unknown",
            started_at=action_engine._utcnow(), request_bytes=1,
        ))
    monkeypatch.setattr(action_engine, "_post_challenge", lambda *a: pytest.fail("must not resend"))
    status = action_engine.get_action_status_by_id(action_id, requester_id)
    assert status["failure_class"] == "unknown_delivery_state"


def test_mcp_and_rest_use_same_service_and_require_auth(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: [_candidate()])
    monkeypatch.setattr(action_engine, "_post_challenge", lambda u, e: _verified_response(e))
    response = _mcp(key, "verify_external_callability", {
        "query": "research", "authorize_external_contact": True,
        "idempotency_key": uuid.uuid4().hex,
    })
    data = response.json()["result"]["structuredContent"]
    assert data["outcome"]["callability_verified"] is True
    denied = _mcp(None, "get_action_status", {"action_id": data["action_id"]})
    assert denied.json()["result"]["isError"] is True


def test_action_rate_guard_is_bounded_deterministically(monkeypatch):
    monkeypatch.setattr(action_engine, "ACTION_RATE_LIMIT", 2)
    assert action_engine._allow_action(100.0)
    assert action_engine._allow_action(100.1)
    assert not action_engine._allow_action(100.2)
    assert action_engine._allow_action(161.0)


def test_action_considers_no_more_than_candidate_limit(monkeypatch):
    _, key = _join()
    candidates = [
        _candidate(identifier=f"external:{index}", card_parseable=False)
        for index in range(action_engine.ACTION_DISCOVERY_CANDIDATE_LIMIT)
    ]
    candidates.append(_candidate(identifier="external:beyond-limit"))
    posts = []
    monkeypatch.setattr(action_engine, "discover_external_agents", lambda *a: candidates)
    monkeypatch.setattr(action_engine, "_post_challenge", lambda *a: posts.append(a))
    result = _request(key).json()
    assert result["failure_class"] == "unavailable"
    assert posts == []
