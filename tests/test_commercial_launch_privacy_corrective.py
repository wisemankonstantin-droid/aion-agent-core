import uuid

import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.security import hash_key
from app.services import commercial_router, external_registry, external_registry_targeted
from app.services.external_registry import DiscoveryResult


client = TestClient(app)


def _agent_key() -> str:
    token = uuid.uuid4().hex
    key = "aion_privacy_" + token
    with SessionLocal() as db:
        db.add(
            models.Agent(
                external_id="privacy-" + token,
                name="Commercial privacy test",
                protocol="REST",
                api_key_hash=hash_key(key),
                acquisition_source="internal-test",
            )
        )
        db.commit()
    return key


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + key}


def _mcp_headers(key: str, *, origin: str | None = None, host: str | None = None):
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "plan_commercial_route",
    }
    if origin is not None:
        headers["Origin"] = origin
    if host is not None:
        headers["Host"] = host
    return headers


def _mcp_payload(need: str, candidate_identifier=None):
    arguments = {"need": need, "currency": "USD"}
    if candidate_identifier is not None:
        arguments["candidate_identifier"] = candidate_identifier
    return {
        "jsonrpc": "2.0",
        "id": "privacy-gate",
        "method": "tools/call",
        "params": {
            "name": "plan_commercial_route",
            "arguments": arguments,
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "privacy-corrective-test",
                    "version": "0.8.0",
                },
            },
        },
    }


