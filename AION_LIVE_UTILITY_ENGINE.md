# AION Live Utility Engine

## Status and scope

This document defines the next product and architecture direction for AION. It
is additive to `AION_DIRECTIVE.md` and does not claim that the systems described
below are implemented. The current FastAPI, SQLAlchemy, Alembic, A2A and MCP
architecture remains authoritative until a bounded, reviewed change replaces a
specific part of it.

AION is evolving into a **Live Utility Engine for independent AI agents**. Its
purpose is to provide current, evidenced, compatible and actionable utility,
then learn from verified outcomes. It is not a static knowledge database, a
generic search engine, an indiscriminate crawler, a stale RAG dump, an
unverified directory, a generic news feed or a marketplace where listing
implies trust.

The long-term product progression is:

`recommendation -> safe action -> verified result`

The canonical utility loop is:

`discovery -> understanding -> first contact -> immediate utility -> optional join -> capability / need / offer -> matching -> useful result -> interaction -> reputation/history -> return -> monetization`

Registration alone is not utility. Traffic alone is not adoption. Synthetic or
AION-operated agents are not evidence of independent external adoption.

## Product gates

Utility comes before membership, acquisition and monetization. AION should not
scale acquisition until an independent external agent can receive a useful,
current result, complete a successful action and voluntarily return.

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
  articles and unverified agent claims.

Tier 3 information can trigger investigation but must not become verified truth
without stronger evidence.

### Freshness as a system property

Freshness is part of each consequential fact or capability, not a single global
daily job. The data model should support, where applicable:

- `observed_at`, `verified_at`, `valid_from`, `stale_after`, `expires_at`;
- `source_revision` and `verification_method`;
- event-driven, scheduled, TTL, demand-driven, impact-driven and usage-driven
  refresh; and
- an explicit confidence downgrade when material information is stale and safe
  refresh cannot be completed.

Refresh decisions should be policy-driven and testable. A recommendation must
not silently present stale consequential data as current.

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

### Self-obsolescence detection

AION should detect when its own knowledge, integrations or assumptions are
becoming outdated through a bounded pipeline:

`watch -> detect -> diff -> impact analysis -> prioritize -> verify -> update -> test -> engineering task if required`

High-value triggers include protocol revisions, breaking API or authentication
changes, new discovery mechanisms, payment standards, registry changes,
security advisories and material ecosystem shifts. Automated detection may
propose a change; it does not authorize code changes, deployment or unsafe
external action.

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
budgets, plus a disable or circuit-breaker path.

AION must not continuously crawl the internet or apply the same refresh cadence
to every fact. Refresh cost should be proportional to expected utility, change
rate, consequence of staleness and current demand.

## Directional measures

Useful future measures include fresh verified coverage, stale answer rate,
verification success, capability invocation success, recommendation acceptance,
verified outcome rate, time and cost to useful result, return after a useful
result, repeat capability and paid use, and personalized-delta usefulness.

These are directional metrics, not claims about current implementation. Outcome
quality has priority over database rows, registrations, listings and traffic.

## Phased roadmap

1. Architecture, data model and source/freshness policy.
2. Narrow MVP using a small number of Tier 1 sources.
3. Change detection, provenance and freshness evaluation.
4. Capability compatibility and explicit trust-state progression.
5. Personalized delta for returning agents.
6. Outcome telemetry with verification distinctions.
7. Utility-based ranking calibrated from outcomes.
8. Safe action and result-verification layer.
9. Broader ecosystem coverage based on demonstrated value.
10. Acquisition scale only after useful action and voluntary return are proven.

Each phase requires a bounded hypothesis, threat model, resource budget,
targeted tests and an explicit non-goal list. Do not implement several phases in
one broad change.

## Next bounded milestone

The pure contracts and durable Phase 1 persistence exist on repository main.
Package 1 is implemented on branch
`codex/package-1-live-utility-data-engine`: two bounded official protocol-release
sources, shared pinned HTTPS retrieval, adapter-specific structured
normalization, durable normalized material versions, separate verification
evidence, deduplication, lineage, structured change detection, deterministic
refresh execution and restart-safe current-state evaluation. Additive migration
`0006_live_utility_data` provides the storage that `0005` could not represent
without mutating append-only evidence during an unchanged re-verification.

Package 1 does not expose a public utility API and does not implement crawling,
compatibility ranking, personalized delta, outcome telemetry, watchers or
external action. Its immediate gate is exact-commit normal CI, PostgreSQL 18
fresh/upgrade/concurrency evidence and independent HQ review. Only after that
gate may Package 2 be defined as a separate bounded package.
