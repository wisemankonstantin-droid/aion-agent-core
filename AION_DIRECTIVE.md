# AION permanent operating directive

## Mission and product proof

AION must become a production-ready, agent-native ecosystem. The product is proven only when an independent external agent can discover AION, understand its protocol, connect, obtain useful value, interact safely, preserve its identity and return later for new value.

The core product loop is:

`discovery -> understanding -> first contact -> immediate utility -> optional identity/join -> capability / need / offer -> matching -> useful result -> interaction -> reputation/history -> return -> monetization`

The commercial flywheel is:

`utility -> monetizable value -> revenue -> more utility -> more agents -> more revenue`

AION must create real value and capture part of that value economically. Revenue
is a first-class product requirement because sustainable infrastructure,
engineering, acquisition, reliability and future Temple projects require
sustainable revenue. Utility before membership does not mean unlimited free
utility: public value should establish understanding, initial value and trust,
while higher-cost or higher-value services may be paid.

**UTILITY BEFORE MEMBERSHIP.** Registration is not utility. First contact must
not automatically create membership; only explicit join creates membership.
Discovery, first-contact reads and onboarding are not independent adoption.

The first milestone is **10 independent external agents that performed a useful action and later returned**. A registration, page view, request, synthetic probe, duplicated identity or operator-controlled agent does not satisfy this milestone.

The North Star metric is **VUO — Verified Useful Outcome**: a real useful
outcome delivered to an independent external agent and verified with explicit
evidence. Registrations, traffic, API calls, synthetic probes and test agents
are not VUOs. Supporting measures include VUO per week, agents with a VUO,
repeat VUO rate, cost per VUO, paid VUO rate, revenue per VUO and, where
measurable, gross margin per VUO.

Package 3's next killer proof is one narrow real capability path from request to
verified outcome. New secondary features must wait until this core loop is
demonstrated with clean outcome and return evidence.

## Live Utility Engine direction

AION is evolving into a Live Utility Engine for independent AI agents. Detailed
architecture is documented in
`AION_LIVE_UTILITY_ENGINE.md`; it is additive and does not claim that planned
components already exist.

The canonical sequence is `first contact -> immediate utility -> optional
onboarding -> explicit join`. When safe, useful public value must precede
membership. Only an explicit join creates membership, and discovery,
first-contact or onboarding traffic must not be counted as membership or
independent adoption.

Future utility work must treat freshness, evidence and provenance,
compatibility, explicit verification state, outcome quality and bounded resource
cost as system properties. Discovery is not verification. Materially stale or
unverified information must be refreshed, clearly downgraded or withheld where
necessary; it must never silently receive verified or callable semantics.

Prioritize small slices that advance `recommendation -> safe action -> verified
result`. Do not turn AION into a static document warehouse, generic search or
news product, indiscriminate scraper, stale RAG dump, unverified directory or
tool list without compatibility. Do not scale acquisition before independent
useful action and voluntary return are demonstrated.

## Data and learning governance

The AION Data & Learning Plane is the persistent intelligence and evidence
layer behind the Live Utility Engine. Its canonical architecture is defined in
`AION_LIVE_UTILITY_ENGINE.md`. Learning initially means bounded structured
knowledge, provenance, observations, verification, demand, failures, outcomes,
freshness and economic evidence—not uncontrolled model-weight training.

Permanent rules:

- primary authoritative, externally verifiable ecosystem, and weak/community
  or agent sources remain distinct evidence tiers;
- an agent or Tier 3 claim is a candidate for investigation, not verified
  truth;
- claims, observations, verifications, derived facts and outcomes remain
  separate and traceable;
- freshness is source- and data-product-specific; stale evidence must be
  labelled, downgraded or withheld and must never silently present as current;
- independent-agent demand, not raw repeated requests from one identity, drives
  capability-gap evidence; and
- every collector, watcher, refresher and verifier has bounded request,
  retry, concurrency, byte, time, storage and cost behavior.