@pytest.mark.parametrize(
    "sensitive",
    [
        "https://private.example/path?token=SECRET123",
        "api_key=SUPERSECRET123",
        "password: hunter2",
        "Bearer abcdefghijklmnopqrstuvwxyz012345",
        "Abc123" * 8,
    ],
)
def test_rest_sensitive_need_is_rejected_before_discovery_without_echo(monkeypatch, sensitive):
    key = _agent_key()
    calls = []

    def discover(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("sensitive need reached public discovery")

    monkeypatch.setattr(commercial_router, "_DISCOVER", discover)
    monkeypatch.setattr(commercial_router, "_DISCOVER_BY_IDENTIFIER", discover)
    response = client.post(
        "/commercial/routes/plan",
        headers=_auth(key),
        json={"need": sensitive, "currency": "USD"},
    )
    assert response.status_code == 422
    assert sensitive not in response.text
    assert calls == []


def test_normal_bearer_documentation_phrase_is_not_false_positive(monkeypatch):
    key = _agent_key()
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda need, limit: DiscoveryResult(
            [], "success", None, {"outbound_attempts_used": 0}
        ),
    )
    response = client.post(
        "/commercial/routes/plan",
        headers=_auth(key),
        json={"need": "Bearer authentication documentation", "currency": "USD"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["discovery"]["need_sent_to_public_registry"] is True


def test_mcp_sensitive_need_is_rejected_without_echo_or_discovery(monkeypatch):
    key = _agent_key()
    secret = "token=THIS_MUST_NEVER_LEAVE_AION"

    def discover(*args, **kwargs):
        raise AssertionError("sensitive MCP need reached discovery")

    monkeypatch.setattr(commercial_router, "_DISCOVER", discover)
    monkeypatch.setattr(commercial_router, "_DISCOVER_BY_IDENTIFIER", discover)
    response = client.post(
        "/mcp",
        headers=_mcp_headers(key),
        json=_mcp_payload(secret),
    )
    assert response.status_code == 200
    assert secret not in response.text
    body = response.json()
    assert body["result"]["isError"] is True
    assert body["result"]["structuredContent"]["status"] == 422


def test_identifier_path_never_calls_need_search(monkeypatch):
    key = _agent_key()
    identifier = "com.example.agent"

    def generic(*args, **kwargs):
        raise AssertionError("generic ?q= need search must not run for identifier path")

    targeted_calls = []

    def targeted(value):
        targeted_calls.append(value)
        return DiscoveryResult(
            [{"source": "global_a2a_registry", "identifier": value}],
            "success",
            None,
            {"outbound_attempts_used": 1},
        )

    monkeypatch.setattr(commercial_router, "_DISCOVER", generic)
    monkeypatch.setattr(commercial_router, "_DISCOVER_BY_IDENTIFIER", targeted)
    response = client.post(
        "/commercial/routes/plan",
        headers=_auth(key),
        json={
            "need": "research summary",
            "currency": "USD",
            "candidate_identifier": identifier,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert targeted_calls == [identifier]
    assert body["discovery"]["mode"] == "registry_identifier_lookup"
    assert body["discovery"]["need_sent_to_public_registry"] is False
    assert body["truth_boundaries"]["need_sent_to_public_registry"] is False


@pytest.mark.parametrize(
    "identifier",
    ["https://registry.example/private", "../agent", "token=SECRET123"],
)
def test_unsafe_identifier_is_rejected_without_echo_or_network(monkeypatch, identifier):
    key = _agent_key()

    def network(*args, **kwargs):
        raise AssertionError("unsafe identifier reached network")

    monkeypatch.setattr(commercial_router, "_DISCOVER", network)
    monkeypatch.setattr(commercial_router, "_DISCOVER_BY_IDENTIFIER", network)
    response = client.post(
        "/commercial/routes/plan",
        headers=_auth(key),
        json={
            "need": "research",
            "currency": "USD",
            "candidate_identifier": identifier,
        },
    )
    assert response.status_code == 422
    assert identifier not in response.text


def test_targeted_registry_helper_has_no_query_search_or_need_parameter(monkeypatch):
    urls = []
    identifier = "com.example.agent"
    manifest = "https://provider.example/agent-card.json"

    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    monkeypatch.setattr(external_registry, "_allow_discovery", lambda: True)
    monkeypatch.setattr(
        external_registry,
        "_resolve_public_https",
        lambda value: (None, ["93.184.216.34"], None),
    )

    def read_json(method, url, payload=None, headers=None, timeout=4.0, budget=None):
        urls.append(url)
        if budget is not None:
            budget.consume(1)
        if url == external_registry.A2A_REGISTRY_SEARCH + "/" + identifier:
            return 200, {
                "agent": {
                    "identifier": identifier,
                    "name": "Provider",
                    "manifest_url": manifest,
                }
            }, None
        if url == manifest:
            return 200, {
                "name": "Provider",
                "securityRequirements": [],
                "supportedInterfaces": [
                    {
                        "url": "https://provider.example/a2a/v1",
                        "protocolBinding": "JSONRPC",
                        "protocolVersion": "1.0",
                    }
                ],
            }, None
        raise AssertionError(url)

    monkeypatch.setattr(external_registry, "_read_json", read_json)
    result = external_registry_targeted.discover_external_agent_by_identifier_with_status(
        identifier
    )
    assert result.status == "success"
    assert result.results[0]["identifier"] == identifier
    assert result.results[0]["declared_a2a_v1_jsonrpc"] is True
    assert all("?q=" not in url for url in urls)
    assert urls[0] == external_registry.A2A_REGISTRY_SEARCH + "/" + identifier


def test_host_header_cannot_authorize_attacker_mcp_origin(monkeypatch):
    key = _agent_key()
    monkeypatch.setenv("AION_PUBLIC_URL", "https://aion.example")
    monkeypatch.delenv("AION_ALLOWED_ORIGINS", raising=False)
    response = client.post(
        "/mcp",
        headers=_mcp_headers(
            key,
            origin="https://evil.example",
            host="evil.example",
        ),
        json=_mcp_payload("research"),
    )
    assert response.status_code == 403


def test_openapi_discloses_public_registry_privacy_boundary():
    schema = client.get("/openapi.json").json()
    operation = schema["paths"]["/commercial/routes/plan"]["post"]
    text = (operation.get("description") or "").lower()
    assert "public a2a registry" in text
    assert "never place secrets" in text
    assert "does not send need" in text
