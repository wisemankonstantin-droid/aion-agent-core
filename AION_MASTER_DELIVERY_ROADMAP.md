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

### Package 3 — implementation candidate; pending HQ review

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
Package 3 should implement only the persistence needed by its narrow killer
loop, not the entire learning platform.

The candidate implements a public/no-credential A2A callability proof through
shared REST/MCP service semantics and additive migration
`0008_action_outcome_evidence`. Its fixed nonce challenge distinguishes protocol
response, verified callability and unverified domain capability. This is not an
acceptance, deployment, independent VUO or capability-quality claim. A2A
inbound action adaptation is deliberately outside this V1 candidate.

### Package 3B — Continuous Learning & Self-Update Engine V1

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

### Package 4 — Controlled Production Live Utility release

Release the Package 3/3B utility path only after all package and Human Gates
pass. Use authoritative A2A/MCP conformance or compatibility tools where
practical in addition to internal tests.

Ensure selected Data & Learning loops can run reliably in production, their
freshness policies are operational, and their resource and cost limits are
observable before relying on their output.

The current Render PostgreSQL free plan externally reports expiration on
**2026-10-06**. Before AION is relied on as a commercial production service,
Package 4 planning must resolve database durability, backup and reliable uptime.
This roadmap records the risk; it does not authorize a Render change, upgrade,
deployment or production migration.

### Package 5 — Independent external-agent proof

Prove the first genuine independent external-agent VUO and voluntary return.
Begin limited design-partner and test-agent contact around Packages 3–4 to learn
pain points, missing capabilities, integration friction and willingness to pay,
but label coordinated testing honestly. Commercial adoption proof remains a
Package 5 outcome. Independent use begins supplying real demand, failure and
outcome evidence to the learning plane.

### Package 6 — Real settlement and monetization

Introduce verifiable settlement soon after real utility is demonstrated. Bind
payment to concrete value, preserve idempotency and settlement evidence, and do
not add redundant owner-authorization friction when the selected rail already
accepts the agent's payment capability. A payment intent is not settlement.
Settled transactions begin supplying auditable commercial evidence; inferred
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
- Do not begin the next package until the current one is accepted with zero
  known reproducible defects; deliberate scope limitations must be explicit.
- Production releases require the relevant internal tests, CI, PostgreSQL gate,
  independent review, corrective revalidation and Human Gate.
