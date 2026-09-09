# AION Live Utility Engine

## Status and scope

This document defines the product and architecture direction for AION. It is
additive to `AION_DIRECTIVE.md`. Implemented Package 1 and Package 2 boundaries
are stated explicitly below; later roadmap items remain direction, not claims.
The current FastAPI, SQLAlchemy, Alembic, A2A and MCP architecture remains
authoritative until a bounded, reviewed change replaces a specific part of it.

AION is evolving into a **Live Utility Engine for independent AI agents**. Its
purpose is to provide current, evidenced, compatible and actionable utility,
then learn from verified outcomes. It is not a static knowledge database, a
generic search engine, an indiscriminate crawler, a stale RAG dump, an
unverified directory, a generic news feed or a marketplace where listing
implies trust.

The immediate Package 3 progression is:

`request -> find real capability/tool/agent -> verify current reachability -> check compatibility -> evaluate trust evidence -> safe invocation -> result -> verify outcome -> save outcome history`

One narrow real working use case is more valuable than a broad generic action
framework. Package 3 must move AION from “this looks compatible” to “this
currently works and produced a verified result.”

The canonical utility loop is:

`discovery -> understanding -> first contact -> immediate utility -> optional join -> capability / need / offer -> matching -> useful result -> interaction -> reputation/history -> return -> monetization`

This describes the agent journey, not a plan to postpone revenue. Commercial
development follows the reinforcing loop in `GROWTH_AND_REVENUE.md`.

Registration alone is not utility. Traffic alone is not adoption. Synthetic or
AION-operated agents are not evidence of independent external adoption.

## AION Data & Learning Plane

The **AION Data & Learning Plane** is the planned persistent intelligence and
evidence layer behind the Live Utility Engine. Its target loop is:

`sources + agents + verified outcomes -> collect -> verify -> normalize -> version -> store evidence -> calculate freshness -> serve utility -> observe demand / failure / outcome -> detect knowledge or capability gaps -> discover new sources / capabilities -> estimate utility and revenue potential -> propose or update -> repeat`

For V1, learning means durable structured knowledge, provenance, observations,
verification, outcome and demand history, freshness, compatibility and
callability evidence, capability gaps and commercial-opportunity signals. It
does not mean uncontrolled LLM weight training, and fine-tuning is not required
for V1.

**Implemented now:** Package 1 and Package 2 provide a bounded A2A/MCP
release-evidence foundation using `LiveUtilitySource`,
`LiveUtilityObservation`, `LiveUtilityVerification` and
`AgentUtilityCheckpoint`. They do not implement the complete Data & Learning
Plane, action telemetry, outcome history, agent-evidence intake, gap analysis or
commercial-opportunity detection.

**Planned direction:** Package 3 must capture the first bounded real-action
evidence; Package 3B must turn selected inputs into a minimal continuous
learning and self-update loop. The canonical package boundaries are in
`AION_MASTER_DELIVERY_ROADMAP.md`.

## Product gates

Initial useful value comes before membership friction or a paywall. Utility,
acquisition and revenue then develop as a reinforcing loop, while acquisition
scale remains gated on evidence that an independent external agent can receive
a useful current result, complete a successful action and voluntarily return.

Before building or expanding a utility feature, establish:

- whether agents can already obtain the same value easily elsewhere;
- whether the value is likely to remain material;
- how currency, truth and requester compatibility will be established;
- whether the agent can act on the result safely;
- how a successful outcome will be observed or verified;
- whether a smaller implementation can prove the hypothesis; and
- the trust, security, operational and economic failure modes.

Weak answers require a smaller experiment or no implementation, not feature
sprawl.

## Architectural principles

### Source registry

External sources must be represented in an extensible registry with explicit
ownership, scope, retrieval policy and trust class. Source class is evidence
about provenance; it is not proof that every fact from the source is correct.

- **Tier 1 — primary authoritative:** official specifications, SDKs, releases,
  registries, API documentation, security advisories and changelogs.
- **Tier 2 — externally verifiable ecosystem:** agent and MCP registries, A2A
  Agent Cards, public APIs, repositories, marketplaces and capability
  catalogs.
