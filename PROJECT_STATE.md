# Project checkpoint — 2026-09-08

## Current production state

- **Repository:** `wisemankonstantin-droid/aion-agent-core`.
- **Main SHA:** `419f11b2a34fdec26269a216de65e9dcf955e963`.
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

This branch implements the Phase 1 pure internal contract slice: bounded source
registry contracts, immutable versioned source-observation/provenance contracts
and deterministic freshness evaluation. It has no persistence, crawler, remote
retrieval, public REST/MCP/A2A integration, compatibility ranking, personalized
delta, outcome telemetry, watchers or safe action layer. Do not scale
acquisition until an independent external agent obtains a useful current result,
completes a successful action and voluntarily returns. No production deployment
occurred for this contract-only branch.

## Current next milestone

Obtain independent review of the implemented Phase 1 contract slice. If it is
accepted, make a separately bounded persistence/data-model decision for:

- a bounded source registry;
- versioned observations with evidence and provenance; and
- freshness evaluation with explicit stale-state behavior.

Do not combine that decision with broad crawling, compatibility ranking,
personalized delta, outcome telemetry or external action. Any persistence
change requires a reviewed migration and the established database release gates.

## Phase 1 contract validation

- `python -m pytest -q tests/test_live_utility.py`: 25 passed.
- `python -m pytest -q tests/test_source_integrity.py tests/test_live_utility.py`:
  29 passed.
- `python -m pytest -q`: 101 passed, 3 PostgreSQL-only tests skipped.
- `python scripts/readiness.py`: all 26 local readiness checks passed.
- `python scripts/check_secrets.py`: 92 files scanned, 0 findings.
- `git diff --check`: passed.

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
