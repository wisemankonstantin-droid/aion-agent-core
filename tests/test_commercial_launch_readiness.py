from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import fastapi
import starlette
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from app import models
from app.conversation_models import ConversationEvidence, ConversationIntelligence
from app.db import SessionLocal
from app.main import (
    MAX_MACHINE_REQUEST_BYTES,
    MAX_WRITE_REQUEST_BYTES,
    MCP_VERSION,
    _BoundMachineRequestBody,
    app,
)
from app.public_origin import PublicOriginError, canonical_public_origin
from app.security import hash_key
from app.services import ambassador, commercial_router
from app.services.external_registry import DiscoveryResult
from scripts import render_server_json


client = TestClient(app)


def _agent() -> tuple[int, str]:
    key = "aion_launch_" + uuid.uuid4().hex
    with SessionLocal() as db:
        row = models.Agent(
            external_id="commercial-launch-" + uuid.uuid4().hex,
            name="Commercial Launch Test",
            protocol="MCP",
            api_key_hash=hash_key(key),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, key


def _candidate() -> dict:
    identifier = "launch-provider-" + uuid.uuid4().hex
    return {
        "source": "global_a2a_registry",
        "identifier": identifier,
        "name": "Launch Provider",
        "description": "bounded candidate",
        "url": f"https://{identifier}.example/.well-known/agent-card.json",
        "interaction_url": f"https://{identifier}.example/a2a",
        "manifest_reachable": True,
        "card_parseable": True,
        "declared_a2a_v1_jsonrpc": True,
        "interaction_url_validated": True,
        "authentication_requirement": "none",
        "protocol_binding": "JSONRPC",
        "protocol_version": "1.0",
        "registry_verified_claim": False,
    }


def _discovery(candidate: dict) -> DiscoveryResult:
    return DiscoveryResult(
        [candidate],
        "success",
        None,
        {
            "candidate_limit": 5,
            "outbound_attempt_budget": 12,
            "outbound_attempts_used": 0,
            "response_byte_limit": 256000,
        },
    )


def _mcp(key: str | None, arguments: dict):
    meta = {
        "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "commercial-launch-test", "version": "1"},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "plan_commercial_route",
    }
    if key is not None:
        headers["Authorization"] = "Bearer " + key
    return client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": "commercial-route",
            "method": "tools/call",
            "params": {
                "name": "plan_commercial_route",
                "arguments": arguments,
                "_meta": meta,
            },
        },
    )


def _column_snapshot(agent_id: int) -> dict:
    with SessionLocal() as db:
        row = db.get(models.Agent, agent_id)
        return {
            column.key: getattr(row, column.key)
            for column in inspect(models.Agent).mapper.column_attrs
        }


def _protected_counts() -> dict:
    protected = (
        models.EconomicOperation,
        models.EconomicTransition,
        models.PaymentIntent,
        models.ActionRun,
        models.ActionAttempt,
        models.ActionOutcome,
        models.ActionVerification,
        models.Package5VuoProof,
        models.Interaction,
        models.Need,
        models.Offer,
        models.MachineEntry,
        models.AmbassadorContactAttempt,
        ConversationEvidence,
        ConversationIntelligence,
    )
    with SessionLocal() as db:
        return {
            model.__tablename__: db.scalar(select(func.count()).select_from(model)) or 0
            for model in protected
        }


def test_mcp_commercial_route_requires_authentication(monkeypatch):
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate()))
    response = _mcp(None, {"need": "research", "currency": "USD"})
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["status"] == 401


def test_mcp_commercial_route_matches_rest_and_is_fully_read_only(monkeypatch):
    agent_id, key = _agent()
    candidate = _candidate()
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(candidate))
    payload = {
        "need": "bounded web research",
        "currency": "USD",
        "requester_max_price": "25.00",
        "candidate_identifier": candidate["identifier"],
    }
    before_agent = _column_snapshot(agent_id)
    before_counts = _protected_counts()

    rest = client.post(
        "/commercial/routes/plan",
        headers={"Authorization": "Bearer " + key},
        json=payload,
    )
    mcp = _mcp(key, payload)

    assert rest.status_code == mcp.status_code == 200
    assert mcp.headers["cache-control"] == "private, no-store"
    mcp_result = mcp.json()["result"]
    assert mcp_result["isError"] is False
    assert mcp_result["structuredContent"] == rest.json()
    assert rest.json()["execution"]["provider_interaction_endpoint_contacted"] is False
    assert rest.json()["execution"]["payment_rail_contacted"] is False
    assert rest.json()["commercial"]["execution_eligible"] is False
    assert rest.json()["truth_boundaries"]["route_plan_is_not_executable_quote"] is True
    assert _column_snapshot(agent_id) == before_agent
    assert _protected_counts() == before_counts


