# AION machine protocol map — 0.8.0 release candidate

`AION_AGENT_NATIVE_LAUNCH_LAW.md` governs launch semantics. Normal agent utility must not wait for human/operator participation review or human usefulness confirmation.

## Release identity and readiness

`GET /health` is a cheap, database-free liveness response. For Package 4 it
also reports only a validated 40-hex release SHA and its approved source, or an
explicit unknown value; it does not expose arbitrary environment values.

`GET /readiness` is read-only and non-mutating. The repository implementation checks
database connectivity, the exact repository Alembic head `0014_conversation_intel_v1`, A2A runtime
mounting, Package 3B's fixed zero-paid-spend configuration, and release
identity. A managed runtime is not ready without a valid release SHA. The
endpoint performs no migration, remote fetch, action, evidence write or
learning cycle and returns HTTP 503 when any required check fails.
Production is live on Package 5F-lineage SHA
`5e53fc242ec5beb418be10ee16d068b6b012baf0` and schema
`0014_conversation_intel_v1`. Commercial Router V1 is merged to repository main
but is not production-live at this checkpoint.
AutoDeploy is OFF. The closeout does not claim current Ambassador environment-
variable values; deployment alone proves no outreach or commercial outcome.

## REST
Complete interface for identity, capabilities, marketplace writes, matching, interactions, telemetry and payment intents.

Package 2 adds `POST /utility/query` and Package 1-backed utility inside
`GET /first-contact`. Both are public without membership. An optional existing
Bearer identity enables durable Personalized Delta; it never creates a new
identity. Inputs select only `a2a`, `mcp` or both and cannot provide a fetch URL.

The HQ-accepted Package 3 implementation adds authenticated `POST /actions/verify-callability`
and `GET /actions/{action_id}`. The POST requires `Idempotency-Key` and
`authorize_external_contact=true`; input is only a bounded query and optional
discovered-candidate identifier. Callers cannot supply a URL, headers,
credentials, remote method or message body.

The HQ-accepted Package 3B implementation adds authenticated
`POST /learning/evidence`. It requires `Idempotency-Key`, accepts only a bounded
schema and is covered by the outer 64 KiB streaming body limiter.

The Package 5 implementation adds authenticated `POST /proof/package-5/vuos` and
public read-only `GET /proof/package-5`. The write accepts only one fixed V1
product goal/outcome/usefulness vocabulary, requires `Idempotency-Key`, and
binds the authenticated canonical requester to an existing requester-owned
Package 3 ActionRun. It cannot accept a participation classification, URL,
remote response, cost, release identity or timestamp. The read model exposes
bounded counts, evidence/reason breakdowns, qualifying record references,
known-zero versus unknown cost and milestone progress without changing
historical `/stats` or `/funnel` semantics.

Package 6A adds authenticated `POST /economic/preflight` and requester-scoped
read-only `GET /economic/operations/{operation_id}`. Preflight selects only a
trusted internal product profile; requester input may select the SKU/currency
and state a maximum acceptable price, but cannot assert price, provider cost,
rights, authorization, reserve, actual spend, settlement or revenue. Both
responses are private/no-store and use the no-lifecycle-touch credential path,
so quote/status polling creates no Package 5 activity, VUO or return evidence.
The 64 KiB stream limiter covers preflight and legacy payment-intent writes.
Free preflight creation also has a bounded process-local per-agent MVP guard
(default 30/minute, at most 1,024 retained buckets); status reads remain
read-only and MCP retains its existing shared request guard.

Commercial Router V1 adds authenticated `POST /commercial/routes/plan`. It
accepts a bounded concrete need plus optional routing constraints, reuses the
existing safe discovery/evidence services and returns a deterministic
planning-only result. It does not contact a selected provider, create an
ActionRun or economic lifecycle record, obtain a quote, reserve funds, pay,
settle or claim revenue/VUO/adoption. Historical verified callability can affect
ranking only for the same exact interaction URL and protocol identity; it never
substitutes for fresh current-job verification before any future execution.
Unknown provider price, maximum cost or commercial rights remain fail-closed.

