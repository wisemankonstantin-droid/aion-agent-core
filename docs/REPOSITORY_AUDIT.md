# Repository normalization audit — 2026-09-07

## Original GitHub state

Repository: wisemankonstantin-droid/aion-agent-core (public). Authenticated connector
reports push/admin permission. Default and only remote branch at clone: main.
Clean checkout at 078aa55. Tracked files: README.md containing only
`AION Agent Core`, and AION_Agent_Core_v0.6.0.zip.

Recent history (all available commits):

- 078aa55, 2026-09-06: Add files via upload.
- f09b597, 2026-09-06: Add files via upload.
- 80a5f58, 2026-09-06: Update README title to 'AION Agent Core'.

Backup: git tag backup/pre-normalization-20260907 at 078aa55.
Normalization work is isolated on codex/normalize-repository.

## Archive and actual architecture

ZIP SHA-256: `5927cc038ca6bf0326f001b2dad4b0924ef43fc60332b029ddda5515c0741e1e`.
66 regular files under AION_Agent_Core_v0.6.0/. VERSION, app.main.APP_VERSION
and README identify 0.6.2. Every extracted file was byte-identical to its archive
member before normalization edits. app/ remains byte-identical; alembic/ differs
only by removal of trailing whitespace in the initial migration's docstring.
No runtime database or populated .env was bundled. Complete path/size/hash
inventory is in archive-inventory.json. The original ZIP is retained unchanged.

Backend: FastAPI entry point app.main:app, SQLAlchemy persistence, Alembic head
0004_reputation_idempotency. SQLite local default, normalized PostgreSQL URLs
for psycopg in deployed environments. REST API, A2A SDK integration and separate
MCP JSON-RPC tool endpoint share services for joining/matching/lifecycle.
No separate frontend exists in this release. Existing tests cover identity keys,
authenticated writes, capabilities, needs/offers/matching, interaction completion,
reputation idempotency, telemetry, MCP envelopes and A2A join.

All Python files were syntax-inspected; environment reads, route declarations,
models, services, migration scripts, workflows and deployment documents were
examined. Archived release claims are historical statements, not independently
verified facts. SHA256SUMS.txt and RELEASE_MANIFEST.json remain historical archive
metadata, not current-tree attestations.

## Dependencies and startup

Nine direct requirements already used exact pins; transitive dependencies were
unlocked. requirements.in preserves those pins, and requirements.txt now uses a
universal uv-generated resolution with artifact hashes and platform markers.
Python 3.12 is the validation target. The original SDK is retained at 1.1.2.
Build/start paths reference repository-root source, never unzip. Docker's Python
base tag is still mutable; this is not a claim of bit-identical OS images.

## Environment and secret checks

Repository/runtime names: DATABASE_URL, AION_APP_VERSION, AION_PUBLIC_URL,
RENDER_EXTERNAL_URL, AION_REQUIRE_A2A, AION_JOIN_RATE_PER_MINUTE,
AION_MCP_RATE_PER_MINUTE, AION_EXTERNAL_DISCOVERY_TIMEOUT,
AION_RETURN_THRESHOLD_MINUTES, AION_ALLOWED_ORIGINS,
AION_DISABLE_EXTERNAL_DISCOVERY, AION_OPERATED_EXTERNAL_IDS, PYTHON_VERSION and
PORT. `.env.example` has no values. Do not load blank numeric variables; leave
optional settings absent for defaults.

The live service additionally retains historical source-patch variable names:
AION_COMPOSITE_SMOKE, AION_ENABLE_FIRST_CONTACT, AION_FIRST_CONTACT_PATCH,
AION_PATCH_B64, AION_V42_PATCH, AION_V4_DELTA, AION_V5_DELTA and AION_V6_DELTA.
Their output has been recovered into direct files, so the reconciled build does
not require these source carriers.

Offline heuristic scan covers tracked/new files, nested ZIP members and all
historical unique blobs for recognizable provider tokens, private keys,
credential URLs and literal secrets. Initial result: zero findings, three
historical blobs. Values are never printed. This is defense in depth, not a
guarantee against arbitrary unrecognizable credentials. Ignore rules protect
environment files, databases, virtualenvs and key files. Source-patch values
were used only for recovery in an untracked workspace; database and credential
values were not read or copied.

## Production compatibility: recovered and awaiting review

Public health and readiness report 0.7.1, healthy database and mounted A2A.
Authenticated read-only Render inspection established the live service, linked
Git commit, deploy ID, Python version, commands, environment names and database
resource. The exact ZIP-plus-patch build chain was recovered and reproduced in
an isolated tree. Its output is now direct source on
`codex/recover-production-0.7.1`; it has not been merged or deployed.

The recovered delta adds identity resolution, duplicate protection, first
contact, canonical needs/offers, unique external funnel metrics, structured
matching and verified external A2A interaction. Models and migrations are
unchanged at head 0004. See `PRODUCTION_RECOVERY_0.7.1.md` for provenance,
classification and database evidence.

Live funnel snapshot: 302 machine-entry requests, 2 raw identity/activation rows,
1 returning row, 1 estimated unique external activated/returning agent and 1
duplicate identity row. These are reported estimates, not independent proof of
adoption. Public probes may increase request telemetry; no agents were created.

## Tests and limitations

- Untouched archive baseline: 40 passed, 1 failed. A2A test expected result.parts;
  pinned SDK source wraps the response in result.message. Corrected the test,
  preserving backend behavior; strengthened the live smoke response assertion.
- Normalized 0.6.2 source: 42 passed, no skips, with AION_REQUIRE_A2A=1.
- Reconciled 0.7.1 source: 50 passed, including identity/deduplication,
  canonical rows, matching v1, first contact, external validation and a
  forward migration path. The first run exposed stale 0.6.2 assertions and an
  A2A attribution spoof regression; both were corrected and covered.
- New startup test: fresh Alembic upgrade, repeated upgrade, schema check, real
  Uvicorn startup, mounted A2A and empty-database stats.
- Readiness: 24/24; pip check: no broken requirements.
- Live smoke now requires 0.7.1. It was not used to mutate production during
  source recovery; public read-only probes confirmed health/readiness/version.
- Upstream deprecation warnings remain. Docker is unavailable locally;
  PostgreSQL migration compatibility and Linux CI are not implied by SQLite tests.

No speculative product feature was introduced. Existing production behavior was
recovered, and one server-controlled A2A attribution invariant was restored.
The next gate is independent review; merge and deployment remain separate.

## Publication outcome

The second clean Python 3.12 environment installed successfully with artifact
hash verification; all 42 tests passed there as well. Git diff whitespace check
passes. One inherited trailing space in a migration docstring was removed.

GitHub CLI authentication is working through the Windows keyring as
`wisemankonstantin-droid`, and Git uses the GitHub CLI credential helper.
`codex/normalize-repository` was pushed successfully at
`cb79011583506b59ede4bba9f6be8144b3392333`. The remote branch SHA and all 77
tracked blob SHAs match the local commit. Required files were read back through
the GitHub API. No merge, default-branch update or deployment was performed.
