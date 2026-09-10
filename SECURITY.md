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
- Evidence intake is process-limited to 20 attempts per agent per minute with
  at most 1,024 in-memory agent buckets. The guard runs before evidence reads,
  so replay, idempotency-conflict and duplicate-material traffic is bounded.
  Shared-material database locking and canonical logical-identity counting
  prevent duplicate raw rows or concurrent submissions from manufacturing
  independent corroboration. AION-operated/test identities are excluded from
  independent commercial demand, and untrusted `observed_at` values cannot
  boost opportunity recency beyond AION receipt time.
- The Package 3B watcher allowlist contains only the configured official A2A
  and MCP release sources. Hardened transport bounds remain in force. Durable
  leases prevent duplicate same-source refresh; three consecutive failures
  open a restart-safe 15-minute circuit. Automatic paid external spend is
  disabled with a maximum of zero.
- Package 4 release identity exposes only a validated 40-hex commit and its
  source. `RENDER_GIT_COMMIT` has precedence over the optional
  `AION_RELEASE_SHA` fallback; invalid values expose no SHA and unrelated
  environment values are never returned.
- `/health` performs no database, migration, learning or external-network work.
  `/readiness` reads database connectivity and `alembic_version`, verifies the
  expected `0010_package5_proof_v1` schema, mounted A2A runtime and fixed Package 3B policy, and
  never migrates, refreshes sources, runs learning or exposes credentials.
- The Package 4 Live Gate is manually dispatched with a public URL and exact
  expected SHA. Its protected action/evidence checks are unauthenticated
  rejection proofs; it supplies no credential and cannot dispatch or persist
  those operations.
- Package 5 participation is never promoted by client-controlled attribution.
  Only a guarded operator-reviewed assessment can mark a canonical logical
  identity countable, while configured internal/test exclusions apply across
  every duplicate raw row. The assessment surface is not exposed over REST,
  MCP or A2A and stores only digests of its bounded evidence reference and
  summary.
- Package 5 VUO intake is bearer-authenticated, requester/canonical-identity
  scoped, idempotent and limited by database uniqueness. It references the
  existing Package 3 action/outcome/verification records and accepts only fixed
  V1 semantic evidence values—no URL, method, credential, remote body, cost or
  client timestamp. The outer 64 KiB streaming request limiter applies.
- Package 5 return evidence uses a later distinct durable ActionRun and server
  timestamps. It does not use `last_seen_at`, status/telemetry/machine-entry
  traffic or client time. The proof read model is capped at 500 raw identity
  rows, 500 logical identities and 5,000 VUO candidates and fails closed
  beyond any bound.
- Package 5B adds shared public guidance only. It does not accept credentials in
  A2A content, expose an A2A protected-action/VUO-write adapter, weaken REST/MCP
  Bearer authentication or make public reads mutate Package 5 evidence.

## Before higher-scale production
Move rate limiting to shared infrastructure, add abuse monitoring, add database backups/restore drills, put the service behind managed TLS/WAF, and perform an external security review before enabling real-value settlement.
