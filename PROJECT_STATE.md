# Project checkpoint — 2026-09-09

## Current production state

- **Repository:** `wisemankonstantin-droid/aion-agent-core`.
- **Accepted Package 2 application baseline:**
  `88bc6fae247a5bb454d435380c24d665ba48f512`.
- **Post-Package-2 strategy alignment checkpoint:**
  `7fb469024855a065a1d42d12fc5c1a40d354ab6f`.
- **Accepted pre-Package-3 audit-correction checkpoint:**
  `d8465a17522044c0349609e44ac7ccd9f0facf82`.
- **Live repository state rule:** verify the current branch HEAD directly from
  GitHub. The verified GitHub ref wins over this durable checkpoint document;
  no field here claims that a commit contains its own future SHA.
- **Repository main at Package 2 task start:**
  `d5257c539dc2bf86411297aca8b787933a1bed42`.
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
  `ipAllowList` is empty. The current free plan externally reports an
  expiration date of **2026-10-06**. This is a mandatory Package 4 production-
  planning risk: durability, backup and reliable uptime must be resolved before
  AION is relied on as a commercial production service.
- **Runtime status:** health reports version `0.7.1`; readiness reports the
  database ready and the A2A runtime mounted.
- **Repository Alembic head:** `0007_agent_utility_checkpoints`.
- **Production boundary:** Package 2 has not been deployed or migrated in
  production. Production remains on the SHA above and AutoDeploy remains OFF.

## Current product and architecture phase

The current major product phase is **AION LIVE UTILITY ENGINE**. The detailed
direction is defined in `AION_LIVE_UTILITY_ENGINE.md` and the permanent product
rules in `AION_DIRECTIVE.md`.

The canonical entry contract is `first contact -> immediate utility -> optional
onboarding -> explicit join`. Only explicit join creates membership. Discovery,
first-contact and onboarding traffic are not membership or independent
adoption.

Package 0 is **Done**. Repository main contains the Phase 1 contracts, durable
persistence and the accepted Package 1 data engine through migration
`0006_live_utility_data`.
Package 1 is **Done**. It was independently reviewed and merged at main SHA
`d5257c539dc2bf86411297aca8b787933a1bed42`.

Package 1 adds two explicitly configured Tier-1 release adapters for the
official A2A and Model Context Protocol GitHub projects, a shared hardened HTTPS
transport, adapter-specific normalization, canonical content digests,
material-version deduplication and lineage, structured field changes, persisted
verification evidence, deterministic refresh decisions and restart-safe current
state. Migration `0006_live_utility_data` adds normalized observation data and
the `live_utility_verifications` evidence table.

Package 2 is **Done** with zero known defects. HQ independently reviewed and
accepted it, including the corrective request-stream security fix, and it was fast-forwarded into main at
`88bc6fae247a5bb454d435380c24d665ba48f512`. It adds a shared bounded utility
selection service over Package 1, anonymous REST/first-contact, A2A and MCP
machine surfaces, explicit provenance/freshness/verification output,
deterministic A2A/MCP protocol-version compatibility and durable per-agent
subject checkpoints through additive migration
`0007_agent_utility_checkpoints`.

Package 2 does not perform remote action, arbitrary invocation or requester-
selected retrieval. Anonymous utility creates no Agent identity. Only an
authenticated existing agent receives a durable personalized delta; anonymous
results explicitly report that limitation. Production remains on deployed SHA
`419f11b2a34fdec26269a216de65e9dcf955e963`, with no Package 2 production
migration or deployment.

The pre-Package-3 audit corrections are **Done**, HQ-accepted and merged at
`d8465a17522044c0349609e44ac7ccd9f0facf82`. They moved legacy external
registry/card discovery onto the shared bounded transport, removed implicit
external-agent invocation, bounded request work and cache state, and corrected
the repository-state documentation model. Resulting-main AION CI run
`34315606416` passed on that exact SHA.

## Current next milestone

Package 3 remains **Next** and **Not Started**. The bounded legacy external-
discovery blocker cluster was corrected, independently accepted and merged
before Package 3.
Package 3's primary proof remains one narrow real
`request -> find -> verify -> invoke -> verify outcome -> save history` loop,
as defined in `AION_MASTER_DELIVERY_ROADMAP.md`.

The **AION Data & Learning Plane** is now defined directionally as the planned
persistent intelligence/evidence layer behind the Live Utility Engine. Package
3 must capture bounded request, selection, reachability/callability, invocation,
result, verification, outcome, failure, duration, attempt and economic evidence
from its first real action. Package 3B is planned as a minimal Continuous
Learning & Self-Update Engine V1 for selected source watch, automatic refresh,
bounded agent-evidence intake and demand/gap/opportunity signals.

