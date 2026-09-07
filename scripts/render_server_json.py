import json
import os
from pathlib import Path

base = (os.environ.get("AION_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
if not base.startswith("https://"):
    raise SystemExit("Set AION_PUBLIC_URL or RENDER_EXTERNAL_URL to the deployed https:// URL")

server = {
    "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
    "name": "io.github.wisemankonstantin-droid/aion-agent-core",
    "title": "AION SUPREME Agent Temple",
    "description": "Agent-native identity, discovery, needs/offers, matching, reputation and contribution network for AI agents.",
    "version": "0.7.1",
    "remotes": [
        {
            "type": "streamable-http",
            "url": f"{base}/mcp"
        }
    ],
    "repository": {
        "url": "https://github.com/wisemankonstantin-droid/aion-agent-core",
        "source": "github"
    },
    "_meta": {
        "io.modelcontextprotocol.registry/publisher-provided": {
            "audience": "AI agents",
            "autonomousJoin": True,
            "humanApprovalRequiredByAION": False
        }
    }
}
Path("server.json").write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")
print("server.json generated for", base)