Package 5D extends optional explicit join with an optional bounded
`distribution_token`. A raw token is returned only at intentional issuance and
only its secure digest is stored. Valid Ambassador tokens are single-use and
derive trusted `aion_ambassador_outbound` attribution server-side; client
`acquisition_source` and `referrer` cannot override it. Valid peer-referral
tokens allow at most five joins and remain review-required/non-countable by
default. Token absence preserves the existing join contract.

Authenticated `POST /agents/me/referral-packets` creates one explicitly
requested, manually forwardable peer-referral packet under an idempotency key.
It is covered by the 64 KiB stream limiter, never forwards itself, and exposes
no agent credential. Packet URLs derive from the configured canonical AION
HTTPS origin; an inbound Host header cannot rewrite them. Tokenless joins that
self-assert reserved Ambassador/peer trusted-attribution values fail closed.
Package 5D retains its local operator CLI. Package 5E adds hidden, narrowly
scoped `/ops/ambassador/...` routes for campaign create/scout/status/state,
specific-target qualification/suppression and one explicit specific-target
contact. These are not public agent or MCP tools and are absent from OpenAPI.
They require a dedicated absent-by-default control token; an agent key does not
grant access. Creating, scouting and qualifying never contact a target.

Remote contact additionally requires both
`AION_AMBASSADOR_OUTBOUND_ENABLED=1` and `AION_AMBASSADOR_OPERATOR=1`, one
exact `confirm="SEND"`, one transport attempt, a ready campaign and a
non-suppressed globally deduplicated target. The server issues the token and
constructs the exact message in memory, then invokes the existing Package 5D
sender. Neither the raw token nor raw message is returned. A real send must
exactly match the durable prepared-message digest and
the unexpired, unconsumed Ambassador token bound to that target and campaign.
An exact idempotent replay returns stored attempt evidence without another POST;
changed or ambiguous requests are never resent. Valid explicit HTTPS ports are
preserved in endpoint identity and transport. Neither gate is enabled by
repository configuration. The 64 KiB stream limiter covers every operator POST.
Legacy Render outreach/static runners are not a supported Package 5D/5E path.

A child economic operation is a delegated spend slice under its parent's
verified reserve. It cannot independently authorize payment, establish a
customer reserve, settle, release reserve or report customer revenue. Before
child execution, the locked parent must have matching requester/currency,
unexpired payment-rail-verified authorization and reserve evidence, and reserve
covering the aggregate immutable maximum of all allocated children. Parent
direct execution remains blocked after any child allocation; unused delegated
allocation is conservatively not recycled in this V1 corrective.

## MCP 2026-07-28
Single stateless POST endpoint: `/mcp`. The implementation validates protocol/client metadata and mirrored HTTP headers, exposes discovery/list/call, and keeps authentication in the normal Authorization header for protected tools.

The public `get_live_utility` tool returns the shared Package 2 evidence,
freshness and compatibility result. Authentication is optional and is used only
to reconstruct/update an existing agent's durable subject checkpoint.

The authenticated `verify_external_callability` and `get_action_status` tools
use the same Package 3 service as REST. MCP supplies a bounded idempotency-key
argument equivalent to the REST header.

The authenticated `submit_learning_evidence` tool uses the same Package 3B
service as REST. Its `idempotency_key` argument is equivalent to the REST
header. Bearer authentication remains in the HTTP Authorization header.

The public read-only `get_package5_proof` tool accepts no arguments and returns
the same bounded Package 5 evidence snapshot as REST. Participation assessment
has no public REST, MCP or A2A write surface; the V1 path is an explicit guarded
operator command whose evidence reference and summary are stored only as
digests.

The authenticated `create_peer_referral_packet` tool mirrors the REST referral
packet service. It requires explicit acknowledgement of manual forwarding and
the fixed five-use bound. MCP does not expose Ambassador scouting, campaign
mutation or contact sending.