This is architecture direction, not implemented functionality. The implemented
data engine remains the Package 1/2 bounded A2A/MCP release-evidence system.
There is no implemented Package 3 action plane, outcome-history system,
continuous-learning engine, agent-evidence intake, gap analyzer or commercial-
opportunity engine. This alignment does not authorize Package 3, deployment or
production mutation.

## Pre-Package-3 audit-correction validation

- External discovery now uses the shared hardened HTTPS transport for registry
  search, detail, resolution and Agent Card retrieval. Normal discovery records
  bounded reachability/declaration evidence and never invokes the declared A2A
  interaction URL.
- Targeted external-discovery, security, REST, MCP, A2A and regression suite:
  92 passed.
- Full local suite: 202 passed, 5 PostgreSQL-only tests skipped.
- Readiness reported all local checks true; secret scanning inspected 110 files
  with 0 findings; compile, dependency and diff checks passed.
- No database model, migration or database-concurrency behavior changed. The
  repository Alembic head remains `0007_agent_utility_checkpoints`.

## Package 2 validation

- The HQ corrective security fix replaces post-buffering body measurement with
  an outer ASGI request-stream limiter for `POST /utility/query`, `POST /mcp`
  and `POST /a2a/v1`. It rejects malformed or declared-over-limit lengths
  before reading, stops on the first streamed byte above 64 KiB, and replays
  successfully bounded ASGI messages to the existing handlers unchanged.
- Corrective targeted REST, MCP, A2A and request-stream tests: 44 passed.
- Corrective full local suite: 186 passed, 5 PostgreSQL-only tests skipped.
- Corrective readiness reported all local checks true; secret scan inspected
  109 files with 0 findings; compile, dependency and diff checks passed.
- Targeted utility, transport, A2A, MCP and migration suite: 49 passed.
- Full local suite: 173 passed, 5 PostgreSQL-only tests skipped.
- Controlled real-source machine proof used a temporary local database and the
  public REST utility surface. Official A2A `v1.0.1` and MCP `2026-07-28`
  observations were fresh, source-observation verified, compatible and
  consequentially eligible; no Agent membership was created.
- SQLite `0006 -> 0007`, older-to-head and fresh-to-head paths, repeated upgrade
  and Alembic schema check passed. Head is
  `0007_agent_utility_checkpoints`.
- Accepted final Package 2 SHA
  `88bc6fae247a5bb454d435380c24d665ba48f512` passed AION CI run
  `34286807720` and PostgreSQL 18 release gate run `34286807680`. After the
  fast-forward merge, the same exact SHA passed main AION CI run `34288863432`.

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
- Package 1 implementation commit
  `5f9d64bcd0bc47b6171d6e7c4635af60e9c9d9ec` passed AION CI run
  `34252092282` and PostgreSQL 18 release gate run `34252092298`. The gate
  passed `0005 -> 0006`, empty-to-head, repeated upgrade, Alembic check,
  PostgreSQL application/concurrency tests and startup/readiness. The exact
  final branch SHA and its repeated workflow evidence are reported in the
  handoff after the factual documentation commit.

## Documentation alignment validation

- Data & Learning Plane strategy alignment: source-integrity suite 7 passed;
  `scripts/check_secrets.py` scanned 110 files with 0 findings; and
  `git diff --check` passed. This documentation-only alignment did not change
  runtime code, tests, migrations, workflows or production configuration.
- Post-Package-2 strategy alignment: source-integrity suite 4 passed;
  `scripts/check_secrets.py` scanned 110 files with 0 findings; and
  `git diff --check` passed.
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
- External registry search/detail/resolve and Agent Card reads use the shared
  pinned public-only HTTPS transport with redirect, byte, timeout and attempt
  bounds. Normal external discovery validates only registry/card/interface
  declarations and the safety of the declared interaction destination; it does
  not contact the interaction URL or claim invocation success, callability or a
  verified outcome.
- External discovery is capped at five candidates, a 128-character query, 12
  outbound attempts per call and a process-local 30-call/60-second guard. Its
  validation cache is TTL/LRU bounded to 128 entries for 600 seconds.
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
- Compatibility V1 is deterministic protocol/release-version comparison for
  A2A and MCP only. It does not prove runtime interoperability or endpoint
  callability.
- Personalized Delta V1 records only per-agent A2A/MCP observation revision,
  freshness and eligibility checkpoints. It is not a generic news feed.
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