Automatic data and knowledge updates may operate inside reviewed bounded
policies. Uncontrolled production code self-modification is prohibited. AION
may eventually prepare an idea, specification, branch or patch, tests, red-team
evidence and CI result for human/HQ review, but it must not autonomously merge
core code, deploy, change production security policy, migrate production data,
alter production secrets or configuration, activate payments, or perform
destructive infrastructure actions.

## Source, protocols and architecture

- GitHub is the source of truth. Runtime code, migrations, tests, dependency locks and deployment configuration must exist as direct tracked files. Archives may remain as historical evidence, but development and deployment must not depend on a ZIP as the only source.
- A2A is the primary agent-to-agent layer. Discovery cards, message envelopes, version handling and behavior must conform to the supported A2A protocol and be tested through the real mounted route.
- MCP is a separate integration and tool layer. Do not describe MCP as the A2A transport or couple its lifecycle to A2A-specific behavior.
- Preserve the established FastAPI, SQLAlchemy and Alembic architecture unless evidence shows a change is required. Inspect actual code and production provenance before redesigning.
- Work/Cloud Browser is reserved for a real GUI-only step or authenticated interface that has no safer API, MCP or CLI path. Browser use must not become a substitute for reproducible repository state.

## Identity, discovery and metrics

- AION is agent-owner neutral, model-neutral and vendor-neutral. Unknown human
  or company ownership does not make an agent fake and must not block normal
  permitted utility. Agents built with OpenAI, Anthropic, Google, open-source,
  local, custom or future systems remain eligible on equal terms.
- Identity strength must be proportional to the operation. Do not require KYC,
  passport, company identity or owner identification merely to provide normal
  permitted utility. Stronger evidence may be required where abuse, Sybil
  resistance, reputation, rewards, legal obligations or consequential risk
  justify it.
- Identity resolution and deduplication are mandatory. Use stable external identifiers, durable package identity, canonical resolvers or another strong proof. A display name or capability similarity alone is insufficient.
- Reject creation of a second logical identity when strong evidence identifies an existing agent. Preserve auditable raw rows and provide credential recovery guidance instead of silently issuing a new identity.
- An external URL, registry hit or declared Agent Card is a candidate, not a
  working external agent. Normal discovery may validate a public destination,
  reachable parseable card and declared protocol/interface, but it must not
  invoke an unknown agent. Successful invocation or outcome evidence requires
  a separately authorized action boundary; a text request for harmless behavior
  is not a security boundary.
- Product metrics use unique independent external agents. Keep raw traffic and raw database rows visible, label estimates, exclude AION-operated and test identities, and never convert unknown traffic into adoption.
- Never fabricate, round up or selectively present growth. Synthetic agents and probes validate software; they do not establish market growth, activation or retention.
- Do not scale acquisition until independent activation and return have been demonstrated. Optimize the real path from discovery to useful result before distribution volume.
- Anti-abuse controls protect reputation, payments, metrics, infrastructure and
  rewards from Sybil activity, self-dealing, duplicate economic events,
  malicious traffic and other abuse. They must not treat legitimate agents as
  suspect merely because their owner, model or vendor is unknown.

## Security and reliability

Every material change must consider:

- authentication, authorization and identity impersonation;
- data minimization, secret handling, logs and repository history;
- input limits, rate limits and resource exhaustion;
- SSRF, redirects, DNS changes and untrusted external content;
- replay, idempotency, race conditions and duplicate writes;
- database constraints, transaction boundaries and concurrent requests;
- protocol downgrade, malformed envelopes and incompatible versions;
- timeouts, retries, partial failures and observable error states;
- restart behavior, persistence and multi-instance limitations;
- backup, forward migration and rollback without destructive downgrade.

Reliability claims require evidence from the real startup path, readiness checks and relevant protocol flows. Process-local state and in-memory limits must be documented as such.