def test_machine_surfaces_lead_with_truthful_commercial_route_guidance():
    onboarding = client.get("/onboarding").json()
    manifest = client.get("/.well-known/aion.json").json()
    first_contact = client.get("/first-contact").json()
    route = onboarding["commercial_route_planning"]
    assert route == manifest["commercial_route_planning"] == first_contact["commercial_route_planning"]
    assert route["planning_only"] is True
    assert route["MCP"]["tool"] == "plan_commercial_route"
    assert route["A2A"]["available"] is False
    assert route["fresh_current_job_verification_required_before_execution"] is True
    assert route["truth_boundaries"]["requester_budget_is_preference_not_funds"] is True
    for path in ("/skill.md", "/llms.txt"):
        text = client.get(path).text
        assert "plan_commercial_route" in text
        assert "planning-only" in text
        assert "A2A exposes discovery and guidance, not the authenticated commercial route-planning tool" in text


def test_agent_card_advertises_cross_interface_planning_without_false_a2a_execution():
    card = client.get("/.well-known/agent-card.json").json()
    skill = {item["id"]: item for item in card["skills"]}["aion_commercial_route_planning"]
    assert "REST/MCP" in skill["description"]
    assert "A2A provides guidance only" in skill["description"]
    assert "does not execute the route" in skill["description"]
    assert "verified route planning" in card["description"]


def test_ambassador_invitation_is_demand_first_but_keeps_all_truth_boundaries():
    token = "aion_dist_" + "x" * 43
    message = ambassador.build_ambassador_message(
        public_base_url="https://aion.example", distribution_token=token
    )
    assert message["purpose"] == "bounded_machine_utility_invitation"
    assert "what capability or result you need" in message["utility"]
    assert message["join"]["optional"] is True
    assert message["commercial_route"]["planning_only"] is True
    assert message["commercial_route"]["fresh_current_job_verification_required_before_execution"] is True
    assert "no provider execution or payment" in message["truth"]
    assert "not independent adoption" in message["truth"]


def test_mcp_registry_metadata_is_bounded_and_preserves_required_identity():
    server = render_server_json.build_server("https://aion.example/")
    assert server["description"] == render_server_json.DESCRIPTION
    assert len(server["description"]) <= 100
    assert server["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert server["name"] == "io.github.wisemankonstantin-droid/aion-agent-core"
    assert server["version"] == "0.8.0"
    assert server["remotes"] == [{"type": "streamable-http", "url": "https://aion.example/mcp"}]
    assert server["repository"] == {
        "url": "https://github.com/wisemankonstantin-droid/aion-agent-core",
        "source": "github",
    }


def test_launch_security_dependency_pair_and_publisher_checksum_are_pinned():
    assert fastapi.__version__ == "0.141.1"
    assert starlette.__version__ == "1.6.0"
    root = render_server_json.Path(__file__).resolve().parents[1]
    requirements_in = (root / "requirements.in").read_text(encoding="utf-8")
    workflow = (root / ".github/workflows/publish-mcp.yml").read_text(encoding="utf-8")
    assert "fastapi==0.141.1" in requirements_in
    assert "starlette==1.6.0" in requirements_in
    assert "releases/download/v1.8.1/mcp-publisher_linux_amd64.tar.gz" in workflow
    assert "a06c9096dcb9727c13555b6be26c7effa707b01f06a4c561ba7a3635443cf2cc" in workflow
    assert "sha256sum --check --strict" in workflow
    assert "releases/latest" not in workflow


def test_mcp_tool_and_discovery_expose_planning_without_execution_claims():
    response = client.post(
        "/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/list",
        },
        json={
            "jsonrpc": "2.0",
            "id": "tools",
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
    )
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    route_tool = tools["plan_commercial_route"]
    assert route_tool["inputSchema"]["required"] == ["need"]
    assert route_tool["inputSchema"]["properties"]["currency"]["default"] == "USD"
    assert "never executes" in route_tool["description"]
    assert "idempotency" not in json.dumps(route_tool).lower()


def test_a2a_version_guard_uses_scope_path_and_requires_header_not_query():
    payload = {
        "jsonrpc": "2.0",
        "id": "version",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "version-message",
                "role": "ROLE_USER",
                "parts": [{"text": "hello"}],
            }
        },
    }
    poisoned = client.post(
        "/a2a/v1?A2A-Version=1.0",
        headers={"Host": "poisoned.example"},
        json=payload,
    )
    assert poisoned.status_code == 400
    assert poisoned.json()["error"]["code"] == -32009
    assert poisoned.json()["error"]["data"]["requested"] == "missing"


