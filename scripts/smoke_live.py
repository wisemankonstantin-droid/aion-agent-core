"""Non-mutating Package 4 live gate for the accepted Package 1-3B stack."""

from __future__ import annotations

import json
import os
import re
import uuid
import urllib.error
import urllib.request


APP_VERSION = "0.7.1"
MCP_VERSION = "2026-07-28"
EXPECTED_SCHEMA_REVISION = "0010_package5_proof_v1"
MAX_SMOKE_RESPONSE_BYTES = 1024 * 1024
_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


class PublicHttpClient:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    def request(self, method: str, path: str, payload=None, headers=None):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json", **(headers or {})},
            method=method,
        )
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read(MAX_SMOKE_RESPONSE_BYTES + 1)
            if len(raw) > MAX_SMOKE_RESPONSE_BYTES:
                raise AssertionError(f"{path} exceeded smoke response bound")
            try:
                body = json.loads(raw)
            except Exception:
                body = raw.decode(errors="replace")
            status = getattr(response, "status", None) or getattr(response, "code", None)
            return status, body


def _ok(client, method, path, payload=None, headers=None):
    status, body = client.request(method, path, payload, headers)
    assert status == 200, (method, path, status, body)
    return body


def _expected_sha(value: str) -> str:
    normalized = str(value or "").strip()
    if not _SHA_PATTERN.fullmatch(normalized):
        raise SystemExit("AION_EXPECTED_RELEASE_SHA must be an exact 40-hex commit SHA")
    return normalized.lower()


def _mcp(client, method, rpc_id, params, *, name=None):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": method,
    }
    if name:
        headers["Mcp-Name"] = name
    body = _ok(
        client,
        "POST",
        "/mcp",
        {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params},
        headers,
    )
    assert "error" not in body, body
    return body["result"]


def _a2a(client, text: str, rpc_id: str):
    response = _ok(
        client,
        "POST",
        "/a2a/v1",
        {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "aion-package4-smoke-" + uuid.uuid4().hex,
                    "role": "ROLE_USER",
                    "parts": [{"text": text}],
                }
            },
        },
        {"A2A-Version": "1.0"},
    )
    assert "error" not in response and "result" in response, response
    return json.loads(response["result"]["message"]["parts"][0]["text"])