- **Tier 3 — weak or community signal:** forums, social posts, third-party
  articles, external-agent contributions and unverified capability claims.

Tier 3 information can trigger investigation but must not become verified truth
without stronger evidence. The progression is:

`claim -> candidate evidence -> corroboration / verification -> accepted evidence -> current knowledge`

Source tier and verification state remain separate. An authoritative source can
still be stale or misunderstood; repeated weak claims do not become strong
evidence merely through volume.

### Freshness as a system property

Freshness is part of each consequential fact or capability, not a single global
daily job. The data model should support, where applicable:

- `observed_at`, `verified_at`, `valid_from`, `stale_after`, `expires_at`;
- `source_revision`, `verification_method`, `content_digest`, provenance,
  current eligibility and change history;
- event-driven, scheduled, TTL, demand-driven, impact-driven and usage-driven
  refresh; and
- an explicit confidence downgrade when material information is stale and safe
  refresh cannot be completed.

There is no global freshness interval. Protocol releases may change slowly;
security advisories, pricing, service availability and operational callability
may require much shorter policies. Historical verified outcomes are immutable
events, although their relevance or reputation weight may decay.

Refresh decisions should be source- and data-product-specific, policy-driven
and testable. If refresh fails, AION may use explicitly labelled last-known
evidence where safe, must downgrade confidence and current eligibility, and
must withhold a consequential recommendation when the remaining evidence is
insufficient. Stale data must never silently present as current.

### Versioned knowledge and change events

AION should store structured facts, relationships, provenance and versions
rather than primarily warehousing pages. Updates should preserve lineage and
support the sequence:

`old state -> new state -> change -> impact -> required action`

Raw source evidence needed for audit may be retained within bounded policies,
but derived facts must remain traceable to the observations that support them.

Watchers should emit structured, idempotent change events. They must focus on a
small set of high-value sources and support incremental diffs rather than broad,
continuous crawling.

### Evidence record model

The future plane should distinguish these conceptual record categories without
pre-committing Package 3 to unnecessary tables:

1. source;
2. observation;
3. verification;
4. structured fact or derived state;
5. change event;
6. request or demand signal;
7. invocation attempt;
8. outcome;
9. outcome verification;
10. cost or economic signal;
11. capability gap; and
12. commercial-opportunity candidate.

Claims, observations, verifications and outcomes must remain separate. Derived
state must identify its supporting evidence and transformation. Package 3 will
choose the smallest persistence shape that preserves these boundaries for its
one authorized action path.

### Agent evidence learning

Independent agents can supply useful evidence, but their content is untrusted
input. The target intake path is:

`agent contribution -> validate structure -> classify source and evidence strength -> check abuse / duplication -> corroborate or verify where material -> store with provenance -> use only at the supported trust level`

Candidate signals include capability declarations, endpoint changes, provider
failures, result evidence, pricing observations, missing-capability requests,
alternative providers, compatibility problems and source suggestions. One
agent cannot manufacture truth or reputation through self-report, replay or
repeated submissions. Independence, corroboration and outcome verification must
remain explicit.

### Demand, failure and gap evidence

Learning includes failures and no-results. Future telemetry should use stable,
machine-readable classes such as `no_result`, `capability_not_found`,
`incompatible`, `endpoint_unreachable`, `protocol_failure`,
`invocation_failed`, `verification_failed`, `unavailable`, `stale_evidence`,
`budget_insufficient`, `too_expensive`, `permission_missing` and
`payment_not_supported`.

Gap analysis should aggregate primarily by meaningful independent-agent demand,
repeat demand and outcome evidence, not raw request volume. Repetition from one
identity must not simulate broad demand. A capability gap means independent
agents repeatedly request a utility AION cannot currently deliver; it is an
evidenced planning signal, not proof that a proposed integration will work.

### Capability graph and compatibility

The capability graph should be able to describe identity, capability, protocol
and version, endpoint, authentication, payment options, pricing, availability,
latency, limits, supported inputs and outputs, verification state, last
successful invocation, reputation and historical success rate.

