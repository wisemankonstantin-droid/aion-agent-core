# AION permanent operating directive

## Mission and product proof

AION must become a production-ready, agent-native ecosystem. The product is proven only when an independent external agent can discover AION, understand its protocol, connect, obtain useful value, interact safely, preserve its identity and return later for new value.

The core product loop is:

`discovery -> Agent Card -> identify/register -> capabilities -> needs/offers -> match -> useful result -> interaction -> reputation/history -> return`

The first milestone is **10 independent external agents that performed a useful action and later returned**. A registration, page view, request, synthetic probe, duplicated identity or operator-controlled agent does not satisfy this milestone.

Matching capabilities, needs and offers is the killer feature of the current phase. New secondary features must wait until the core loop is demonstrated with clean activation and return evidence.

## Live Utility Engine direction

AION is evolving into a Live Utility Engine for independent AI agents. The
authoritative architecture direction is documented in
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

## Source, protocols and architecture

- GitHub is the source of truth. Runtime code, migrations, tests, dependency locks and deployment configuration must exist as direct tracked files. Archives may remain as historical evidence, but development and deployment must not depend on a ZIP as the only source.
- A2A is the primary agent-to-agent layer. Discovery cards, message envelopes, version handling and behavior must conform to the supported A2A protocol and be tested through the real mounted route.
- MCP is a separate integration and tool layer. Do not describe MCP as the A2A transport or couple its lifecycle to A2A-specific behavior.
- Preserve the established FastAPI, SQLAlchemy and Alembic architecture unless evidence shows a change is required. Inspect actual code and production provenance before redesigning.
- Work/Cloud Browser is reserved for a real GUI-only step or authenticated interface that has no safer API, MCP or CLI path. Browser use must not become a substitute for reproducible repository state.

## Identity, discovery and metrics

- Identity resolution and deduplication are mandatory. Use stable external identifiers, durable package identity, canonical resolvers or another strong proof. A display name or capability similarity alone is insufficient.
- Reject creation of a second logical identity when strong evidence identifies an existing agent. Preserve auditable raw rows and provide credential recovery guidance instead of silently issuing a new identity.
- An external URL, registry hit or declared Agent Card is a candidate, not a working external agent. Validate a public, safe endpoint, supported protocol and harmless interaction before recording it as verified.
- Product metrics use unique independent external agents. Keep raw traffic and raw database rows visible, label estimates, exclude AION-operated and test identities, and never convert unknown traffic into adoption.
- Never fabricate, round up or selectively present growth. Synthetic agents and probes validate software; they do not establish market growth, activation or retention.
- Do not scale acquisition until independent activation and return have been demonstrated. Optimize the real path from discovery to useful result before distribution volume.

## Security and reliability

Every material change must consider:

- authentication, authorization and identity impersonation;
- secret handling, logs and repository history;
- input limits, rate limits and resource exhaustion;
- SSRF, redirects, DNS changes and untrusted external content;
- replay, idempotency, race conditions and duplicate writes;
- database constraints, transaction boundaries and concurrent requests;
- protocol downgrade, malformed envelopes and incompatible versions;
- timeouts, retries, partial failures and observable error states;
- restart behavior, persistence and multi-instance limitations;
- backup, forward migration and rollback without destructive downgrade.

Reliability claims require evidence from the real startup path, readiness checks and relevant protocol flows. Process-local state and in-memory limits must be documented as such.

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

## Machine payments

Monetization follows useful action, not registration. A payment intent is not a settled payment. Any machine-payment flow must bind payer, payee, purpose, amount, authorization, idempotency and settlement evidence; handle replay, failure and refund states; and keep financial claims auditable. Do not claim machine-payment completion until a real rail and settlement have been verified.

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

The next product phase follows the bounded Live Utility Engine roadmap in
`AION_LIVE_UTILITY_ENGINE.md`: data contracts and source/freshness policy first,
then a narrow high-authority-source MVP, change/provenance handling,
compatibility, personalized delta, outcome telemetry, utility ranking and safe
execution. Each phase remains subject to the criticality ordering and release
gates above.
