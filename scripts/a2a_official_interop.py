"""Bounded A2A 1.0 JSON-RPC interoperability proof using a2a-sdk 1.1.2."""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest
from a2a.utils.constants import TransportProtocol


BASE_URL = os.environ.get("AION_INTEROP_BASE_URL", "https://127.0.0.1:8765").rstrip("/")


async def main() -> None:
    async with httpx.AsyncClient(verify=False, timeout=30.0) as http_client:
        resolver = A2ACardResolver(http_client, BASE_URL)
        card = await resolver.get_agent_card()
        assert len(card.supported_interfaces) >= 1
        interface = next(
            item for item in card.supported_interfaces if item.protocol_binding == "JSONRPC"
        )
        assert interface.protocol_version == "1.0"
        assert interface.url == f"{BASE_URL}/a2a/v1"

        config = ClientConfig(
            httpx_client=http_client,
            supported_protocol_bindings=[TransportProtocol.JSONRPC],
            streaming=False,
        )
        client = await create_client(card, client_config=config)
        actual_transport = getattr(client, "_transport", client)
        assert actual_transport.__class__.__name__ == "JsonRpcTransport"

        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                message_id=str(uuid.uuid4()),
                parts=[Part(text=json.dumps({"action": "live_utility", "subject": "a2a"}))],
                context_id=str(uuid.uuid4()),
            )
        )

        response_payload = None
        async for event in client.send_message(request):
            if event.HasField("message"):
                response_payload = json.loads(get_message_text(event.message))
                break

        await client.close()

    assert isinstance(response_payload, dict)
    assert response_payload.get("membership_required") is False
    print("official A2A 1.0 JSONRPC interop: agent card + SendMessage + live utility: PASS")


if __name__ == "__main__":
    asyncio.run(main())
