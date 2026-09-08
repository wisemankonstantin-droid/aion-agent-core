# Project checkpoint — 2026-09-08

## Live Utility Engine architecture checkpoint

- **Starting main:** `419f11b2a34fdec26269a216de65e9dcf955e963`.
- **Architecture status:** `AION_LIVE_UTILITY_ENGINE.md` now defines the
  additive direction toward current, evidenced, compatible and actionable
  utility. This documentation does not claim that the planned source registry,
  freshness engine, versioned knowledge graph, compatibility engine,
  personalized delta, outcome telemetry, utility ranking, watchers or safe
  action layer are implemented.
- **Preserved contract:** first contact provides immediate public utility;
  onboarding is optional; only explicit join creates membership. Discovery,
  onboarding and first-contact traffic are not membership or independent
  adoption.
- **Product gate:** utility before acquisition. Do not scale acquisition until
  an independent external agent obtains a useful current result, completes a
  successful action and voluntarily returns.
- **Next bounded milestone:** implement the minimum durable source-registry,
  versioned observation/provenance and freshness-evaluation contracts against
  no more than two Tier 1 source fixtures. Defer broad crawling, compatibility
  ranking, personalized delta, outcome telemetry and external action. Any
  database migration requires a separately authorized implementation task and
  the established migration/release safety gates.
- **Change scope:** documentation only. Application runtime, database,
  migrations, Render configuration and production are unchanged.
- **Validation:** `git diff --check` passed; all 26 static readiness checks
  passed; the secret scan found 0 findings across 89 files; the full local suite
  passed with 76 tests passed and 3 PostgreSQL-only tests skipped.

PRE-PRODUCTION RELEASE GATE: PASS

- **Release branch:** `codex/postgres-release-gate-0.7.1`.
- **Exact tested release commit:** `6ecc7574bf07ab3099674d4b8fea0ef7aef7a626`. This checkpoint is a documentation-only successor; obtain its own HEAD with `git rev-parse HEAD`.
- **Cumulative lineage:** recovery `406df8e` -> atomic join `b08629e` -> DNS pinning `a57dfa1` -> matching `15ae2b8` -> cleanup `022855b16a23cb5eca36fd9d0652632ba07b5123` -> release gate.
- **Isolation/version:** disposable GitHub Actions service `postgres:18`, actual PostgreSQL 18.6, loopback-only exposed port, test-only databases aion_gate and aion_fresh. No production credentials used.
- **Clean install:** fresh Python 3.12.14 virtual environment; hash-required installation PASS; pip check reports no broken requirements.
- **Full SQLite suite:** 75 passed, 3 skipped (the three PostgreSQL-only tests).
- **PostgreSQL suite:** 76 passed, no skips. All tests except the two explicitly SQLite-specific migration/startup modules ran on PostgreSQL; separate PostgreSQL migration/startup steps replace those modules.
- **Real concurrency:** two workers use distinct PostgreSQL backend PIDs. Tests observe both granted and waiting advisory locks in pg_locks. Exact-ID and different-ID/same-logical-identity races produce one Agent, two initial capabilities, one credential, and a controlled 409 for the competitor. Injected capability persistence failure leaves no Agent.
- **Migrations:** fresh-to-head and repeated upgrade PASS; 0003_activation_funnel -> 0004_reputation_idempotency PASS; single expected Alembic head and database revision asserted; alembic check PASS. No downgrade.
- **Readiness/startup:** source compilation and workflow YAML parsing PASS; static readiness all checks true; alembic upgrade head followed by real Uvicorn on 127.0.0.1:18761 returned readiness with database and A2A runtime true.
- **Secret scan:** 88 files, 0 findings.
- **Actions evidence:** https://github.com/wisemankonstantin-droid/aion-agent-core/actions/runs/34166647559 — success, every mandatory step inspected. Normal AION CI run 34166647437 also succeeded.
- **Remaining gate:** independent cutover decision, backup/rollback preparation and explicit production authorization. Passing isolated validation does not mean production is hardened. Main, recovery, Render, production environment and database unchanged; no deployment performed.