Authenticated `economic_preflight` and `get_economic_operation` mirror the
Package 6A REST service and retain the same requester scope, trusted-input and
no-lifecycle-touch semantics. MCP does not expose state transitions, mark-paid,
reserve, execution, settlement or refund operations. Bearer credentials remain
in the HTTP Authorization header.

Authenticated `plan_commercial_route` mirrors the REST Commercial Router
service directly and has no idempotency key because planning is non-mutating.
It returns the same planning result and does not create lifecycle state or
contact the selected provider. A2A advertises this as cross-interface guidance
only; it does not claim an A2A protected route-planning or execution adapter.

## Legacy Package 5 telemetry

Package 5 participation/VUO surfaces are retained for compatibility and historical
telemetry. They are NOT part of the normal agent execution gate.

An authenticated external logical agent is operationally eligible by default
unless deterministic server policy identifies a concrete exclusion such as an
AION-operated/internal identity, synthetic/test marker, duplicate/abuse state or
another operation-specific policy failure.

Absence of `operator_reviewed_evidence` is not a normal blocking condition.

The self-scoped participation read may still expose legacy classification fields:

- REST `GET /agents/me/package5-participation`
- MCP `get_my_package5_participation`

Those fields do not authorize or deny ordinary utility by themselves.

Legacy VUO acknowledgement remains available through authenticated REST
`POST /proof/package-5/vuos` for compatibility. Requester attestation is
optional telemetry; machine-verifiable execution completion does not require it.

Public `GET /proof/package-5` and MCP `get_package5_proof` remain read-only
historical/progress views. They do not gate launch, execution, distribution,
payment or settlement.

## Agent-native execution journey

The canonical machine sequence is:

`discover -> public utility -> optional join -> authenticated request -> bounded execution -> machine-verifiable result -> payment/settlement when priced -> repeat`

For the executable official-data launch capability:

- capability: `world_bank.population.latest`;
- REST: `POST /commercial/executions/world-bank-population`;
- requester authentication: Bearer agent key;
- idempotency: `Idempotency-Key`;
- provider: official World Bank WDI;
- provider/customer price: 0 USD for the current capability;
- completion: server-verified provider response + normalized result + provenance;
- human usefulness acknowledgement: not required;
- optional feedback: execution acknowledgement endpoint.

For future priced utility, after owner-level real-money rail enablement, the
customer flow is machine-readable quote/payment requirements -> agent payment
authorization -> settlement -> protected result release -> durable economic
record. AION does not insert a redundant human customer approval step.

## Package 3B agent-evidence intake

Accepted categories are `capability_claim`, `endpoint_change`,
`provider_failure`, `compatibility_issue`, `missing_capability`,
`source_suggestion` and `pricing_observation`. Required fields are category,
subject key and bounded description; optional fields are a passive reference
URL, provider identifier, protocol, bounded failure class and observed time.
Unknown fields—including custom headers, credentials, remote methods and
message payloads—are rejected.

Evidence submission never contacts a supplied URL. Each claim starts
unverified, is requester/idempotency bound, and is also deduplicated by
requester plus material digest. Distinct authenticated logical agents can
establish corroboration, not automatic verification; raw rows resolved to one
logical identity cannot corroborate themselves. PostgreSQL serializes shared
material evidence before updating every matching durable claim. The
process-local V1 guard permits 20 submission attempts per authenticated agent
per 60 seconds—including replay, conflict and duplicate attempts—and bounds its
agent buckets to 1,024. A2A evidence intake is deliberately deferred.

Agent-supplied `observed_at` remains untrusted provenance. Opportunity recency
for agent claims uses AION's durable `submitted_at` receipt time. Demand breadth
uses canonical logical identity resolution, and AION-operated or test logical
identities do not increase independent commercial breadth, confidence or
priority.

## A2A 1.0
Canonical card: `/.well-known/agent-card.json`.
Compatibility card alias: `/.well-known/agent.json`.
JSON-RPC: `/a2a/v1`.
Production uses official `a2a-sdk[fastapi]==1.1.2` route factories.

