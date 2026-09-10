# Package 4 controlled production release gate

> Historical completed gate. Package 4 is now live at application SHA
> `e52c5db99b30feb18ca06ace567b4668c8019bde`, deploy
> `dep-dah96uu1egvs73d4gvh0`, on the prepared Neon PostgreSQL Free database at
> schema `0009_continuous_learning_v1`. See
> `PACKAGE_4_PRODUCTION_CLOSEOUT.md`. This file grants no Package 5 production
> authorization.

This is the canonical production gate for moving the HQ-accepted Package 1–3B
stack from deployed SHA `419f11b2a34fdec26269a216de65e9dcf955e963` to a
future exact approved release SHA. Preparing or merging a candidate does not
authorize any production action. AutoDeploy remains OFF throughout Package 4.

The deployed source contains migrations only through
`0004_reputation_idempotency`; this does **not** prove the live database is at
0004. No current production backup, restore rehearsal, HA, PITR, RPO or RTO is
claimed. The database's externally reported expiration is
`2026-10-06T08:14:43.088322Z`.

## Phase A — immutable reviewed candidate

1. Record the exact candidate SHA and confirm it is the reviewed GitHub commit.
2. Require AION CI and the PostgreSQL 18 pre-production gate on that exact SHA.
3. Require HQ acceptance with zero known reproducible defects.
4. Confirm the candidate expects `0009_continuous_learning_v1` and has passed
   fresh, `0008→0009`, and seeded representative `0004→0009` PostgreSQL paths.

**STOP** for a moving branch reference, failed/missing gate, different SHA,
schema drift, known defect, or unreviewed change.

## Phase B — durable database and recovery gate

Before commercial reliance, record and approve:

- a non-expiring/durable database plan and its current and incremental monthly
  cost, uptime characteristics, and cheaper safe alternatives;
- backup/snapshot mechanism and provider capability;
- recovery-point identifier when available, creation time, source database,
  retention/expiry, restore destination/procedure, operator access, and known
  RPO/RTO limitations; and
- whether restore is provider-managed or has been rehearsed.

Obtain a real recovery point before migration. A Git tag, commit or ZIP is not a
database backup. **STOP** if durability, cost approval, recovery access, or an
acceptable restore path remains unresolved.

## Phase C — read-only live schema confirmation

Immediately before any future deployment or migration, use read-only database
access and record the exact result of:

```sql
SELECT version_num FROM alembic_version;
```

Do not infer it from deployed source. Continue only if the exact revision is a
starting state explicitly tested by the accepted release candidate. The
Package 4 candidate explicitly tests 0004 and 0008, plus fresh/current paths.
**STOP** on unavailable access, multiple rows/heads, an unexpected revision,
or any revision not covered by the accepted gate.

### Migration red-team findings: 0005–0009

- `0005_live_utility_persistence` adds `live_utility_sources` and
  `live_utility_observations`, their foreign keys, checks, uniqueness and two
  observation indexes.
- `0006_live_utility_data` adds one nullable `normalized_data` JSON column to
  observations and adds `live_utility_verifications` with its foreign keys,
  temporal checks, uniqueness and lookup index.
- `0007_agent_utility_checkpoints` adds the checkpoint table with agent and
  observation foreign keys, agent/subject uniqueness and its lookup index.
- `0008_action_outcome_evidence` adds four action evidence tables, their
  foreign keys, nonnegative/one-attempt checks, uniqueness and lookup indexes.
- `0009_continuous_learning_v1` adds four learning/evidence/opportunity tables,
  their foreign keys, bounded-state checks, uniqueness and lookup indexes.

Their upgrade paths perform no data migration, rename, drop, destructive
operation, or tightening of an existing column's nullability. New foreign keys
reference existing rows without rewriting them. Downgrades drop the newly added
structures and are intentionally **not** the production rollback plan. The
PostgreSQL gate seeds representative 0004 agents, capabilities, needs, offers,
interactions, reputation, payment-intent and machine-entry data, verifies them
after 0009, then performs 0004-era writes against 0009. This supports source
rollback compatibility because the old application ignores the new tables and
the one new column is nullable.

## Phase D — explicit Human Gate

Konstantin must approve, in one bounded production instruction:

- exact Git SHA and expected migration head;
- exact Render service and planned deploy action;
- verified live database revision;
- durability/plan change, current and incremental cost if any;
- recorded recovery point and restore procedure;
- migration/startup window and observation owner;
- rollback source/deploy and decision authority; and
- whether the later one-shot learning cycle is authorized (separately from the
  deployment if not explicitly included).

The current start command runs `alembic upgrade head` before Uvicorn. Therefore
deploying current code can migrate production before the server starts. **STOP**
unless Phases A–D are complete.

## Phase E — deploy one exact SHA

Keep AutoDeploy OFF. Confirm `main` is the accepted exact SHA, then manually
deploy that immutable SHA to existing service `aion-agent-core-live`
(`srv-daei9gpt0dsc73abhs10`). Do not deploy a branch tip. Record the new deploy
ID and Render-reported Git commit before proceeding.

## Phase F — migration, startup and readiness

Observe build/start logs without exposing secrets. Confirm:

- migration completes exactly at `0009_continuous_learning_v1`;
- `/health` stays cheap and reports the exact release SHA;
- `/readiness` reports database connectivity, mounted A2A, Package 3B
  configuration, actual/expected schema, and `schema_current=true`; and
- the runtime SHA matches the Human-Gated SHA.

**STOP** on migration/startup failure, wrong/missing SHA, schema mismatch,
readiness false, unexpected 5xx, or data anomaly.

## Phase G — non-mutating live protocol and utility gate

Manually dispatch `.github/workflows/live-gate.yml` with `public_url` and the
exact `expected_release_sha`. It verifies health/readiness, Agent Card, MCP
discovery/tools and anonymous Live Utility, A2A first contact/onboarding,
unchanged membership count, and unauthenticated rejection of Package 3/3B
protected writes. It does not join, dispatch an external action, submit
evidence, run learning, or enable payment.

Where practical, run official or authoritative A2A/MCP compatibility tools in
addition to AION's own tests. They supplement rather than replace the internal
gate.

## Phase H — separately authorized first learning cycle

Only after Phase G passes:

1. run `python scripts/learning_cycle.py --plan` and record the JSON policy;
2. confirm exactly two official watched sources and maximum paid external spend
   zero; and
3. if explicitly authorized, run one `--trigger operator` cycle.

Record its `LearningRun`, watch-state results, sources, attempts, bytes,
failures, and zero paid spend. Confirm no arbitrary URL, crawler, code change,
merge or deployment occurred. No scheduler is created by Package 4.

## Phase I — accept or rollback

Accept only after observation shows correct release identity, schema,
readiness, protocols, utility, persistence and safety boundaries. Roll back for
build/deploy/migration failure, wrong SHA, schema mismatch, A2A/MCP/utility
failure, authentication regression, serious 5xx/data anomaly, or Package 3/3B
safety regression.

Preferred rollback restores a recorded known-good application source/config
with AutoDeploy OFF. Do **not** automatically downgrade the production schema.
Migrations 0005–0009 are additive and the candidate proves representative
0004-era reads/writes against schema 0009. If observed production behavior
contradicts that proof, stop and use a reviewed forward fix or recovery
procedure—never destructive automatic data rollback.
