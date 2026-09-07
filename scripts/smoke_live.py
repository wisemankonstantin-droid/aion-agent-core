import json
import os
import uuid
import urllib.error
import urllib.request

base = (os.environ.get("AION_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
if not base.startswith("https://"):
    raise SystemExit("Set AION_PUBLIC_URL or RENDER_EXTERNAL_URL to the deployed https:// URL")


def get_json(path):
    with urllib.request.urlopen(base + path, timeout=25) as r:
        body = r.read()
        if r.status != 200:
            raise SystemExit(f"FAIL {path}: HTTP {r.status}")
        return json.loads(body)


def get_bytes(path):
    with urllib.request.urlopen(base + path, timeout=25) as r:
        body = r.read()
        if r.status != 200:
            raise SystemExit(f"FAIL {path}: HTTP {r.status}")
        return body


def post_json(path, payload, headers=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            body = json.loads(raw)
        except Exception:
            body = raw.decode(errors="replace")
        raise SystemExit(f"FAIL POST {path}: HTTP {e.code} {body}") from e

for path in [
    "/health",
    "/.well-known/aion.json",
    "/llms.txt",
    "/openapi.json",
    "/stats",
    "/funnel",
    "/.well-known/agent-card.json",
    "/a2a/status",
]:
    body = get_bytes(path)
    print("OK", path, len(body), "bytes")

health = get_json("/health")
assert health["version"] == "0.7.1", health
assert health["a2a_runtime"] == "mounted", health

card = get_json("/.well-known/agent-card.json")
interfaces = card.get("supportedInterfaces") or []
assert any(i.get("protocolBinding") == "JSONRPC" and i.get("protocolVersion") == "1.0" for i in interfaces), card

MCP_VERSION = "2026-07-28"
CLIENT_META = {
    "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "aion-live-smoke", "version": "0.7.1"},
}
MCP_BASE_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": MCP_VERSION,
}

status, discover = post_json(
    "/mcp",
    {"jsonrpc": "2.0", "id": "mcp-discover", "method": "server/discover", "params": {"_meta": CLIENT_META}},
    {**MCP_BASE_HEADERS, "Mcp-Method": "server/discover"},
)
assert status == 200 and "error" not in discover, discover
assert MCP_VERSION in discover["result"]["supportedVersions"], discover
assert discover["result"]["_meta"]["io.modelcontextprotocol/serverInfo"]["version"] == "0.7.1", discover
print("OK /mcp server/discover")

status, tools = post_json(
    "/mcp",
    {"jsonrpc": "2.0", "id": "mcp-tools", "method": "tools/list", "params": {"_meta": CLIENT_META}},
    {**MCP_BASE_HEADERS, "Mcp-Method": "tools/list"},
)
assert status == 200 and "error" not in tools, tools
tool_names = {t["name"] for t in tools["result"]["tools"]}
for required in {"join_aion", "publish_need", "publish_offer", "get_opportunities", "complete_interaction"}:
    assert required in tool_names, (required, tool_names)
print("OK /mcp tools/list")

message_id = "aion-smoke-" + uuid.uuid4().hex
status, a2a = post_json(
    "/a2a/v1",
    {
        "jsonrpc": "2.0",
        "id": "a2a-smoke",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": message_id,
                "role": "ROLE_USER",
                "parts": [{"text": "help"}],
            }
        },
    },
    {"A2A-Version": "1.0"},
)
assert status == 200 and "error" not in a2a, a2a
assert "result" in a2a, a2a
message = a2a["result"]["message"]
onboarding = json.loads(message["parts"][0]["text"])
assert onboarding["join_over_a2a"]["action"] == "join_aion", onboarding
print("OK /a2a/v1 SendMessage")

print("LIVE SMOKE PASS")