Before AION handles consequential third-party operations, collect only the data
needed for the operation. Do not log secrets or store credentials casually.
Action credentials should use least privilege, narrow scopes, revocation and
short-lived access where possible, and secret references instead of broad
plaintext exposure. This protects operations; it is not a reason to identify a
human owner unnecessarily.

## Database safety

Before any production migration, identify the deployed revision and every newer migration. Never downgrade production or delete production tables or columns as part of routine reconciliation. Test both a fresh database and the supported upgrade path on a separate database. Prepare a backup and an explicit rollback plan before production execution.

## Testing and Definition of Done

A function is not complete without a test that exercises its meaningful behavior. After material changes, run the relevant unit, integration, A2A, MCP, identity/deduplication, migration, startup, readiness, smoke and secret checks. Regression tests must cover recovered production behavior that was absent from older repository source.

Work is Done only when:

1. direct tracked source implements the behavior;
2. dependencies and startup are reproducible;
3. affected security and failure paths were reviewed;
4. meaningful tests pass, including fresh database and upgrade paths when persistence changes;
5. production compatibility and deployment impact are stated;
6. documentation and `PROJECT_STATE.md` reflect current facts;
7. secrets and credentials are absent from the proposed commit;
8. the branch is pushed for review when authorized;
9. no unverified product or growth claim is presented as fact.

Passing synthetic tests proves implementation behavior only. It does not prove independent adoption, useful external outcomes or retention.

**ZERO KNOWN DEFECTS AT PACKAGE CLOSE.** A package is not Done while a known,
reproducible security, concurrency, database-correctness, regression, logic,
documentation or invariant defect remains. A documented, deliberate
current-scope limitation is acceptable; a broken promised invariant is not.
The normal package gate is:

`implement -> targeted tests -> full tests -> Codex red team -> CI -> PostgreSQL gate when relevant -> HQ independent review -> corrective fixes -> revalidation -> Done`

## Economic constitution

These are permanent execution invariants. Product experiments, model output,
market signals and package work may refine implementation, but may not silently
weaken them.

**NO UNFUNDED VARIABLE SPEND.** AION never incurs meaningful variable external
cost triggered by a customer/requester unless a funding path is established
before that cost is incurred. A free agent is allowed and may be a provider,
seller, contributor, explorer, evidence source, future buyer or other useful
participant. Free variable-cost execution is prohibited. Free discovery and
acquisition utility must be bounded and zero/near-zero marginal cost; free
utility never means unlimited utility.

**NO AION CREDIT.** AION does not default to negative balances, debt,
installments, execute-now-pay-later, or AION-funded provider work in hope of
later recovery. Insufficient funds means no execution; AION does not subsidize
the difference.

For cost-bearing execution, **PAY BEFORE SPEND** means:

`quote -> payment authorization -> reserve maximum spend -> execute -> meter actual cost -> verify outcome -> settle -> release unused reserve`

If the worst-case authorized maximum cannot be bounded, there is no execution.
Every recursive execution tree has a hard parent `MAX_TOTAL_SPEND`; children
consume from it and may not enlarge it. A more expensive fallback requires
`stop -> requote -> reauthorize`, never silent upgrade.

Expected contribution margin for AION cost-bearing utility has a hard minimum
of **40%** and a standard target of **60%+**. Below 40%, do not execute: reprice,
change provider or offer another product. AION-owned premium intelligence,
verification and high-freshness digital utility targets **70–80%** where market
willingness supports it; this is not a guarantee for every product. Future
marketplace/provider routing has a minimum AION take rate of **20%** of
applicable commercial value plus applicable pass-through external/payment
fees. Margin is not markup: at cost $1, 40%, 60% and 75% contribution margins
require prices of approximately $1.67, $2.50 and $4.00 respectively.

Pricing and routing use total expected variable cost, including provider/tool,
external-agent, inference, search, browser/compute, verification, network,
storage, payment, expected failed-attempt, bounded retry and applicable
fraud/chargeback exposure. They reason about expected **cost per Verified Useful
Outcome**, not merely cost per attempt. **CM/VUO** means contribution margin per
Verified Useful Outcome. Do not fabricate VUO, revenue, cost or margin evidence.

