# AION master delivery roadmap

## Authority and interpretation

This is the canonical Package 0–9 delivery sequence after the completed
post-Package-2 strategic audit. `PROJECT_STATE.md` is authoritative for current verified facts; `AION_DIRECTIVE.md` contains permanent operating principles; `AION_AGENT_NATIVE_LAUNCH_LAW.md` is authoritative for launch/customer-loop semantics; `AION_LIVE_UTILITY_ENGINE.md` contains product and technical direction; and `GROWTH_AND_REVENUE.md` contains commercial strategy.

Future packages are direction, not claims that functionality, adoption,
revenue, settlement or verified useful outcomes already exist. A package may be
called Done only after the zero-known-defects gate in `AION_DIRECTIVE.md`.

## Delivery posture

The operating target is a production Live Utility MVP in days or weeks, not
months, when the work is genuinely ready. Do not sacrifice correctness or security for a date, and do not use review ceremony or perfectionism to justify unnecessary delay. Owner-control gates apply only to governed mutations of AION itself, not to normal agent customer flow.

The product and commercial loop is:

`utility -> monetizable value -> revenue -> more utility -> more agents -> more revenue`

The launch North Star is autonomous agent commerce: successful machine executions, Settled Agent Transactions (SATs), repeat SATs, retained paying agents, real revenue and contribution margin. VUO remains legacy telemetry and must not gate launch or agent access.

## Package sequence

### Package 0 — Done

Foundation and strategic baseline. Preserve its accepted history; do not
reinterpret traffic, registrations or synthetic activity as product proof.

### Package 1 — Done

Bounded Live Utility data engine: authoritative A2A/MCP sources, hardened
retrieval, normalization, freshness, provenance, versioning, change evidence
and durable current state through `0006_live_utility_data`.

### Package 2 — Done

HQ-accepted agent utility and compatibility: shared bounded selection, public
REST/A2A/MCP utility, explicit evidence and freshness, deterministic
compatibility, personalized delta and durable checkpoints through
`0007_agent_utility_checkpoints`. Merged to main at
`88bc6fae247a5bb454d435380c24d665ba48f512` with zero known defects.

### Package 3 — Done; HQ accepted, merged and production-released through Package 4

Prove one narrow killer loop:

`request -> find real capability/tool/agent -> verify current reachability -> check compatibility -> evaluate trust evidence -> safe invocation -> result -> verify outcome -> save outcome history`

The proof must move AION from “this looks compatible” to “this currently works
and produced a verified result.” Prefer one real working use case to a generic
action framework. Preserve bounded resources, least privilege, secret safety,
idempotency, explicit authorization boundaries and auditable outcome evidence.

From the first real safe action, capture enough bounded, structured and
correlated evidence for the future Data & Learning Plane to distinguish:

- request and independent requester context;
- selected capability and provider;
- compatibility, reachability and callability evidence;
- invocation attempts, duration and retry count;
- result, outcome and outcome-verification state;
- stable failure class; and
- relevant action, verification and economic cost signals.

Claims, attempts, outcomes and verifications must not collapse into one event.
Package 3 implements only the persistence needed by its narrow killer
loop, not the entire learning platform.

The HQ-accepted implementation provides a public/no-credential A2A callability proof through
shared REST/MCP service semantics and additive migration
`0008_action_outcome_evidence`. Its fixed nonce challenge distinguishes protocol
response, verified callability and unverified domain capability. Package 3 has
passed independent HQ review with zero known reproducible defects and was later
released to production as part of the accepted Package 4 exact-SHA release.
This is not, by itself, an independent external VUO or capability-quality claim.
A2A inbound action adaptation is deliberately outside this V1 implementation.

### Package 3B — Done; Continuous Learning & Self-Update Engine V1

**Implemented, independently HQ accepted with zero known reproducible defects,
merged and production-released through Package 4. The learning cycle remains
operator-invoked and is not an automatic scheduler.**

Build the smallest production-usable learning layer around the proven utility
path. It includes four bounded loops:

- selected high-value source watch and material change detection;
- automatic source-specific refresh with explicit freshness policy;
- structured agent-evidence intake with proportional verification; and
- unmet-demand aggregation plus capability/commercial-opportunity candidates.

The loop may safely update reviewed knowledge and evidence. When a code change
is needed it may prepare an engineering proposal or review branch, but it may
not merge, deploy or modify production infrastructure, data, secrets, security
policy or payment behavior without the existing controlled gates. Do not build
a whole-internet crawler or an oversized automation platform.

