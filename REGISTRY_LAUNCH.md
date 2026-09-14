# Registry launch sequence for AION 0.8.0

Do not publish AION before a public HTTPS deployment passes `scripts/smoke_live.py`.

## MCP Registry
After deploy:
```bash
AION_PUBLIC_URL=https://YOUR-HOST python scripts/render_server_json.py
```
This creates `server.json` for the remote Streamable HTTP endpoint `/mcp`. Then use the current official MCP publisher flow to authenticate, validate and publish. Registry publication is an external/authenticated action, not a local code task.

## A2A directories
Submit the deployed AION URL/card only after `/a2a/status` reports `mounted` and the live `SendMessage` smoke passes. Track each directory separately and do not count a listing, card fetch or external search result as a joined AION agent.

## Launch order
1. HQ accepts one exact AION 0.8.0 candidate SHA.
2. A separate Human Gate authorizes manual production deployment.
3. Run the exact-SHA non-mutating live smoke against schema
   `0014_conversation_intel_v1`.
4. Validate registry metadata, then perform passive registry distribution only
   under separate publication authorization.
5. Run a separately authorized bounded demand pilot; coordinated responses are
   not independent adoption, VUO, payment or revenue.
6. Learn from real demand before adding only the quote/payment adapter evidence
   shows is required.

The repository `render.yaml` is not authoritative for current production and
must not be Blueprint-synchronized without a separate Human Gate.
