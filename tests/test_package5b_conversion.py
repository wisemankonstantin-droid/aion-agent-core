import json
import uuid

from fastapi.testclient import TestClient

from app.main import MCP_VERSION, app


client = TestClient(app)


def _mcp(method: str, params: dict | None = None, bearer: str | None = None):
    params = dict(params or {})
    params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "agent-only-test", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": method,
    }
    if method == "tools/call":
        headers["Mcp-Name"] = params.get("name", "")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": "agent-only", "method": method, "params": params},
    )


def _join(label: str) -> tuple[dict, str]:
    response = client.post(
        "/agents",
        json={
            "external_id": f"agent-only-{label}-{uuid.uuid4().hex}",
            "name": f"Agent Only {label}",
            "protocol": "MCP",
            "capabilities": [{"name": "public_data"}],
        },
    )
    assert response.status_code == 200
    body = response.json()
    return body["agent"], body["agent_key"]


def _assert_agent_only_journey(journey: dict) -> None:
    assert journey["audience"] == "AI agents and machine principals"
    assert journey["human_participant_required"] is False
    assert "machine_request" in journey["sequence"]
    assert "machine_outcome_verification" in journey["sequence"]
    assert "machine_vuo" in journey["sequence"]
    assert "package5_countable_participation_gate" not in journey
    assert "requester_usefulness_acknowledgement" not in journey
    assert journey["machine_outcome_verification"]["human_confirmation_required"] is False
    assert journey["machine_vuo"]["separate_human_usefulness_acknowledgement_required"] is False
    assert journey["machine_vuo"]["separate_operator_review_required"] is False
    assert journey["bounded_execution"]["MCP"]["tool"] == "execute_world_bank_population"
    assert journey["machine_outcome_verification"]["MCP"]["tool"] == "get_world_bank_execution"
    assert journey["legacy_package5"]["operator_classification_is_launch_gate"] is False
    assert journey["legacy_package5"]["ambassador_outreach_is_launch_gate"] is False


def test_machine_surfaces_share_agent_only_journey():
    onboarding = client.get("/onboarding").json()
    manifest = client.get("/.well-known/aion.json").json()
    first_contact = client.get("/first-contact").json()

    _assert_agent_only_journey(onboarding["verified_outcome_journey"])
    assert onboarding["verified_outcome_journey"] == manifest["verified_outcome_journey"]
    assert onboarding["verified_outcome_journey"] == first_contact["verified_outcome_journey"]

    route = onboarding["commercial_route_planning"]
    assert route["human_participant_required"] is False
    executable = route["executable_zero_cost_capability"]
    assert executable["MCP"]["execute_tool"] == "execute_world_bank_population"
    assert executable["MCP"]["status_tool"] == "get_world_bank_execution"
    assert executable["machine_vuo_on_verified_completion"] is True
    assert executable["human_usefulness_acknowledgement_required"] is False


def test_machine_docs_remove_operator_and_acknowledgement_gate():
    for path in ("/skill.md", "/llms.txt"):
        document = client.get(path).text
        assert "execute_world_bank_population" in document
        assert "get_world_bank_execution" in document
        assert "wait for operator review" not in document
        assert "separately POST" not in document


def test_mcp_exposes_agent_native_execution_and_status_tools():
    response = _mcp("tools/list")
    assert response.status_code == 200
    tools = {item["name"]: item for item in response.json()["result"]["tools"]}
    assert "execute_world_bank_population" in tools
    assert "get_world_bank_execution" in tools
    assert "without human usefulness acknowledgement" in tools["execute_world_bank_population"]["description"]


def test_onboarding_has_no_package5_gate_in_active_journey():
    document = json.dumps(client.get("/onboarding").json())
    assert "execute_world_bank_population" in document
    assert "get_world_bank_execution" in document
    assert "package5_countable_participation_gate" not in document
    assert "requester_usefulness_acknowledgement" not in document


def test_removed_official_data_acknowledgement_endpoint_is_not_an_agent_gate():
    _, key = _join("removed-ack")
    response = client.post(
        f"/commercial/executions/{uuid.uuid4()}/acknowledge",
        headers={"Authorization": f"Bearer {key}"},
        json={"usefulness_confirmed": True},
    )
    assert response.status_code == 404
