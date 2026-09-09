import uuid

import pytest
from fastapi.testclient import TestClient

from app import models, schemas
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.services import action_engine, external_registry


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_guards():
    with external_registry._AION_DISCOVERY_STATE_LOCK:
        external_registry._AION_DISCOVERY_RATE_TIMES.clear()
        external_registry._AION_VALIDATION_CACHE.clear()
    with action_engine._ACTION_RATE_LOCK:
        action_engine._ACTION_RATE_TIMES.clear()


def _requester_id():
    token = uuid.uuid4().hex
    with SessionLocal.begin() as db:
        agent = models.Agent(
            external_id="discovery-semantics-" + token,
            name="Discovery Semantics " + token,
            api_key_hash="discovery-semantics-hash-" + token,
        )
        db.add(agent)
        db.flush()
        return agent.id


def _run_action(requester_id):
    return action_engine.verify_external_callability(
        requester_id,
        schemas.VerifyCallabilityRequest(
            query="research", authorize_external_contact=True
        ),
        uuid.uuid4().hex,
    )


def _assert_no_post(monkeypatch):
    monkeypatch.setattr(
        action_engine,
        "_post_challenge",
        lambda *args: pytest.fail("discovery failure must not invoke"),
    )


def test_successful_empty_search_is_the_only_empty_no_result(monkeypatch):
    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    monkeypatch.setattr(
        external_registry,
        "_read_json",
        lambda *args, **kwargs: (200, [], None),
    )
    _assert_no_post(monkeypatch)

    discovery = external_registry.discover_external_agents_with_status("research", 5)
    assert discovery.status == "success"
    assert discovery.failure_class is None
    assert discovery.results == []
    result = _run_action(_requester_id())
    assert result["failure_class"] == "no_result"
    assert result["telemetry"]["invocation_attempts"] == 0


def test_public_discovery_can_exhaust_shared_rate_without_creating_false_no_result(
    monkeypatch,
):
    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    monkeypatch.setattr(
        external_registry,
        "_AION_RESOLVED_DISCOVER",
        lambda query, limit, budget: external_registry.DiscoveryResult(
            [], "success", None, external_registry._discovery_bounds(budget)
        ),
    )
    for _ in range(external_registry._AION_DISCOVERY_RATE_LIMIT):
        assert external_registry.discover_external_agents("research", 5) == []
    _assert_no_post(monkeypatch)

    result = _run_action(_requester_id())
    assert result["failure_class"] == "rate_limited"
    assert result["failure_class"] != "no_result"
    assert result["telemetry"]["invocation_attempts"] == 0


def test_operator_disabled_discovery_is_unavailable_without_post(monkeypatch):
    monkeypatch.setenv("AION_DISABLE_EXTERNAL_DISCOVERY", "1")
    _assert_no_post(monkeypatch)
    result = _run_action(_requester_id())
    assert result["failure_class"] == "unavailable"
    assert result["failure_class"] != "no_result"
    assert result["telemetry"]["invocation_attempts"] == 0


@pytest.mark.parametrize(
    ("status", "error", "expected"),
    [
        (None, "TimeoutError:registry", "endpoint_unreachable"),
        (503, "http_503", "endpoint_unreachable"),
        (429, "http_429", "rate_limited"),
    ],
)
def test_registry_operational_failures_are_not_no_result(
    monkeypatch, status, error, expected
):
    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    monkeypatch.setattr(
        external_registry,
        "_read_json",
        lambda *args, **kwargs: (status, None, error),
    )
    _assert_no_post(monkeypatch)
    result = _run_action(_requester_id())
    assert result["failure_class"] == expected
    assert result["failure_class"] != "no_result"
    assert result["telemetry"]["invocation_attempts"] == 0


def test_budget_exhaustion_before_complete_candidate_set_is_unavailable(monkeypatch):
    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    rows = [
        {"identifier": f"agent-{index}", "package_name": f"package-{index}"}
        for index in range(5)
    ]

    def read(method, url, payload=None, headers=None, timeout=4, budget=None):
        if budget.remaining <= 0:
            return None, None, "outbound_budget_exhausted"
        budget.consume(min(2, budget.remaining))
        if "?q=" in url:
            return 200, rows, None
        return 200, {}, None

    monkeypatch.setattr(external_registry, "_read_json", read)
    discovery = external_registry.discover_external_agents_with_status("research", 5)
    assert discovery.failure_class == "unavailable"
    assert discovery.resource_bounds["outbound_attempts_used"] == 12

    monkeypatch.setattr(
        action_engine, "discover_external_agents_with_status", lambda *args: discovery
    )
    _assert_no_post(monkeypatch)
    result = _run_action(_requester_id())
    assert result["failure_class"] == "unavailable"
    assert result["failure_class"] != "no_result"


def test_public_rest_and_mcp_discovery_contracts_remain_list_compatible(monkeypatch):
    monkeypatch.setattr("app.main.discover_external_agents", lambda *args: [])
    rest = client.get("/discover/external?q=research")
    assert rest.status_code == 200
    assert rest.json() == {
        "query": "research",
        "results": [],
        "membership": "external results are not counted as AION members",
    }

    params = {
        "name": "discover_external_agents",
        "arguments": {"query": "research", "limit": 5},
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }
    mcp = client.post(
        "/mcp",
        headers={
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "discover_external_agents",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
    )
    assert mcp.status_code == 200
    assert mcp.json()["result"]["structuredContent"]["results"] == []


def test_list_compatibility_delegates_to_structured_status(monkeypatch):
    sentinel = [{"identifier": "external:sentinel"}]
    monkeypatch.setattr(
        external_registry,
        "discover_external_agents_with_status",
        lambda *args: external_registry.DiscoveryResult(
            sentinel, "endpoint_unreachable", "endpoint_unreachable", {}
        ),
    )
    assert external_registry.discover_external_agents("research", 5) == sentinel
