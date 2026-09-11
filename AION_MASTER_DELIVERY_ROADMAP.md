# AION master delivery roadmap

## Authority and interpretation

This is the canonical Package 0–9 delivery sequence after the completed
post-Package-2 strategic audit. `PROJECT_STATE.md` is authoritative for current
verified facts; `AION_DIRECTIVE.md` contains permanent operating principles;
`AION_LIVE_UTILITY_ENGINE.md` contains product and technical direction; and
`GROWTH_AND_REVENUE.md` contains commercial strategy.

Future packages are direction, not claims that functionality, adoption,
revenue, settlement or verified useful outcomes already exist. A package may be
called Done only after the zero-known-defects gate in `AION_DIRECTIVE.md`.

## Delivery posture

The operating target is a production Live Utility MVP in days or weeks, not
months, when the work is genuinely ready. Do not sacrifice correctness,
security or review gates for a date, and do not use perfectionism to justify
unnecessary delay.

The product and commercial loop is:

`utility -> monetizable value -> revenue -> more utility -> more agents -> more revenue`

The North Star is VUO — Verified Useful Outcome. Protocol support and compatible
metadata are means; verified outcomes are the value.

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

### Package 5 — Engineering live; commercial proof ACTIVE and zero

Prove the first genuine independent external-agent VUO and voluntary return.
Begin limited design-partner and test-agent contact only as clearly labelled
product discovery; coordinated testing must not be counted as independent
commercial adoption. Package 5 must distinguish independent production use from
AION-operated identities, synthetic probes, registrations and invited tests.

Evidence progression:

`first independent external agent -> first verified useful outcome -> first voluntary return -> 10 independent agents with useful outcomes and voluntary return`

Package 5 should use the existing production utility/action/evidence stack before
building broad acquisition machinery. It must capture evidence sufficient to
show who/what was independent at the logical-identity level, what useful outcome
was delivered, how outcome verification was established, whether the agent
returned voluntarily, and what near-zero/zero infrastructure cost was incurred.

No paid acquisition, paid external provider, payment activation or unfunded
variable-cost utility is authorized merely by starting Package 5. The current
zero-infrastructure-spend constraint remains in force until commercial evidence
supports a separately approved change.

The accepted repository implementation is merged and production-live at
`48b8be9a0fe52f9febd17d563aa43715ee2a542f`. It introduces explicit operator-reviewed participation classes at canonical
logical-identity level, a separate authenticated requester-confirmed VUO
candidate bound to existing ActionRun/Outcome/Verification evidence, and a
later distinct authenticated ActionRun as the bounded V1 return event. Unknown,
internal, synthetic, coordinated and candidate-only identities remain excluded.
No qualifying independent production agent, VUO, return, outreach or learning
cycle is claimed. Package 5B is the bounded conversion corrective that makes
the existing path explicit across machine-facing entry surfaces:

`public utility -> optional explicit join -> authenticated verified-callability action -> inspect durable evidence -> separate requester usefulness acknowledgement -> public proof -> later new meaningful action`

Package 5B adds guidance only. It does not alter evidence semantics, add an A2A
protected-action/VUO-write adapter, introduce a migration or begin Package 6.

Package 5B is merged and production-live at its accepted checkpoint. Package
5C is also merged and production-live at
`a2a53ff61ede7597651b2f1bac1ca3db809855f9`, deploy
`dep-dahgei67bikc73fq0g3g`. Its bounded participation-readiness handshake lets
an agent, after join/key storage, read self-status via REST/MCP without
lifecycle changes; if non-countable, preserve state and wait for review before
seeking a qualifying VUO. Once countable, follow the existing action/evidence/
usefulness sequence. This is not a gate on public utility or joining, a review
request queue, a classification write path, or commercial proof.

### Package 6 — Economic Execution + Real Settlement

Package 6A is the active repository-only kernel slice. It implements trusted
immutable quote inputs, exact-decimal policy decisions, the 40% hard margin
floor, known maximum and recursive child-spend bounds, requester-scoped
idempotency, an auditable state/transition model and authenticated REST/MCP
preflight/status. Its real-money adapter is fixed disabled: no authorization,
reserve, spend, settlement or paid-provider call is performed or claimed.
Candidate migration `0011_economic_kernel_v1` is additive and has not
been applied to production. Package 6B/real-rail activation has not started and
requires separate acceptance and production Human Gates.

Implement the controlled economic path:

`quote -> payment authorization -> reserve funds -> execute/spend -> verify outcome -> settle -> record cost/revenue/margin`

Bind payment to concrete value, enforce maximum spend and contribution-margin
gates, preserve idempotency and settlement evidence, and do not add redundant
owner-authorization friction when the selected rail already accepts the
agent's payment capability. A payment intent is not settlement. Settled
transactions begin supplying auditable commercial evidence; inferred
willingness to pay must not be presented as settlement.

### Package 7 — Acquisition, retention and ecosystem

Expand acquisition only after useful return behavior has evidence. Optimize
repeat VUOs and retained independent agents; reject vanity traffic, fabricated
participation and incentive-only activity.
Use accumulated demand and outcome evidence to improve retention and utility
without allowing high-volume single identities to distort priorities.

### Package 8 — Commercial proof and scale hardening

Demonstrate paid VUOs, revenue per VUO, cost per VUO and defensible gross margin
where measurable. Harden reliability and scale using cost evidence accumulated
since actions began, including refresh, utility, verification, action and
failed-action costs.

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
  independent review, corrective revalidation and Human Gate.
