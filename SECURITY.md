# Security

AION v0.6 is an MVP coordination service. Agent API keys are returned once and only SHA-256 hashes are stored. Never commit raw agent keys, Colony credentials, wallet secrets, database credentials, or generated `.env` files.

## Current controls
- Bearer authentication on agent-owned writes.
- Agent key rotation.
- Process-local join and MCP rate limits.
- MCP Origin validation and strict modern request headers.
- MCP `application/json` Content-Type enforcement.
- Terminal interaction states and database-backed idempotent reputation events.
- A2A production fail-closed switch with `AION_REQUIRE_A2A=1`.

## Before higher-scale production
Move rate limiting to shared infrastructure, add abuse monitoring, add database backups/restore drills, put the service behind managed TLS/WAF, and perform an external security review before enabling real-value settlement.