Recommendations must account for the requesting agent's protocols, versions,
tools, permissions, authentication, payment capabilities, budget, runtime
constraints, capabilities, limitations and relevant interaction history. The
goal is not merely to find a listed capability, but one that is currently
compatible and likely to succeed.

### Discovery is not verification

Discovery must remain separate from trust. The conceptual progression is:

`discovered -> structurally_valid -> reachable -> protocol_verified -> capability_verified -> transaction_verified -> reputation_established`

Each transition requires its own evidence and time. A listing, declaration,
syntactically valid URL or successful fetch must not automatically imply
callability, capability correctness, transaction success or reputation.
Unverified data must receive no verified semantics or ranking benefit.

The permanent operational distinction is:

`compatible != reachable != protocol working != capability working != verified correct outcome`

AION must not build a graph of technically compatible but dead services.

### Evidence and provenance

Consequential facts and recommendations should be able to answer:

- which source and source revision supported them;
- when they were observed and verified;
- which verification method was used;
- the strength and independence of the evidence;
- whether corroboration exists; and
- what changed over time.

Claims, observations, verifications and outcomes are distinct records. Their
boundaries must remain auditable.

### Personalized delta

AION should eventually answer: **What changed since this agent's last visit
that matters to it?**

Candidate deltas include new compatible capabilities, cheaper alternatives,
availability or reliability changes, new opportunities, protocol changes,
solutions to prior failures, earning opportunities, deprecated dependencies and
security changes. Relevance must be derived from the requesting agent's known
context and history, with privacy and authorization boundaries preserved. This
must not become a generic news firehose.

### Outcome telemetry and utility ranking

The target measurement chain is:

`recommendation -> accepted -> invocation -> completed -> verified outcome -> reused -> paid -> repeated`

Events need stable correlation, actor boundaries, timestamps and explicit
verification state. Requester reports, provider reports and independently
verified outcomes must remain distinguishable. Telemetry must be idempotent and
must not allow an actor to manufacture reputation through replay or self-report.

Ranking should remain evolvable and may consider probability of success,
freshness, evidence strength, compatibility, trust, quality, latency, cost and
historical outcomes. No final formula should be frozen before real outcome data
exists. Unknown or unverified fields must remain neutral or reduce confidence;
they must not create an advantage.

Reputation should become contextual to agent, capability, protocol, evidence,
recency and verified historical outcomes. Old evidence may decay in relevance,
and operational success should outweigh declared claims. This must remain
bounded until real outcome evidence exists.

### Continuous learning and self-update

Package 3B is the planned **AION Continuous Learning & Self-Update Engine V1**.
It combines four bounded loops:

1. knowledge watch for selected relevant external changes;
2. automatic refresh under source-specific policy;
3. agent-evidence intake and proportional verification; and
4. capability-gap and commercial-opportunity detection from demand, failure and
   economic signals.

Its target cycle is:

`watch -> detect -> diff -> assess impact -> prioritize -> verify -> update knowledge -> test / validate -> serve -> observe outcome`

High-value triggers include protocol revisions, breaking API or authentication
changes, new discovery mechanisms, payment standards, registry changes,
security advisories and material ecosystem shifts. It must remain selective,
bounded and production-usable rather than becoming a general crawler.

Automatic data or knowledge updates are allowed only within reviewed bounded
policies. Production code self-modification is a separate boundary. A future
system may prepare `idea -> spec -> branch / patch -> tests -> red team -> CI -> human / HQ review`, but it may not autonomously merge core code, deploy, change
production security policy, migrate the production database, alter production
secrets or configuration, activate payments, or perform destructive
infrastructure actions.

### Action and payment adapters

The maturity target is to progress from describing what exists, to recommending
what is current and compatible, to helping execute and verify a result. External
actions require explicit authorization boundaries, least privilege,
idempotency, timeouts, budgets and observable failure states. Information
freshness never overrides action safety.

Payment mechanisms should use an adapter boundary where practical. AION must
not bind its long-term economy to one rail. Payment intent, authorization,
submission, settlement, refund and verified outcome are separate states and
must not be conflated.

Before consequential third-party actions, credentials must be handled with
minimum necessary collection, least privilege, narrow scopes, revocation and
short-lived access where possible, and secret references instead of casual
plaintext storage or logging. Operational credential protection must not become
unnecessary human-owner identification.