def run_live_smoke(client, expected_sha: str) -> dict:
    expected_sha = _expected_sha(expected_sha)
    before = _ok(client, "GET", "/stats")

    health = _ok(client, "GET", "/health")
    assert health["status"] == "ok" and health["version"] == APP_VERSION, health
    assert health["a2a_runtime"] == "mounted", health
    assert health.get("release_sha") == expected_sha, health
    assert health.get("release_source") in {"render_git_commit", "aion_release_sha"}, health

    readiness = _ok(client, "GET", "/readiness")
    assert readiness["status"] == "ready", readiness
    assert readiness["expected_schema_revision"] == EXPECTED_SCHEMA_REVISION, readiness
    assert readiness["database_schema_revision"] == EXPECTED_SCHEMA_REVISION, readiness
    assert readiness["schema_current"] is True, readiness
    assert all(readiness["checks"].values()), readiness
    assert readiness.get("release_sha") == expected_sha, readiness

    for path in (
        "/.well-known/aion.json",
        "/llms.txt",
        "/openapi.json",
        "/funnel",
        "/proof/package-5",
        "/a2a/status",
    ):
        _ok(client, "GET", path)

    card = _ok(client, "GET", "/.well-known/agent-card.json")
    interfaces = card.get("supportedInterfaces") or []
    assert any(
        interface.get("protocolBinding") == "JSONRPC"
        and interface.get("protocolVersion") == "1.0"
        for interface in interfaces
    ), card

    meta = {
        "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {
            "name": "aion-package4-live-smoke",
            "version": APP_VERSION,
        },
    }
    discover = _mcp(client, "server/discover", "mcp-discover", {"_meta": meta})
    assert MCP_VERSION in discover["supportedVersions"], discover
    tools = _mcp(client, "tools/list", "mcp-tools", {"_meta": meta})
    tool_names = {tool["name"] for tool in tools["tools"]}
    required_tools = {
        "get_live_utility",
        "verify_external_callability",
        "get_action_status",
        "submit_learning_evidence",
        "get_package5_proof",
    }
    assert required_tools <= tool_names, (required_tools, tool_names)
    mcp_utility = _mcp(
        client,
        "tools/call",
        "mcp-utility",
        {"name": "get_live_utility", "arguments": {"subject": "all"}, "_meta": meta},
        name="get_live_utility",
    )["structuredContent"]
    assert mcp_utility["action"] == "live_utility", mcp_utility
    assert mcp_utility["membership_required"] is False, mcp_utility
    assert mcp_utility["network_fetch_performed"] is False, mcp_utility
    package5 = _mcp(
        client,
        "tools/call",
        "mcp-package5-proof",
        {"name": "get_package5_proof", "arguments": {}, "_meta": meta},
        name="get_package5_proof",
    )["structuredContent"]
    assert package5["package"] == 5, package5
    assert package5["status"] == "evidence_snapshot", package5

    utility = _ok(client, "POST", "/utility/query", {"subject": "all"})
    assert utility["action"] == "live_utility", utility
    assert utility["membership_required"] is False, utility
    assert utility["network_fetch_performed"] is False, utility
    assert isinstance(utility["results"], list), utility
    for result in utility["results"]:
        assert {"source", "evidence", "freshness", "compatibility"} <= set(result), result

    first_contact = _a2a(client, "help", "a2a-first-contact")
    assert first_contact["action"] == "first_contact", first_contact
    assert first_contact["membership_required"] is False, first_contact
    assert first_contact["join_is_optional"] is True, first_contact
    onboarding = _a2a(
        client,
        json.dumps({"action": "onboarding"}, separators=(",", ":")),
        "a2a-onboarding",
    )
    assert onboarding["join_over_a2a"]["action"] == "join_aion", onboarding
    assert "agent_key" not in onboarding, onboarding

    action_status, _ = client.request(
        "POST",
        "/actions/verify-callability",
        {"query": "package-4-boundary", "authorize_external_contact": True},
        {"Idempotency-Key": "package-4-live-smoke-action"},
    )
    assert action_status in {401, 403}, action_status
    evidence_status, _ = client.request(
        "POST",
        "/learning/evidence",
        {
            "category": "missing_capability",
            "subject_key": "package-4-boundary",
            "description": "Unauthenticated boundary check; must not persist",
        },
        {"Idempotency-Key": "package-4-live-smoke-evidence"},
    )
    assert evidence_status in {401, 403}, evidence_status
    vuo_status, _ = client.request(
        "POST",
        "/proof/package-5/vuos",
        {
            "action_id": "00000000-0000-0000-0000-000000000000",
            "goal_kind": "verify_external_agent_callability",
            "product_goal": "find_verify_invoke_external_a2a_agent",
            "delivered_outcome": "verified_external_agent_callability",
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_goal_was_useful",
        },
        {"Idempotency-Key": "package-5-live-smoke-vuo"},
    )
    assert vuo_status in {401, 403}, vuo_status

    after = _ok(client, "GET", "/stats")
    assert after["agents_raw_rows"] == before["agents_raw_rows"], (before, after)
    return {
        "status": "pass",
        "release_sha": expected_sha,
        "schema_revision": EXPECTED_SCHEMA_REVISION,
        "membership_created": False,
        "external_action_dispatched": False,
        "evidence_submitted": False,
        "vuo_submitted": False,
        "learning_cycle_run": False,
    }


def main() -> int:
    base = (
        os.environ.get("AION_PUBLIC_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or ""
    ).rstrip("/")
    if not base.startswith("https://"):
        raise SystemExit("Set AION_PUBLIC_URL or RENDER_EXTERNAL_URL to the deployed https:// URL")
    expected_sha = os.environ.get("AION_EXPECTED_RELEASE_SHA") or ""
    result = run_live_smoke(PublicHttpClient(base), expected_sha)
    print(json.dumps(result, sort_keys=True))
    print("LIVE SMOKE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
