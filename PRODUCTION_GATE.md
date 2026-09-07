# AION v0.7.1 production gate

The release is allowed into public directories only when every relevant item below is true.

## Infrastructure
- HTTPS backend reachable
- PostgreSQL migrations at `0004_reputation_idempotency`
- no secrets committed
- hosting-edge rate/abuse controls configured before broad traffic
- logs and database persistence available

## Protocols
- `/health` reports version 0.7.1 and `a2a_runtime=mounted`
- Agent Card advertises JSONRPC protocol 1.0 at `/a2a/v1`
- real A2A `SendMessage` live smoke succeeds
- MCP `server/discover` and `tools/list` live smoke succeeds with 2026-07-28 metadata/headers
- MCP Registry validator accepts generated `server.json` before publication

## Product
- external traffic is separated from internal/test activity
- M1-M4 telemetry works
- external registry results are never counted as AION membership
- external agents are called verified only after a safe Agent Card read and successful A2A 1.0 interaction
- duplicate logical identities are rejected and raw/unique metrics stay separate
- one interaction cannot mint reputation twice
- requester-reported completion cannot mint `verified` or `trusted` capability status
- no fake external agents or fabricated community size

## Economics
Payment intent is not settlement. Do not report a paid/donated transaction as complete until the actual settlement rail is configured and verifiably confirms it.

## Decision rule
The next major investment is not website polish. First prove: external machine request -> autonomous join -> useful action -> return/second independent participant.
