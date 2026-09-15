"""Bounded interoperability proof using the official MCP Python SDK v2 client.

Run against an isolated local AION HTTPS server. This script creates only a
throwaway local test identity so it can prove an authenticated MCP tool call.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


BASE_URL = os.environ.get("AION_INTEROP_BASE_URL", "https://127.0.0.1:8765").rstrip("/")
MCP_URL = f"{BASE_URL}/mcp"
EXPECTED_PROTOCOL = "2026-07-28"


def _structured(result) -> dict:
    data = getattr(result, "structured_content", None)
    if not isinstance(data, dict):
        raise AssertionError("official MCP client did not expose structuredContent")
    return data


async def _client(headers: dict[str, str] | None = None):
    http_client = httpx2.AsyncClient(
        headers=headers or {},
        verify=False,
        timeout=httpx2.Timeout(30.0, read=60.0),
    )
    transport = streamable_http_client(
        MCP_URL,
        http_client=http_client,
        terminate_on_close=False,
    )
    return http_client, Client(transport)


async def main() -> None:
    http_client, client = await _client()
    async with http_client:
        async with client:
            assert client.protocol_version == EXPECTED_PROTOCOL

            listed = await client.list_tools()
            names = {tool.name for tool in listed.tools}
            assert "get_live_utility" in names
            assert "join_aion" in names
            assert "who_am_i" in names

            utility = await client.call_tool(
                "get_live_utility",
                {
                    "subject": "mcp",
                    "context": {
                        "supported_protocols": ["mcp"],
                        "supported_protocol_versions": {"mcp": [EXPECTED_PROTOCOL]},
                    },
                },
            )
            assert not utility.is_error
            utility_data = _structured(utility)
            assert utility_data.get("membership_required") is False

            external_id = f"official-mcp-interop-{uuid.uuid4().hex}"
            joined = await client.call_tool(
                "join_aion",
                {"external_id": external_id, "name": "Official MCP Interop Probe"},
            )
            assert not joined.is_error
            joined_data = _structured(joined)
            key = joined_data.get("agent_key")
            assert isinstance(key, str) and key.startswith("aion_")
            assert joined_data["agent"]["external_id"] == external_id

    auth_http_client, auth_client = await _client({"Authorization": f"Bearer {key}"})
    async with auth_http_client:
        async with auth_client:
            assert auth_client.protocol_version == EXPECTED_PROTOCOL
            identity = await auth_client.call_tool("who_am_i", {})
            assert not identity.is_error
            identity_data = _structured(identity)
            assert identity_data["external_id"] == external_id

    print("official MCP interop: server/discover + tools/list + public utility + authenticated tool: PASS")


if __name__ == "__main__":
    asyncio.run(main())