def test_poisoned_host_never_changes_machine_advertised_origin():
    for path in (
        "/first-contact",
        "/onboarding",
        "/.well-known/agent-card.json",
        "/.well-known/agent.json",
        "/.well-known/aion.json",
        "/skill.md",
        "/llms.txt",
    ):
        response = client.get(path, headers={"Host": "attacker.invalid:9443"})
        assert response.status_code == 200
        encoded = response.text
        assert "attacker.invalid" not in encoded
        assert "https://aion.example" in encoded


def test_managed_runtime_canonical_origin_fails_closed(monkeypatch):
    monkeypatch.delenv("AION_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(PublicOriginError):
        canonical_public_origin()


def _bounded_write(method: str, path: str, chunks: list[bytes], headers=()):
    messages = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    received = 0
    status = None
    downstream_body = None

    async def receive():
        nonlocal received
        message = messages[received]
        received += 1
        return message

    async def downstream(scope, downstream_receive, send):
        nonlocal downstream_body
        body = []
        while True:
            message = await downstream_receive()
            body.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        downstream_body = b"".join(body)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": list(headers),
    }
    asyncio.run(_BoundMachineRequestBody(downstream)(scope, receive, send))
    return status, received, downstream_body


@pytest.mark.parametrize(
    ("method", "path"),
    (("POST", "/agents"), ("PATCH", "/agents/me"), ("PUT", "/agents/me/capabilities")),
)
def test_all_http_writes_have_outer_256k_stream_limit(method, path):
    chunks = [b"a" * MAX_WRITE_REQUEST_BYTES, b"b", b"unread"]
    status, received, downstream = _bounded_write(method, path, chunks)
    assert status == 413
    assert received == 2
    assert downstream is None


def test_outer_write_limit_rejects_duplicate_or_invalid_content_length_before_reading():
    for headers in (
        ((b"content-length", b"1"), (b"content-length", b"1")),
        ((b"content-length", b"invalid"),),
    ):
        status, received, downstream = _bounded_write("PATCH", "/agents/me", [b"unread"], headers)
        assert status == 400
        assert received == 0
        assert downstream is None


def test_existing_tighter_machine_and_router_limits_remain_outermost():
    status, received, _ = _bounded_write(
        "POST", "/mcp", [b"x" * (MAX_MACHINE_REQUEST_BYTES + 1), b"unread"]
    )
    assert (status, received) == (413, 1)


def test_ambassador_uses_official_sendmessage_and_correlates_semantic_response():
    message = ambassador.build_ambassador_message(
        public_base_url="https://aion.example",
        distribution_token="aion_dist_" + "x" * 43,
    )
    payload = ambassador._contact_payload(
        message, target_id="target", idempotency_key="contact"
    )
    assert payload["method"] == "SendMessage"
    assert "message/send" not in json.dumps(payload)
    valid = {
        "jsonrpc": "2.0",
        "id": payload["id"],
        "result": {
            "message": {
                "messageId": "reply",
                "role": "ROLE_AGENT",
                "parts": [{"text": "bounded response"}],
            }
        },
    }
    assert ambassador._validated_semantic_response(valid, payload["id"]) is not None
    assert ambassador._validated_semantic_response(dict(valid, id="wrong"), payload["id"]) is None
    assert ambassador._validated_semantic_response(
        {"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -1, "message": "no"}},
        payload["id"],
    ) is None
    assert ambassador._validated_semantic_response(
        {"jsonrpc": "2.0", "id": payload["id"], "result": {}}, payload["id"]
    ) is None
    nonterminal = {
        "jsonrpc": "2.0",
        "id": payload["id"],
        "result": {"task": {"id": "task", "contextId": "context", "status": {"state": "TASK_STATE_WORKING"}}},
    }
    assert ambassador._validated_semantic_response(nonterminal, payload["id"]) is None


def test_ambassador_invitation_exposes_optional_bounded_feedback_without_execution():
    message = ambassador.build_ambassador_message(
        public_base_url="https://aion.example",
        distribution_token="aion_dist_" + "x" * 43,
    )
    contract = message["optional_structured_feedback"]
    assert contract["part_type"] == "A2A data part"
    assert contract["reply_causes_no_payment_or_provider_execution"] is True
    assert len(json.dumps(message, sort_keys=True, separators=(",", ":")).encode()) <= ambassador.MAX_MESSAGE_BYTES
    status, received, _ = _bounded_write(
        "POST",
        "/commercial/routes/plan",
        [b"x" * (commercial_router.MAX_COMMERCIAL_ROUTE_BODY_BYTES + 1), b"unread"],
    )
    assert (status, received) == (413, 1)
