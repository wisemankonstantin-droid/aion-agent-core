# Registry launch sequence v0.6

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
1. public HTTPS + PostgreSQL
2. live smoke pass
3. generate `server.json`
4. MCP Registry validation/publication
5. public A2A directory submission
6. permitted targeted invitations to compatible agents
7. observe M1 -> M2 -> M3 -> M4
8. fix the first measured bottleneck before scaling acquisition
