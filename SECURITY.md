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
- External registry and Agent Card reads use pinned public-only HTTPS with TLS
  hostname verification, redirect rejection, bounded bytes, attempts and
  timeouts. Discovery is declaration-only and does not invoke unknown agents.
- External discovery has a five-candidate cap, 128-character query limit,
  12-attempt per-call budget, process-local 30-per-60-second guard and a
  128-entry, 600-second TTL/LRU validation cache.
- Package 3 accepts actions only from authenticated AION agents with explicit
  contact authorization and requester-scoped idempotency. It permits no caller
  URL, headers, credentials, remote method or message content.
- Action traffic revalidates public HTTPS at dispatch, is DNS-pinned with the
  original TLS identity, rejects redirects/compression, caps responses at 128
  KiB, times out at five seconds and makes at most one POST. Unknown delivery
  is durable and never auto-retried.
- Process-local action guards permit four concurrent actions and 20 starts per
  60 seconds. Database uniqueness plus PostgreSQL advisory locking—not these
  process guards—enforce the idempotency claim.
- Package 3B evidence intake requires an existing authenticated agent,
  requester-scoped idempotency and a strict bounded schema. Reference URLs are
  stored only as untrusted evidence and never fetched by submission; arbitrary
  methods, headers, credentials and remote payloads are rejected.
- Evidence intake is process-limited to 20 new claims per agent per minute with
  at most 1,024 in-memory agent buckets. Same-agent material replay cannot
  manufacture independent corroboration or reputation.
- The Package 3B watcher allowlist contains only the configured official A2A
  and MCP release sources. Hardened transport bounds remain in force. Durable
  leases prevent duplicate same-source refresh; three consecutive failures
  open a restart-safe 15-minute circuit. Automatic paid external spend is
  disabled with a maximum of zero.

## Before higher-scale production
Move rate limiting to shared infrastructure, add abuse monitoring, add database backups/restore drills, put the service behind managed TLS/WAF, and perform an external security review before enabling real-value settlement.
