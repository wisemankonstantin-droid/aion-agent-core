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

Names only: DATABASE_URL, AION_PUBLIC_URL, RENDER_EXTERNAL_URL, AION_REQUIRE_A2A,
AION_JOIN_RATE_PER_MINUTE, AION_MCP_RATE_PER_MINUTE,
AION_EXTERNAL_DISCOVERY_TIMEOUT, AION_RETURN_THRESHOLD_MINUTES,
AION_ALLOWED_ORIGINS, AION_DISABLE_EXTERNAL_DISCOVERY, PYTHON_VERSION, PORT.
The last two are deployment settings. .env.example has no values. Do not load
blank numeric variables; leave optional settings absent for defaults.

Offline heuristic scan covers tracked/new files, nested ZIP members and all
historical unique blobs for recognizable provider tokens, private keys,
credential URLs and literal secrets. Initial result: zero findings, three
historical blobs. Values are never printed. This is defense in depth, not a
guarantee against arbitrary unrecognizable credentials. Ignore rules protect
environment files, databases, virtualenvs and key files. No live secret values
were retrieved. Live environment names require the pending Render selection.

## Production compatibility: critical drift

Public health and readiness report 0.7.1, healthy database and mounted A2A.
Production exposes newer routes, including /identity-resolution, /first-contact,
/offers/canonical, /needs/canonical, /version and /readiness. Recovered 0.6.2
is therefore not equivalent to the current production application.

The ZIP's DEPLOY_RENDER.md described auto-deploy from GitHub with ZIP extraction;
current Dashboard settings are unverified. Render MCP requires explicit user
confirmation of My Workspace before inspection. No production change was made.
Keep this normalization branch isolated until newer source is recovered.
See DEPLOY_RENDER.md for target commands, cutover and rollback limitations.

Live funnel snapshot: 302 machine-entry requests, 2 raw identity/activation rows,
1 returning row, 1 estimated unique external activated/returning agent and 1
duplicate identity row. These are reported estimates, not independent proof of
adoption. Public probes may increase request telemetry; no agents were created.

## Tests and limitations

- Untouched archive baseline: 40 passed, 1 failed. A2A test expected result.parts;
  pinned SDK source wraps the response in result.message. Corrected the test,
  preserving backend behavior; strengthened the live smoke response assertion.
- Normalized source: 42 passed, no skips, with AION_REQUIRE_A2A=1.
- New startup test: fresh Alembic upgrade, repeated upgrade, schema check, real
  Uvicorn startup, mounted A2A and empty-database stats.
- Readiness: 24/24; pip check: no broken requirements.
- Live smoke: public GET routes respond, but version gate rejects 0.7.1 when
  0.6.2 is expected. It stops before live protocol POSTs. Do not weaken this gate
  to conceal source drift.
- Upstream deprecation warnings remain. Docker is unavailable locally;
  PostgreSQL migration compatibility and Linux CI are not implied by SQLite tests.

No new product features were introduced. The next critical task is source and
deployment reconciliation with production 0.7.1, followed by identity/A2A work.

## Publication outcome

The second clean Python 3.12 environment installed successfully with artifact
hash verification; all 42 tests passed there as well. Git diff whitespace check
passes. One inherited trailing space in a migration docstring was removed.

Local git commit and backup tag exist. Remote publication was attempted through
both normal git and the connected GitHub API. Git has no authenticated credential;
the connector's create_branch call returned HTTP 403 `Resource not accessible
by integration`. Repository metadata push/admin flags do not override that
integration permission restriction. No remote modifications or PR were created.
Post-push remote reread and GitHub Actions validation are therefore pending.

USER BLOCKER: authenticate git for this repository or grant the connected GitHub
integration repository content write permission (workflow writes are also needed
for .github/workflows). Render workspace confirmation is separately pending.
