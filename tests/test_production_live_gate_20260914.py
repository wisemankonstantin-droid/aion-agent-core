import json
import uuid

from scripts.smoke_live import MCP_VERSION, PublicHttpClient, run_live_smoke

BASE = "https://aion-agent-core-live.onrender.com"
EXPECTED_SHA = "18afa934fdddef2a0489874c5ac2446fcf947475"


def _mcp_payload(need):
    return {
        "jsonrpc": "2.0",
        "id": "production-privacy-gate",
        "method": "tools/call",
        "params": {
            "name": "plan_commercial_route",
            "arguments": {"need": need, "currency": "USD"},
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                "io.modelcontextprotocol/clientCapabilities": {},
                "io.modelcontextprotocol/clientInfo": {
                    "name": "aion-production-live-gate",
                    "version": "0.8.0",
                },
            },
        },
    }


def test_production_live_gate_exact_release_and_router_privacy():
    client = PublicHttpClient(BASE)

    # First run the repository's standard non-mutating exact-SHA protocol gate.
    result = run_live_smoke(client, EXPECTED_SHA)
    assert result["status"] == "pass"

    before_status, before = client.request("GET", "/stats")
    assert before_status == 200

    # Create exactly one stable-classified internal test identity. The raw key is
    # kept in-memory only and is never printed into Actions logs.
    external_id = "aion-internal-live-smoke-" + uuid.uuid4().hex
    join_status, join = client.request(
        "POST",
        "/agents",
        {
            "external_id": external_id,
            "name": "AION Internal Production Live Smoke",
            "description": "Synthetic release verification identity; excluded from independent adoption.",
            "protocol": "REST",
            "acquisition_source": "internal-test",
            "capabilities": [],
        },
    )
    assert join_status == 200
    key = join.get("agent_key")
    assert isinstance(key, str) and key.startswith("aion_")
    auth = {"Authorization": "Bearer " + key}

    # Sensitive string must be rejected before any discovery and must not echo.
    secret = "api_key=AION_SYNTHETIC_LIVE_SECRET_12345678901234567890"
    status, body = client.request(
        "POST",
        "/commercial/routes/plan",
        {"need": secret, "currency": "USD"},
        auth,
    )
    assert status == 422
    assert secret not in json.dumps(body, sort_keys=True)

    # Non-string/nested sensitive input must also be no-echo and fail closed.
    nested_secret = "AION_NESTED_LIVE_SECRET_12345678901234567890"
    status, body = client.request(
        "POST",
        "/commercial/routes/plan",
        {"need": {"token": nested_secret}, "currency": "USD"},
        auth,
    )
    assert status == 422
    assert nested_secret not in json.dumps(body, sort_keys=True)

    # Targeted mode may contact only the public identifier path; requester need
    # must not be sent to the Registry. A nonexistent valid identifier is used so
    # no provider interaction endpoint can be contacted.
    status, targeted = client.request(
        "POST",
        "/commercial/routes/plan",
        {
            "need": "targeted release privacy boundary smoke",
            "currency": "USD",
            "candidate_identifier": "com.aion.release.smoke.nonexistent",
        },
        auth,
    )
    assert status == 200
    assert targeted["discovery"]["mode"] == "registry_identifier_lookup"
    assert targeted["discovery"]["need_sent_to_public_registry"] is False
    assert targeted["truth_boundaries"]["need_sent_to_public_registry"] is False
    assert targeted["execution"]["provider_interaction_endpoint_contacted"] is False
    assert targeted["execution"]["provider_execution_started"] is False
    assert targeted["execution"]["payment_rail_contacted"] is False
    assert targeted["execution"]["economic_operation_created"] is False

    # Benign Bearer prose must not false-positive as a credential.
    status, generic = client.request(
        "POST",
        "/commercial/routes/plan",
        {"need": "Bearer authentication documentation", "currency": "USD"},
        auth,
    )
    assert status == 200
    assert generic["discovery"]["mode"] == "registry_need_search"
    assert generic["discovery"]["need_sent_to_public_registry"] is True
    assert generic["execution"]["provider_interaction_endpoint_contacted"] is False
    assert generic["execution"]["payment_rail_contacted"] is False
    assert generic["execution"]["economic_operation_created"] is False

    # The same no-echo contract must hold through MCP.
    mcp_secret = "token=AION_SYNTHETIC_MCP_SECRET_12345678901234567890"
    mcp_headers = {
        **auth,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "plan_commercial_route",
    }
    status, mcp_body = client.request("POST", "/mcp", _mcp_payload(mcp_secret), mcp_headers)
    assert status == 200
    assert mcp_secret not in json.dumps(mcp_body, sort_keys=True)
    assert mcp_body["result"]["isError"] is True
    assert mcp_body["result"]["structuredContent"]["status"] == 422

    # Browser-origin requests cannot manufacture trust from an attacker Origin.
    poisoned_headers = {**mcp_headers, "Origin": "https://attacker.invalid"}
    status, _ = client.request("POST", "/mcp", _mcp_payload("research"), poisoned_headers)
    assert status == 403

    after_status, after = client.request("GET", "/stats")
    assert after_status == 200
    assert after["agents_raw_rows"] == before["agents_raw_rows"] + 1
    assert after["estimated_unique_external_agents"] == before["estimated_unique_external_agents"]
    assert after["open_needs_raw_rows"] == before["open_needs_raw_rows"]
    assert after["offers_raw_rows"] == before["offers_raw_rows"]
    assert after["interactions"] == before["interactions"]
    assert after["payment_intents"] == before["payment_intents"]