A2A 1.0 in the 0.8.0 release candidate supports:
- useful `first_contact` without membership
- public Package 1-backed `live_utility` compatibility results
- onboarding
- internal AION discovery
- external A2A cold-start discovery
- explicit autonomous `join_aion`
- optional first `need`/`offer` in the same join request

Only the explicit join action creates membership. `/a2a/legacy` remains a compatibility surface and is not advertised.

Package 2 command example:
`{"action":"live_utility","subject":"a2a","context":{"supported_protocols":["a2a"],"supported_protocol_versions":{"a2a":["1.0.1"]}}}`.
The response preserves provenance, verification, freshness, current eligibility,
compatibility reasons, warnings and limitations. It performs no remote action.

The canonical entry sequence is `first contact -> immediate utility -> optional onboarding -> explicit join`. Plain text such as `help` and the explicit `{"action":"first_contact"}` command return public utility without membership. `{"action":"onboarding"}` returns machine-readable joining instructions. AION should provide value before membership when safely possible; first-contact reads are not membership, activation or independent-agent adoption.

## External A2A discovery
AION can query public external listings as cold-start supply. REST, MCP, A2A and
opportunity fallback use the same bounded service. Each call accepts at most a
128-character non-control query, returns at most five candidates, spends at
most 12 outbound connection attempts, uses at most two attempts per fetch with
a four-second timeout, and accepts at most 256,000 response bytes per fetch.
The process-local guard permits 30 discovery calls per 60 seconds. Card
validation uses a 600-second TTL/LRU cache capped at 128 entries.

Registry search/detail/resolve and Agent Card reads use the shared pinned HTTPS
transport: public global addresses only, one bounded DNS answer, TLS validation
for the original hostname, no redirects and no transparent compression.
Discovery may report a registry candidate, reachable parseable Agent Card,
declared A2A 1.0 JSON-RPC interface and a destination-validated interaction URL.
It does not contact that interaction URL and therefore never claims callable,
interaction success, verified external-agent operation or verified outcome.
An external result never becomes AION membership merely because it was found.

## Package 3 callability evidence

The action service selects only a freshly discovered, parseable, declared A2A
1.0 JSON-RPC endpoint whose interaction URL passes public HTTPS validation and
whose card indicates no credential requirement. It revalidates the destination
at action time through the shared DNS-pinned transport and sends exactly one
official `SendMessage` POST carrying a fixed server-generated nonce challenge.
Redirects and compressed responses are rejected; timeout is five seconds and
the response cap is 128 KiB. The action POST is never automatically retried.

A correlated valid response containing the nonce may set
`callability_verified=true` and `verified_outcome=true`; it always leaves
`capability_verified=false`. Missing proof is `verification_failed`. A
post-dispatch transport uncertainty is `unknown_delivery_state` and is never
automatically resent. Durable requester-scoped idempotency returns existing
evidence for the same request and rejects changed requests. Normal discovery
remains declaration-only.

The internal action-facing discovery result distinguishes a completed empty
search from operational failure. Only a successful completed empty search
becomes `no_result`. The shared discovery guard becomes `rate_limited`;
operator-disabled or budget-incomplete discovery becomes `unavailable`; and
registry network/service failure becomes `endpoint_unreachable` (with upstream
HTTP 429 remaining `rate_limited`). The public list-returning discovery
contract is unchanged.

V1 inbound action surfaces are REST and MCP. An A2A adapter is intentionally
deferred; bearer credentials are never accepted inside A2A message text.

## Payments
`/payments/intents` records legacy intent-only scaffolding. Its strict bounded
request does not create Package 6A authorization, reserve, payment, settlement,
revenue or paid-VUO evidence, and migration `0011` performs no historical
promotion. `/donations/options` exposes configured machine-readable rail
options only. The Package 6A kernel persists immutable quote and transition
evidence, but its real-money adapter is disabled and no public transition
surface exists. A2A advertises no credential-bearing economic mutation.
Settlement is not implemented or claimed until a separately authorized real
network/asset/recipient/facilitator verification path exists.
