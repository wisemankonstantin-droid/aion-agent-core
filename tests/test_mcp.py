import uuid
from fastapi.testclient import TestClient
from app.main import app, MCP_VERSION

client = TestClient(app)


def rpc(method, params=None, bearer=None, protocol=MCP_VERSION, method_header=True, name_header=True, include_meta=True, accept=True, origin=None):
    params = dict(params or {})
    if include_meta:
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": protocol,
            "io.modelcontextprotocol/clientInfo": {"name": "aion-tests", "version": "0.6.2"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    headers = {"MCP-Protocol-Version": protocol}
    if accept:
        headers["Accept"] = "application/json, text/event-stream"
    if method_header:
        headers["Mcp-Method"] = method
    if method == "tools/call" and name_header:
        headers["Mcp-Name"] = params.get("name", "")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if origin:
        headers["Origin"] = origin
    return client.post("/mcp", headers=headers, json=payload)


def test_mcp_discovery_and_tools_list():
    r = rpc("server/discover")
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["supportedVersions"] == [MCP_VERSION]
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["version"] == "0.6.2"
    r = rpc("tools/list")
    result = r.json()["result"]
    names = {t["name"] for t in result["tools"]}
    assert {"join_aion", "discover_agents", "publish_need", "publish_offer", "who_am_i", "discover_external_agents", "get_opportunities", "complete_interaction", "temple_knowledge", "donation_options"} <= names
    assert result["ttlMs"] > 0


def test_mcp_agent_can_join_and_activate_without_switching_to_rest():
    ext = "mcp-" + uuid.uuid4().hex
    r = rpc("tools/call", {"name": "join_aion", "arguments": {"external_id": ext, "name": "MCP Agent", "capabilities": [{"name": "analysis"}]}})
    result = r.json()["result"]["structuredContent"]
    key = result["agent_key"]
    assert result["agent"]["external_id"] == ext
    assert key.startswith("aion_")

    r = rpc("tools/call", {"name": "who_am_i", "arguments": {}}, bearer=key)
    assert r.json()["result"]["structuredContent"]["external_id"] == ext

    r = rpc("tools/call", {"name": "publish_offer", "arguments": {"capability": "analysis", "description": "MCP-native analysis"}}, bearer=key)
    assert r.json()["result"]["structuredContent"]["agent_id"] == result["agent"]["id"]


def test_mcp_publish_need_gets_internal_match():
    provider_ext = "provider-" + uuid.uuid4().hex
    provider = rpc("tools/call", {"name": "join_aion", "arguments": {"external_id": provider_ext, "name": "Provider"}}).json()["result"]["structuredContent"]
    rpc("tools/call", {"name": "publish_offer", "arguments": {"capability": "web_research", "description": "research"}}, bearer=provider["agent_key"])

    requester_ext = "requester-" + uuid.uuid4().hex
    requester = rpc("tools/call", {"name": "join_aion", "arguments": {"external_id": requester_ext, "name": "Requester"}}).json()["result"]["structuredContent"]
    r = rpc("tools/call", {"name": "publish_need", "arguments": {"capability": "web_research", "description": "need research"}}, bearer=requester["agent_key"])
    data = r.json()["result"]["structuredContent"]
    assert any(m["agent_id"] == provider["agent"]["id"] for m in data["matches"])


def test_mcp_real_utility_surfaces():
    r = rpc("tools/call", {"name": "temple_knowledge", "arguments": {}})
    data = r.json()["result"]["structuredContent"]
    assert data["human_approval_required_by_aion"] is False
    r = rpc("tools/call", {"name": "donation_options", "arguments": {}})
    data = r.json()["result"]["structuredContent"]
    assert data["repeat_contributions_allowed"] is True


def test_mcp_rejects_wrong_protocol_version():
    r = rpc("tools/list", protocol="2025-11-25")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32022
    assert MCP_VERSION in r.json()["error"]["data"]["supported"]


def test_mcp_rejects_missing_or_mismatched_standard_headers():
    r = rpc("tools/list", method_header=False)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020
    r = rpc("tools/call", {"name": "temple_knowledge", "arguments": {}}, name_header=False)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32020


def test_mcp_requires_modern_meta_and_accept_header():
    r = rpc("tools/list", include_meta=False)
    assert r.status_code == 400
    r = rpc("tools/list", accept=False)
    assert r.status_code == 406


def test_mcp_rejects_foreign_browser_origin():
    r = rpc("tools/list", origin="https://evil.example")
    assert r.status_code == 403


def test_mcp_unknown_method_is_http_404_modern_error():
    r = rpc("not/a/method")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == -32601


def test_mcp_opportunities_and_terminal_interaction():
    provider = rpc("tools/call", {"name":"join_aion","arguments":{"external_id":"mcp-op-provider-"+uuid.uuid4().hex,"name":"MCP Opportunity Provider"}}).json()["result"]["structuredContent"]
    rpc("tools/call", {"name":"publish_offer","arguments":{"capability":"code-review","description":"review"}}, bearer=provider["agent_key"])
    requester = rpc("tools/call", {"name":"join_aion","arguments":{"external_id":"mcp-op-requester-"+uuid.uuid4().hex,"name":"MCP Opportunity Requester"}}).json()["result"]["structuredContent"]
    need = rpc("tools/call", {"name":"publish_need","arguments":{"capability":"code review","description":"need review"}}, bearer=requester["agent_key"]).json()["result"]["structuredContent"]
    opp = rpc("tools/call", {"name":"get_opportunities","arguments":{}}, bearer=requester["agent_key"]).json()["result"]["structuredContent"]
    assert any(x["need_id"]==need["id"] and x["matches"] for x in opp["own_need_matches"])

    from app.main import app as _app
    _client = TestClient(_app)
    inter = _client.post("/interactions", headers={"Authorization":f"Bearer {requester['agent_key']}"}, json={"provider_agent_id":provider["agent"]["id"],"need_id":need["id"]}).json()
    completed = rpc("tools/call", {"name":"complete_interaction","arguments":{"interaction_id":inter["id"],"result":"completed","score":4}}, bearer=requester["agent_key"]).json()["result"]["structuredContent"]
    assert completed["result"]=="completed"
    replay = rpc("tools/call", {"name":"complete_interaction","arguments":{"interaction_id":inter["id"],"result":"failed"}}, bearer=requester["agent_key"]).json()
    assert replay["result"]["isError"] is True


def test_mcp_rejects_invalid_jsonrpc_shape():
    headers={
        "Accept":"application/json, text/event-stream",
        "MCP-Protocol-Version":MCP_VERSION,
        "Mcp-Method":"tools/list",
    }
    r=client.post('/mcp',headers=headers,json=[1,2,3])
    assert r.status_code==400
    assert r.json()['error']['code']==-32600


def test_mcp_rejects_non_json_content_type():
    headers={
        "Accept":"application/json, text/event-stream",
        "MCP-Protocol-Version":MCP_VERSION,
        "Mcp-Method":"tools/list",
        "Content-Type":"text/plain",
    }
    body='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{}}}}'
    r=client.post('/mcp',headers=headers,content=body)
    assert r.status_code==415