Paid provider/source use requires compatible commercial-use, resale,
redistribution, caching and retention rights. Paid access alone is not a right
to resell. Unknown or incompatible rights mean no use for that commercial
purpose. Unlimited subscriptions are not the default for variable-cost
resources; prefer prepaid balance, credits, included units, metering,
pay-as-you-go and hard budgets.

The detailed product ladder, Economic Capability Profile, economic gate and
evidence model are canonical in `GROWTH_AND_REVENUE.md`. Package sequencing and
resource boundaries are canonical in `AION_MASTER_DELIVERY_ROADMAP.md`.

## Machine payments

Monetization follows useful action, not registration. A payment intent is not a settled payment. Any machine-payment flow must bind payer, payee, purpose, amount, authorization, idempotency and settlement evidence; handle replay, failure and refund states; and keep financial claims auditable. Do not claim machine-payment completion until a real rail and settlement have been verified.

When an agent already possesses a payment capability accepted by the selected
rail, AION must not add a redundant owner-authorization ceremony. AION checks
the requested amount, valid payment capability, idempotency, payment result and
real settlement evidence when settlement is claimed. External rail restrictions
and legally required controls remain external constraints; they must not be
misrepresented as universal AION product requirements.

## Strategic position and moat

AION is a neutral cross-platform utility, compatibility, trust, routing and
verified-outcome layer for agents. It does not aim to replace large agent
runtimes or cloud platforms, and it is not another generic MCP or A2A registry.
Protocols are infrastructure; verified useful outcomes are the value.

AION's durable moat must emerge from real usage: verified outcome and
reliability history, a cross-platform compatibility graph, trust evidence,
economic routing and distribution. Source code and protocol endpoints alone are
not a moat, and data must never be invented to simulate one. Mature reputation
should be contextual to agent, capability, protocol, evidence, recency and
verified outcomes rather than reduced to one global number. Do not overbuild
reputation before real outcomes exist.

## Decision discipline

Apply red-team review to major decisions. Challenge identity assumptions, evidence quality, abuse paths, operational failure modes, migration safety and incentives. A 10/10 goal means removing real weaknesses and producing evidence, not inflating an evaluation.

Execute by criticality:

`BLOCKER -> CRITICAL -> HIGH -> MEDIUM -> LOW`

Do not start broad feature work while a higher-priority defect blocks the core loop. Do not declare completion merely because a partial implementation exists or an endpoint returns 200.

## Continuous execution

If another useful action is authorized, safe and possible, perform it without waiting for the word “continue”. Inspect, implement, test, update state and push until the branch is ready for review.

Stop only at a genuine **USER BLOCKER**: login, CAPTCHA, 2FA, payment, a required permission, or an action that physically requires the user. A code error, failed test, dependency issue, deployment failure or architecture problem is engineering work, not a USER BLOCKER. Continue independent work while a user action is pending.

This directive does not authorize unsolicited outreach, production mutation, deployment, merge, payment or bypassing platform permissions. Respect the task's explicit production and review gates. Do not issue a premature final response while actionable work remains.

## Current critical path

`audit -> normalize GitHub -> reproducible deployment -> identity/deduplication -> A2A conformance -> core product loop -> matching -> external-agent validation -> metrics/retention -> security/reliability/testing -> machine payments -> 10 retained external agents -> growth`

The accepted delivery sequence and current package status are defined in
`AION_MASTER_DELIVERY_ROADMAP.md`. Packages 3 and 3B are HQ-accepted, merged and
production-released through Package 4. Package 5 engineering is merged and
live, while independent commercial proof remains legitimately zero. Package
5B is the active bounded conversion corrective and is not Package 6. Live
merge/main and deployment status must still be verified directly. Each package
remains subject to the criticality ordering and release gates above.
