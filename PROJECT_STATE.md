# Project checkpoint — 2026-09-09

## Current production state

- **Repository:** `wisemankonstantin-droid/aion-agent-core`.
- **Accepted Package 2 application baseline:**
  `88bc6fae247a5bb454d435380c24d665ba48f512`.
- **Post-Package-2 strategy alignment checkpoint:**
  `7fb469024855a065a1d42d12fc5c1a40d354ab6f`.
- **Accepted pre-Package-3 audit-correction checkpoint:**
  `d8465a17522044c0349609e44ac7ccd9f0facf82`.
- **Main checkpoint at Economic Control Plane alignment start:**
  `d2ddb13797915788a06ad1bf4266fea7683ab462`.
- **Main checkpoint at Package 3B implementation start:**
  `a92964e0b7d29eacae8016e6ea54f084f6f3a4bf`.
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
- **Accepted Package 3 Alembic head:** `0008_action_outcome_evidence`.
- **Accepted Package 3B Alembic head:** `0009_continuous_learning_v1`.
- **Production boundary:** Package 3 has not been deployed or migrated in
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

## Current Package 3 implementation

Package 3 is **implemented and independently HQ-accepted with zero known
reproducible defects**. It is merged to main at
`d2ddb13797915788a06ad1bf4266fea7683ab462` but is not deployed. The accepted implementation provides one
narrow authenticated and explicitly authorized public/no-credential A2A
callability action: bounded discovery, deterministic safe selection, one fixed
server-generated nonce challenge, verification and durable correlated history.
REST and MCP use one service. A2A inbound action exposure is deliberately not
included in V1; credentials are never placed in A2A message content.

The **AION Data & Learning Plane** is now defined directionally as the planned
persistent intelligence/evidence layer behind the Live Utility Engine. Package
3 captures bounded request, selection, reachability/callability, invocation,
result, verification, outcome, failure, duration, attempt and economic evidence
from its first real action. The HQ-accepted Package 3B implementation adds a minimal Continuous
Learning & Self-Update Engine V1 for selected source watch, automatic refresh,
bounded agent-evidence intake and demand/gap/opportunity signals.

The broader Data & Learning Plane remains architecture direction. Package 3
adds four bounded evidence boundaries: ActionRun, ActionAttempt, ActionOutcome
and ActionVerification. Migration `0008_action_outcome_evidence` is additive and stores normalized evidence,
digests and byte/timing counters without raw remote response bodies.
Callability proof leaves `capability_verified=false`; controlled fixtures are
not independent adoption or external VUO evidence.

## Current Package 3B implementation

Package 3B is **implemented and independently HQ-accepted with zero known
reproducible defects**. Production deployment remains separate and has not
occurred. The accepted implementation adds a one-shot bounded learning cycle,
durable selected-source watch/circuit coordination, authenticated REST/MCP
agent-evidence intake, and deterministic demand/gap opportunity candidates.
It watches only the configured official A2A and MCP release sources and reuses
the Package 1 normalization, verification, freshness and material-version
lineage. Migration `0009_continuous_learning_v1` is additive.

Agent claims begin unverified; distinct authenticated logical agents may
establish corroboration but not verified truth. Duplicate raw identity rows do
not create corroboration or independent market breadth. Submitted URLs are passive untrusted
evidence and are never contacted by intake. Genuine `no_result`,
`capability_not_found`, `incompatible`, and authenticated
`missing_capability` evidence feed bounded unmet-demand aggregation.
Operational failures remain separate and cannot masquerade as market demand.
Every authenticated evidence attempt—including replay, conflict and duplicate
traffic—passes the same per-agent abuse gate before database reads. Shared
material locking makes concurrent cross-agent corroboration converge.
Opportunity recency uses durable AION action timestamps and evidence receipt
time, never a future agent-supplied `observed_at`. AION-operated/test logical
identities are excluded from independent opportunity breadth, confidence and
priority.