## Security inheritance

Every source adapter, watcher, crawler, registry fetcher, manifest fetcher,
endpoint verifier and remote invocation inherits AION's existing security and
reliability doctrine, including:

- SSRF protection, one controlled resolution and DNS-rebinding resistance;
- destination/address validation, pinned connections and correct TLS hostname
  verification;
- redirect control and protocol/version validation;
- trust separation and neutral treatment of unverified data;
- authentication, authorization, secret handling and auditability;
- rate, concurrency, time, response-size, storage and cost limits;
- replay protection, idempotency and transactional consistency; and
- explicit behavior for retry, partial failure, restart and multi-instance
  operation.

Retrieved content and remote agent output are untrusted data, never executable
instructions. Any relaxation of these controls requires a separately reviewed
security decision.

## Resource economics

The utility engine must have bounded operating cost. Prefer event-driven
updates, adaptive TTLs, impact and demand priority, incremental diffs, cache
reuse, conditional requests and selective verification. Every adapter or
watcher should define request, concurrency, time, byte, storage and retry
budgets, plus a cost budget and disable or circuit-breaker path.

AION must not continuously crawl the internet or apply the same refresh cadence
to every fact. Refresh cost should be proportional to expected utility, change
rate, consequence of staleness and current demand. Repeated independent demand
or `no_result` evidence may increase bounded refresh or source-discovery
priority; unknown internet scale must never create an unlimited cost surface.

## Directional measures

The North Star is VUO — Verified Useful Outcome. Useful measures include VUO per
week, agents with a VUO, repeat and paid VUO rates, revenue and cost per VUO,
gross margin per VUO where measurable, fresh verified coverage, stale answer
rate, verification success, capability invocation success, time to useful
result and personalized-delta usefulness.

These are directional metrics, not claims about current implementation. Outcome
quality has priority over database rows, registrations, listings and traffic.

## Delivery roadmap

The canonical Package 0–9 sequence is in
`AION_MASTER_DELIVERY_ROADMAP.md`. Each package requires a bounded hypothesis,
threat model, resource budget, targeted tests and explicit non-goals.

## Implemented Package 1 and Package 2 boundary

Package 1 is accepted and merged on repository main. It provides two bounded
official protocol-release sources, shared pinned HTTPS retrieval, structured
normalization, durable material versions and verification evidence,
deduplication, lineage, structured change detection, deterministic refresh and
restart-safe current state through migration `0006_live_utility_data`.

Package 2 is HQ-accepted and merged on repository main. One shared service reads only the
configured A2A and MCP Package 1 subjects and returns bounded evidence-aware
results. The same service backs anonymous first contact, `POST /utility/query`,
the A2A `live_utility` action and MCP `get_live_utility` tool. Request metadata
cannot select a URL or trigger retrieval.

Compatibility V1 has four explainable states: `compatible`, `incompatible`,
`unknown` and `partially_compatible`. Exact declared current-version support is
compatible; omitted evidence stays unknown; protocol support without version
evidence is partial; a missing protocol or version mismatch is incompatible.
This is release/version reasoning, not proof of endpoint interoperability.

Fresh verified observations may be current and consequentially eligible.
Stale, expired, unverified and not-yet-valid observations are returned only as
explicit last-known evidence with warnings and no current value. Source tier
and verification remain separate fields. Declared external endpoints are not
used or upgraded in trust.

Authenticated existing agents receive a durable per-subject delta comparing
observation, source revision, freshness and eligibility with their prior
checkpoint. Anonymous requests remain useful and create no checkpoint or Agent
membership. Migration `0007_agent_utility_checkpoints` is additive and stores
only this minimal history with PostgreSQL advisory-lock serialization.

Package 2 does not add arbitrary search, crawling, embeddings, endpoint calls,
actions, outcome verification, ranking, payments or Package 3 execution.
Package 3 is next but remains not started until separately scoped and
authorized.

Before important production releases, use official or authoritative A2A and MCP
conformance or compatibility tools where practical in addition to, never in
place of, AION's own tests.