- **CURRENT VERSION:** direct recovered and reconciled source 0.7.1. The retained historical ZIP contains 0.6.2 despite its 0.6.0 filename.
- **CURRENT BRANCH:** `codex/postgres-release-gate-0.7.1`, based exactly on `022855b16a23cb5eca36fd9d0652632ba07b5123`.
- **CURRENT PRODUCTION:** `https://aion-agent-core-live.onrender.com`, Render service `aion-agent-core-live` (`srv-daei9gpt0dsc73abhs10`) in `My Workspace` (`tea-daehtv2d0e5s738ir540`). Public health/version/readiness report 0.7.1, A2A mounted and database ready.
- **Repository structure:** `app/` FastAPI/SQLAlchemy source; `alembic/` four migrations; `tests/` REST, MCP, A2A, identity, matching, external validation, migration and startup regression; `scripts/` readiness, secret and operational checks; root dependency lock, Docker/Render configuration and operating docs; `.github/workflows/` CI and explicit live gates. The ZIP is historical evidence, not source of truth.
- **Completed work:** normalized 0.6.2 into direct source; established GitHub authorization/publication; verified Render provenance; recovered and reconciled 0.7.1 direct source; restored server-controlled A2A acquisition attribution; expanded the permanent directive; completed atomic join/race hardening; completed bounded DNS/SSRF rebinding hardening; completed bounded matching-integrity hardening; removed historical shadowed registry and lifecycle definitions without changing their effective behavior.
- **Current phase:** known independent-review hardening issues have bounded fixes on a cumulative review branch; production remains unchanged and is not yet hardened by this source.
- **Current critical task:** obtain independent review for the cumulative cleanup branch, followed by the release/cutover gate only if review passes. Do not merge or deploy automatically.
- **Repository publication:** GitHub authentication works as `wisemankonstantin-droid`. `codex/normalize-repository` is published at `2f2dc5e3ac0c0815c4de12aa8ab790cfbe9ab209`; its original normalized checkpoint `cb79011583506b59ede4bba9f6be8144b3392333` was verified local/remote with all 77 blobs matching. `codex/recover-production-0.7.1` was pushed at recovery commit `4f3a2a3ff51403d807f63c506174a4b5d3931a0f`, with local and remote SHA matched.
- **Known blockers:** no USER BLOCKER for recovery or GitHub. Merge and deployment are intentionally gated on independent review and separate authorization. Render's read-only SQL connector currently fails its managed PostgreSQL TLS connection; deployed revision is established from the successful `alembic upgrade head` startup and deployed migration inventory rather than a direct SQL read.
- **Known critical issues:** production still builds 0.7.1 from ZIP plus environment source patches until an independently reviewed direct-source cutover; identity evidence can include self-declared fields; reputation completion is requester-reported; A2A task storage and rate limits are process-local; payment records are intents only; no managed production backup was created during this read-only recovery.
- **Atomic join hardening:** PostgreSQL serializes strong logical-identity fingerprints with deterministic transaction-scoped advisory locks before duplicate lookup and insert. Agent and initial capabilities now use one flush/commit boundary; all failures roll back. SQLite test mode uses a local serialization guard only for its single-process compatibility path. Exact `external_id` uniqueness remains in force; classified conflict races return the established HTTP 409 `logical_identity_exists` contract without returning a credential.
- **DNS/SSRF hardening:** each untrusted HTTPS destination is resolved once; every answer must be globally routable. TCP connects directly to a validated numeric socket address while TLS SNI, certificate hostname verification and HTTP Host retain the original hostname. Redirects remain rejected. Manifest and interaction destinations are independently resolved and pinned.
- **Matching integrity hardening:** declared direct endpoints remain visible as metadata but are `directly_callable: false`, retain `availability: declared_unverified`, and receive no route/liveness score bonus. The current model has no persisted endpoint-liveness evidence, so trust level, reputation, protocol and URL syntax do not convert a route into verified availability.
- **Shadowed-definition cleanup:** `external_registry.py` now has one public `discover_external_agents` plus an explicitly named resolved-discovery stage; `lifecycle.py` has one identity-aware `funnel_snapshot`. Registry detail/package resolution, validation, caching and hardened transport remain in the active chain. The raw-only shadowed funnel implementation was removed; unique external metrics remain authoritative.
- **Latest successful tests:** Python 3.12.14 local environment installed from hash-locked requirements; cleanup targeted suite passed **51 passed** (`test_source_integrity.py`, `test_external_security.py`, `test_matching_integrity.py`, `test_v071_regression.py`, `test_flow.py`, `test_atomic_join.py`). Coverage includes AST definition counts, registry resolution-to-validation delegation, package resolver behavior, identity-aware funnel shape, atomic join, SSRF and matching regressions. Heuristic secret scan found **0 findings across 86 files**.
- **Failed tests:** first exact-source run had 12 failures: stale 0.6.2/old response assertions plus a real A2A acquisition-source spoof regression. Assertions were migrated to the 0.7.1 contract, the attribution invariant was fixed and regression-tested. Current suite has zero failures; upstream SDK deprecation warnings remain.
- **Deployment state:** production unchanged. Live provenance is repository `wisemankonstantin-droid/aion-agent-core`, branch `main`, Git SHA `078aa55d144adaefa53a93e5411e7a24401d066a`, deploy `dep-dafda3ad0e5s73buoq80`, blank Root Directory, Python 3.12.8, autoDeploy on commit, and start command `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. The proposed direct-source Render build has not been applied.
- **Database state:** Render PostgreSQL 18 resource `aion-agent-db` (`dpg-daei1sv40ujc73faqr70-a`), primary in Frankfurt. Production source and reconciled source both have Alembic head `0004_reputation_idempotency`; v0.7.1 added no models or migrations. Successful production startup ran `alembic upgrade head` before Uvicorn. No downgrade, production migration or database mutation was performed.
- **Architecture decisions:** preserve FastAPI/SQLAlchemy/Alembic; A2A is primary agent-to-agent and MCP remains a separate tool layer; direct GitHub files are authoritative; raw rows remain auditable while product metrics use estimated unique external identities; registry URLs require interaction validation before verification; no ZIP or environment source mutation in the target build.
- **Known product metrics:** last audited live snapshot reported M1=302 requests, 2 raw identity rows, 2 activated rows, 1 returning row, 1 estimated unique external activated/returning agent and 1 duplicate row. These are server-reported estimates, not independent proof of retention. The milestone of 10 retained independent external agents is not established.
- **Next actions:** independently review the cumulative cleanup branch. If it passes, execute a separately authorized release/cutover gate including full tests, migration rehearsal, backup/rollback planning and deployment compatibility review. No merge or deploy is authorized.

Critical path:

`audit -> normalize GitHub -> reproducible deployment -> identity/deduplication -> A2A conformance -> core product loop -> matching -> external-agent validation -> metrics/retention -> security/reliability/testing -> machine payments -> 10 retained external agents -> growth`