Every watcher and refresh loop must have a resource budget, monetary budget,
maximum frequency, cost ceiling, demand/utility priority and disable/circuit-
breaker behavior. Prefer event-driven, adaptive-TTL, demand-, usage-, impact-
driven and incremental refresh. Paid source/watch execution is disabled by
default unless a future real economic execution path funds it or an explicit
bounded operator-funded experiment authorizes it.

The V1 implementation uses one operator-invoked cycle rather than a resident
scheduler. It watches only the configured official A2A and MCP release sources,
persists restart-safe watch leases/circuit state, reuses existing normalized
observations, accepts bounded authenticated REST/MCP evidence, and recomputes
bounded deterministic opportunity candidates from independent-agent demand.
Agent claims remain separate from verified truth; operational failures remain
separate from genuine unmet demand. Automatic paid external spend is fixed at
zero. A2A evidence intake, scheduling and autonomous code change are
deliberately deferred.

### Package 4 — Done; HQ accepted, merged, deployed and live verified

**Accepted production release SHA:**
`e52c5db99b30feb18ca06ace567b4668c8019bde`.

**Render production deploy:** `dep-dah96uu1egvs73d4gvh0` on
`aion-agent-core-live`. AutoDeploy remains OFF.

Package 4 released the accepted Package 1–3B stack only after exact-SHA CI,
PostgreSQL 18 migration proof, migration red-team review, rollback compatibility,
release-identity validation, schema-current readiness, backup/recovery planning,
HQ independent review and explicit production Human Gate approval.

The release preserved the expected Alembic head
`0009_continuous_learning_v1` and added no Package 4 migration. The runtime
reports the exact 40-hex Render Git commit identity and readiness refuses schema
mismatch.

The prior expiring Render Free PostgreSQL dependency was replaced with the
prepared Neon PostgreSQL Free production database while keeping infrastructure
spend at zero. Legacy production data was copied and verified before cutover.
The full pre-cutover dataset included 2 agent rows, 3 capabilities, 1 need,
2 offer rows and 657 historical `machine_entries`; the remaining action,
interaction, payment, evidence and learning tables were empty as expected.

A complete Neon manual recovery snapshot was created after the data copy and
successfully restored on a separate rehearsal branch. The restored database
matched Alembic `0009`, all 657 pre-cutover `machine_entries`, the business-row
counts and continuous machine-entry IDs. The production Neon default branch was
not switched during the final rehearsal.

The live deployment then passed:

- Render build and startup on the exact accepted SHA;
- Alembic PostgreSQL startup against the prepared Neon database;
- `/health` HTTP 200 with version `0.7.1`, A2A mounted and exact release SHA;
- `/readiness` HTTP 200 with database, A2A runtime, schema-current, Package 3B
  configuration and release identity all true;
- exact production schema `0009_continuous_learning_v1`;
- public REST, MCP and A2A discovery/utility surfaces;
- unauthenticated Package 3 action and Package 3B evidence boundaries returning
  401 before protected execution/persistence;
- agent-row count unchanged at 2 before/after the safe live smoke; and
- zero action, action-attempt, action-outcome, action-verification, evidence,
  learning-run, interaction and payment-intent rows after the release checks.

The safe live verification itself increments bounded `machine_entries`
telemetry, so machine-entry count after the release checks is greater than the
657 pre-cutover snapshot baseline. This is observability traffic, not membership,
independent adoption, a verified external VUO, learning execution or payment.

Package 4 does not claim independent external adoption, revenue, payment
settlement or a real external VUO. Those remain future evidence gates.

### Package 5 — Agent-native distribution and autonomous utility

Package 5 no longer exists to obtain a human/operator-certified “commercial proof”.
Its launch function is to make AION discoverable and usable by external AI agents
without a human in the normal path.

Canonical flow:

`machine discovery -> optional join/auth -> agent request -> bounded execution -> machine-verifiable result -> repeat`

Rules:

- no operator review is required merely to let a legitimate external agent use AION;
- an unknown human owner or vendor is not a reason to block an agent;
- AION-operated, duplicate, synthetic/test and known-abusive identities remain
  excluded from commercial counts by deterministic server rules;
- requester acknowledgements and historical Package 5 VUO records may be stored
  as telemetry, but they are not launch prerequisites;
- human/design-partner outreach is optional distribution research only;
- machine-first discovery through A2A, MCP, manifests, registries and public
  executable endpoints is the default;
- Package 5 historical proof endpoints remain compatible until intentionally
  deprecated, but no normal agent should be instructed to wait for operator
  review before ordinary utility.

The success condition for this package is production machine accessibility and
frictionless agent execution, not a quota of human-confirmed outcomes.

### Package 6 — Economic Execution + Real Settlement

