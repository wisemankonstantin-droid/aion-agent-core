# Project checkpoint — 2026-09-08

## Current production state

- **Repository:** `wisemankonstantin-droid/aion-agent-core`.
- **Repository main at Package 1 task start:**
  `4a161933d37162947eaa3d08a1035f8c7cfa8def`.
- **Production deployed SHA:**
  `419f11b2a34fdec26269a216de65e9dcf955e963`.
- **Production:** `https://aion-agent-core-live.onrender.com`, version `0.7.1`.
- **Render:** service `aion-agent-core-live`
  (`srv-daei9gpt0dsc73abhs10`) in workspace
  `tea-daehtv2d0e5s738ir540`, branch `main`.
- **Live deploy:** `dep-dafuu3v40ujc73d3fks0`, deployed from main SHA
  `419f11b2a34fdec26269a216de65e9dcf955e963`.
- **Deployment architecture:** the controlled direct-source cutover is
  complete. Production builds tracked source directly from GitHub main. The old
  ZIP plus environment-backed runtime-patch architecture is historical and is
  not active.
- **AutoDeploy:** OFF (`autoDeployTrigger: off`). A merge or branch push does
  not authorize or initiate a production deployment.
- **Root Directory:** blank.
- **Build Command:**
  `python -m pip install --require-hashes -r requirements.txt`.