Automatic Package 3B paid external spend is disabled with a maximum of zero.
The candidate contains no real payment implementation, paid-provider calls,
automatic production scheduler, crawler, autonomous code modification, merge
or deployment behavior. A2A evidence intake is a deliberate V1 limitation;
REST and MCP share one authenticated service. No independent adoption,
production learning operation, external VUO, payment, revenue or commercial
opportunity proof is claimed.

Package 3B validation at this checkpoint:

- the initial Package 3B candidate at
  `5fb5915ba63db63baad9ffd1e5184132ffcfcfbc` passed AION CI run
  `34377175042` and PostgreSQL 18 pre-production release gate run
  `34377175046` on that exact SHA;
- the bounded HQ corrective pass makes replay, conflict and duplicate evidence
  attempts consume the common rate allowance; serializes shared-material
  corroboration; maps demand through canonical logical identities; excludes
  AION-operated/test identities from commercial breadth; and makes durable
  receipt time authoritative for untrusted-claim recency;
- corrective targeted learning, migration, request-boundary, source-integrity,
  Live Utility, safe-HTTP, external-security, Package 3, MCP and PostgreSQL-gate
  collection: 175 passed, 10 PostgreSQL-only tests skipped locally;
- corrective full local suite: 295 passed, 10 PostgreSQL-only tests skipped;
- SQLite fresh-to-head and `0008 -> 0009` upgrade paths, repeated upgrade and
  Alembic schema check passed; and
- the HQ corrective commit `8e6b4a19263dcb687d20d6240f8752779685b90d`
  passed AION CI run `34382094903` and PostgreSQL 18 pre-production release
  gate run `34382094918` on that exact SHA; HQ independently re-reviewed the
  four prior blockers and accepted Package 3B with zero known reproducible
  defects. Live merge/main status must be verified directly from GitHub.

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

## Package 3 validation

- Targeted action, request-boundary, hardened-transport, external-security and
  migration suite: 89 passed.
- Full local suite: 245 passed, 6 PostgreSQL-only tests skipped.
- SQLite fresh-to-head and `0007 -> 0008` paths, repeated upgrade and Alembic
  schema check passed. The accepted Package 3 head is
  `0008_action_outcome_evidence`.
- The controlled end-to-end responder proof exercised bounded discovery,
  requester-scoped claim, one official A2A `SendMessage`, nonce verification,
  four durable evidence boundaries and restart-safe retrieval. It is a test
  fixture, not independent adoption or a commercial VUO.
- HQ independently accepted the corrected Package 3 implementation at
  `b34ae9b3d792f96fb3c71710d727a1db56d78cb3` after AION CI run
  `34325607999` and PostgreSQL 18 release gate run `34325608008` both passed
  on that exact SHA. It is merged and remains undeployed; production is untouched.
- The HQ-accepted corrective implementation preserves structured discovery status internally
  so operational, rate, configuration and budget failures cannot be persisted
  as a factual `no_result`. Public discovery lists remain compatible and
  declaration-only.
- Corrective targeted discovery/action/security/source-integrity suite: 73
  passed, with 6 PostgreSQL-only cases skipped locally. Corrective full local
  suite: 254 passed, 6 PostgreSQL-only cases skipped. The PostgreSQL cases
  remain required in the exact-SHA release gate.

## Economic Control Plane alignment

The Economic Constitution alignment is **independently HQ-accepted with zero
known reproducible defects**. It canonically defines no unfunded variable
spend, no AION credit, pay-before-spend, maximum-cost and funding gates,
contribution-margin floors and targets, lawful paid-source use,
prepaid/reserved funding, recursive spend limits, the Economic Capability
Profile, product tiers, and future cost/VUO and CM/VUO evidence.

This is documentation and architecture policy only. No payment rail,
settlement, wallet, balance ledger, paid-provider execution, dynamic pricing or
other economic runtime is implemented. Package 3B does not weaken these rules.
Production remains intentionally unchanged. Live merge/main status must be
verified directly from GitHub under the repository state rule above.

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