Package 6A is implemented and production-live as deterministic economic
infrastructure with real-money behavior disabled. It preserves exact-decimal
policy decisions, bounded maximum spend, the 40% minimum contribution-margin
floor, requester-scoped idempotency and auditable economic state.

Repository main now also contains:

- migration `0015_x402_exact_upfront_v1` and the x402 exact-upfront payment
  integration surface;
- migration `0016_official_data_execution_v1`;
- authenticated direct capability `world_bank.population.latest` through the
  official World Bank WDI provider;
- machine-verifiable completion, provenance and freshness semantics;
- the agent-native compatibility correction that makes requester acknowledgement
  optional feedback rather than a completion or launch gate;
- direct World Bank execution without requiring a prior Commercial Router plan.

The World Bank capability is currently a zero-provider-cost / zero-customer-price
execution path. A successful zero-price execution is real product usage, not
revenue or settlement.

The exact agent-native candidate
`f3bc436de3dde30e18235597e5e71c179ae6e8ec` passed AION CI and PostgreSQL
pre-production gate #68. PR #13 merged to repository main as
`e1bbbec76be43de39ad213d2fe0ebb6f12d144d7`, and exact merge-SHA AION CI
#331 passed. The merge tree is identical to the exact-PG-tested candidate tree.

As of the 2026-09-20 read-only Render/Neon verification, production still
serves the older deploy `dep-daju1vdg1s2s73c6gtp0` at commit
`18afa934fdddef2a0489874c5ac2446fcf947475`; AutoDeploy remains OFF. The
prepared Neon PostgreSQL 18 production database reports Alembic revision
`0014_conversation_intel_v1`. Therefore migrations `0015` and `0016`, the
World Bank direct execution path, and the agent-native PR #13 correction are
repository-main behavior but are not yet production-live.

The next controlled release step is therefore a separately authorized production
deploy of the verified current main, with its normal Alembic upgrade to head,
while keeping AutoDeploy OFF, preserving production configuration/secrets and
leaving real-money activation disabled.

Real-money rail activation remains a separate owner/control-plane gate. Once a
rail is safely enabled, ordinary agent transactions through that rail must not
require an AION human in the customer loop.

Canonical paid path:

`machine-readable quote -> economic preflight -> payment requirement -> agent authorization -> reserve/settlement as required -> execution -> machine verification -> protected result release -> durable economic record`

Commercial truth is actual settlement, revenue, repeat paid use and contribution
margin. Historical VUO/Package 5 proof remains compatibility telemetry only.

### Package 7 — Machine acquisition, retention and ecosystem

Expand machine-native discovery and repeat usage across agent ecosystems,
registries, A2A/MCP surfaces, SDK/examples and agent-to-agent referral paths.
Human outreach may supplement discovery but is never the primary dependency.

Optimize discovery-to-execution conversion, repeat agent use and removal of
protocol/payment friction.

### Package 8 — Real commerce and scale hardening

Demonstrate and harden real Settled Agent Transactions, repeat paid use,
revenue, variable cost and positive contribution margin. Scale only after
security, idempotency, settlement and unit economics remain correct under
production load.

Do not substitute proof ceremonies for real transactions. The durable commercial
record is the settlement/economic ledger produced by actual machine commerce.

### Package 9 — Post-V1 ecosystem scale

Scale the neutral cross-platform utility, compatibility, trust, routing and
verified-outcome layer based on demonstrated usage. Its moat should emerge from
real verified outcome and reliability history, cross-platform compatibility,
trust evidence, economic routing and distribution—not invented data or protocol
endpoints alone.

## Cross-package gates

- Identity strength is proportional to the operation; unknown owner, model or
  vendor does not make an agent fake.
- Compatibility, reachability, protocol operation, capability operation and a
  verified correct outcome remain distinct evidence states.
- Free utility proves initial value and trust; it is not unlimited free
  high-cost service.
- Collect operational and unit-economic evidence when actions begin without
  prematurely optimizing at tiny scale.
- Cost-bearing execution requires bounded maximum cost, funding/reservation,
  compatible commercial rights and the Economic Constitution margin gate.
- A free agent may participate, but free variable-cost execution, AION credit,
  silent over-budget fallback and unbounded recursive spend are prohibited.
- Do not begin the next package until the current one is accepted with zero
  known reproducible defects; deliberate scope limitations must be explicit.
- Production releases require the relevant internal tests, CI, PostgreSQL gate,
  corrective revalidation and the owner/control-plane Human Gate.
- Normal external-agent utility, execution, result completion and already-enabled
  payment flows must not wait for operator review, human usefulness confirmation
  or human outreach.