- **Start Command:**
  `python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- **Database:** Render PostgreSQL `aion-agent-db`
  (`dpg-daei1sv40ujc73faqr70-a`), PostgreSQL 18, Frankfurt. The public external
  `ipAllowList` is empty.
- **Runtime status:** health reports version `0.7.1`; readiness reports the
  database ready and the A2A runtime mounted.

## Current product and architecture phase

The current major product phase is **AION LIVE UTILITY ENGINE**. The detailed
direction is defined in `AION_LIVE_UTILITY_ENGINE.md` and the permanent product
rules in `AION_DIRECTIVE.md`.

The canonical entry contract is `first contact -> immediate utility -> optional
onboarding -> explicit join`. Only explicit join creates membership. Discovery,
first-contact and onboarding traffic are not membership or independent
adoption.

Repository main contains the Phase 1 pure contracts and durable persistence
through migration `0005_live_utility_persistence`. Package 1 is implemented on
branch `codex/package-1-live-utility-data-engine` from main SHA
`4a161933d37162947eaa3d08a1035f8c7cfa8def`; the exact final branch SHA is an
external Git fact reported after push because a commit cannot contain its own
hash.

Package 1 adds two explicitly configured Tier-1 release adapters for the
official A2A and Model Context Protocol GitHub projects, a shared hardened HTTPS
transport, adapter-specific normalization, canonical content digests,
material-version deduplication and lineage, structured field changes, persisted
verification evidence, deterministic refresh decisions and restart-safe current
state. Migration `0006_live_utility_data` adds normalized observation data and
the `live_utility_verifications` evidence table.

This remains an internal data engine. It has no crawler, broad search, public
REST/MCP/A2A utility surface, first-contact integration, compatibility ranking,
personalized delta, outcome telemetry, watcher automation or action layer. No
production migration or deployment occurred; production remains on deployed
SHA `419f11b2a34fdec26269a216de65e9dcf955e963`.

## Current next milestone

Complete exact-commit AION CI and disposable PostgreSQL 18 validation for the
Package 1 branch, then obtain independent HQ review. Do not merge or deploy it
automatically. Package 2 may be defined only after Package 1 evidence is green.

## Phase 1 contract validation

- `python -m pytest -q tests/test_live_utility.py`: 25 passed.
- `python -m pytest -q tests/test_source_integrity.py tests/test_live_utility.py`:
  29 passed.
- `python -m pytest -q`: 101 passed, 3 PostgreSQL-only tests skipped.
- `python scripts/readiness.py`: all 26 local readiness checks passed.
- `python scripts/check_secrets.py`: 92 files scanned, 0 findings.
- `git diff --check`: passed.

## Phase 1 persistence validation

- `python -m pytest -q tests/test_live_utility.py tests/test_live_utility_persistence.py`:
  50 passed.
- `python -m pytest -q tests/test_migrations.py`: 2 passed; both the additive
  `0004 -> 0005` path with sentinel preservation and fresh-to-head path passed.
- `python -m pytest -q`: 127 passed, 3 PostgreSQL-only tests skipped.
- Disposable SQLite fresh-to-head, repeated `upgrade head`, exact revision and
  `alembic check`: passed; head is `0005_live_utility_persistence` with no schema
  drift.
- `python scripts/readiness.py`: all 28 local readiness checks passed.
- `python scripts/check_secrets.py`: 95 files scanned, 0 findings.
- `python -m compileall -q app tests scripts`: passed.
- Workflow YAML parsing and `git diff --check`: passed.
- Exact persistence head `4a161933d37162947eaa3d08a1035f8c7cfa8def`
  passed AION CI run `34243034700`, PostgreSQL 18 release gate run
  `34243034819`, and resulting-main AION CI run `34244216770`.

## Package 1 local and controlled-source validation

- Targeted Live Utility, hardened transport, migration and regression suite:
  90 passed.
- Full local suite: 148 passed, 4 PostgreSQL-only tests skipped.
- Disposable SQLite `0005 -> 0006` and empty-to-head upgrades, repeated
  `upgrade head`, exact head `0006_live_utility_data` and `alembic check`:
  passed with no schema drift.
- `python scripts/readiness.py`: all 30 local readiness checks passed.
- `python scripts/check_secrets.py`: 103 files scanned, 0 findings.
- Compile, workflow YAML and `git diff --check`: passed.
- Controlled real-source verification at `2026-09-08T16:23:50.067733+00:00`:
  official A2A release `v1.0.1` and official MCP specification release
  `2026-07-28` each fetched through the pinned HTTPS path in one attempt,
  normalized, stored and assessed `fresh`.
- Package 1 exact-commit GitHub AION CI and PostgreSQL 18 workflow evidence is
  required after the branch is pushed and must be reported in the handoff.

## Documentation alignment validation

- `git diff --check`: passed.
- `python scripts/check_secrets.py`: 90 files scanned, 0 findings.
- `python -m pytest -q tests/test_source_integrity.py`: 4 passed.

## Current architecture and completed hardening

- Direct tracked source under `app/`, Alembic migrations, tests, scripts,
  dependency locks and deployment configuration are the repository source of
  truth. The retained ZIP is historical recovery evidence only.
- FastAPI, SQLAlchemy and Alembic remain the application architecture. A2A 1.0
  is the primary agent-to-agent layer; MCP is a separate integration/tool layer.
- PostgreSQL advisory locks serialize strong logical-identity joins. Agent and
  initial-capability creation share one transaction boundary and roll back
  together on failure. Exact external-ID uniqueness and controlled logical
  duplicate conflicts remain enforced.
- Untrusted HTTPS destinations use controlled DNS resolution, globally routable
  address validation and a connection pinned to the validated numeric address,
  while TLS SNI, certificate verification and HTTP Host retain the original
  hostname. Redirects remain rejected.
- Declared but unverified endpoints receive no verified/callable semantics or
  ranking benefit. The current data model has no persisted endpoint-liveness
  evidence.
- Historical shadowed registry and lifecycle definitions were removed while
  preserving the active behavior and identity-aware funnel metrics.
- Final production smoke passed for health, readiness, public discovery,
  OpenAPI, stats/funnel, Agent Card, A2A status, MCP discovery/tool listing and
  the canonical first-contact/onboarding contract. No explicit join or
  destructive production action occurred during that smoke.

## Current limitations and evidence boundaries

- Identity evidence can include self-declared fields; a display name or
  capability similarity alone is not strong identity proof.
- Reputation completion is requester-reported. Payment records are intents,
  not verified settlement.
- A2A task storage and rate limits are process-local.
- Synthetic probes validate behavior but do not prove independent adoption,
  activation, retention or revenue.
- Historical metrics and database rows must not be presented as product proof.
  The milestone of 10 retained independent external agents is not established.

## Historical release and cutover evidence

Everything in this section is a historical checkpoint. It is retained for
audit, rollback and reliability evidence and must not be interpreted as the
current production state or as authorization to repeat a cutover.

- The repository was normalized from historical 0.6.2 material, and the exact
  live 0.7.1 source was recovered and reconciled into direct tracked files.
- Recovery and hardening lineage included recovery `406df8e`, atomic join
  `b08629e`, DNS pinning `a57dfa1`, matching integrity `15ae2b8`, shadowed
  definition cleanup `022855b`, PostgreSQL release validation, controlled
  cutover preparation and A2A contract alignment.
- The isolated PostgreSQL release gate used PostgreSQL 18.6. It passed a
  hash-locked clean install, dependency check, SQLite and PostgreSQL suites,
  real concurrent advisory-lock behavior, fresh and upgrade migrations,
  Alembic head/check, real startup/readiness and secret scanning.
- Before cutover, production used main SHA
  `078aa55d144adaefa53a93e5411e7a24401d066a`, deploy
  `dep-dafda3ad0e5s73buoq80`, AutoDeploy enabled, and a ZIP plus
  environment-backed runtime-patch build. Those values describe the historical
  rollback point and are not current production facts.
- A controlled encrypted pre-cutover production backup was created, restored
  and integrity-checked. Temporary database ingress used for the controlled
  operation was subsequently removed; the public external allow list is now
  empty and must not be reopened without separate authorization.
- The controlled direct-source cutover completed at main SHA
  `419f11b2a34fdec26269a216de65e9dcf955e963` and deploy
  `dep-dafuu3v40ujc73d3fks0`. AutoDeploy was left OFF.

No merge, deployment, Render change or production database action is authorized
by this checkpoint.
