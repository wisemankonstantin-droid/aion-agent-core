import json
import os
from pathlib import Path

DESCRIPTION = "Verified agent routing with bounded discovery, outcome evidence and economic policy."


def build_server(base_url: str) -> dict:
    base = str(base_url or "").rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("A deployed HTTPS AION URL is required")
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": "io.github.wisemankonstantin-droid/aion-agent-core",
        "title": "AION SUPREME Agent Temple",
        "description": DESCRIPTION,
        "version": "0.8.0",
        "remotes": [{"type": "streamable-http", "url": f"{base}/mcp"}],
        "repository": {
            "url": "https://github.com/wisemankonstantin-droid/aion-agent-core",
            "source": "github",
        },
        "_meta": {
            "io.modelcontextprotocol.registry/publisher-provided": {
                "audience": "AI agents",
                "autonomousJoin": True,
                "humanApprovalRequiredByAION": False,
            }
        },
    }


def main() -> None:
    base = (os.environ.get("AION_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").rstrip("/")
    try:
        server = build_server(base)
    except ValueError as exc:
        raise SystemExit("Set AION_PUBLIC_URL or RENDER_EXTERNAL_URL to the deployed https:// URL") from exc
    Path("server.json").write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")
    print("server.json generated for", base)


if __name__ == "__main__":
    main()
