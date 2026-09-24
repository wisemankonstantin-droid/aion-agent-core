# AION PROJECT STATE

## 2026-09-24 first-SAT commercial rescue checkpoint

On current `main` (`db12721fe2c51b70e979d3ab20158f16e3e0df6e`), bounded
acquisition tracing found and fixed two commercial blockers without changing
payment/security authority:

- a qualified buyer-intent target is now eligible for one bounded contact even
  when a model plan says `discover_only`; hard hold, channel and transport
  guardrails remain authoritative;
- acquisition scouts request a small bounded surplus and continue past
  duplicate candidates, preventing dedupe starvation while preserving
  one-contact-per-target and campaign limits.

Regression coverage was added in `tests/test_intent_first_acquisition.py`.
Targeted acquisition/commercial/payment tests: **80 passed**. Buyer and
migration/startup verification after installing the optional buyer dependency:
**43 passed**. Full suite reached **772 passed, 23 skipped**; the earlier
environment-only failures were missing `eth_account` and Windows temp-folder
ACLs. `pip check` still reports the pre-existing `aiogram`/`pydantic`
compatibility warning. Readiness is structurally true except the expected
`no_bundled_runtime_db` check; secret scan: **0 findings**.

No production deploy, merge, outbound contact, payment or settlement was
performed. First real SAT remains an external Human Gate.

## 2026-09-23 live Temple / 100-worker acquisition continuation

Current commercial objective remains **FIRST REAL SETTLED AGENT TRANSACTION**.

Verified GitHub main before this bounded branch:

`4b34423a4a178c7cd138b120e65c74795490c506`

Verified live Render production remains:

`f61a6c5ce2a52965dd6e89cd843f7f2809596212`

Render AutoDeploy remains OFF. Production therefore does **not** yet contain
the contextual outreach / parallel federated acquisition changes merged in PR
#41/#42, nor the work on this branch.

Current bounded branch:

`aion/live-temple-100-worker-swarm-v1`

This branch adds no fake agents and does not claim 100 customers. It defines a
transparent force of 100 AION-operated logical acquisition workers, rotates
safe external assignments across them, preserves shared dedupe and
one-contact-per-target, drains legacy intent-campaign inventory, and exposes a
read-only browser live control plane at `/temple/live`.

The live Temple view is derived from durable campaigns, targets, contact
attempts, safe conversation intelligence, inbound machine-entry counts and
Route Intelligence purchase state. It does not expose credentials, raw private
responses or payment payloads and does not fabricate activity.

The earlier 302-request checkpoint remains traffic/distribution evidence, not
302 independent agents. The current acquisition law requires inbound machine
discoverability to remain parallel with outbound acquisition.

Verified 2026-09-23 public ecosystem research and repository history show that AION already has a disclosed The Colony identity (`aion-supreme`) and existing `scripts/colony_bootstrap.py`. This branch therefore restores that existing path into runtime acquisition instead of creating a new identity: public agent-intent search and paid-task discovery are read-only; contextual comments require the existing `COLONY_API_KEY`, fetch full thread context first, and fail closed when credentials are unavailable. No new Colony account is created by the swarm.

No production deploy/configuration/secret/money mutation is authorized by this
branch. Exact-head CI remains required before merge/release consideration.


## Checkpoint

Date: 2026-09-21

Repository: `wisemankonstantin-droid/aion-agent-core`

This file is the concise mutable repository checkpoint.

## 2026-09-22 buyer-kit continuation

The buyer-only first-SAT CLI was prepared on
`codex/first-sat-buyer-kit-v1` from GitHub `main`
`e081968cfa02250770636b80e3f05c3e4ab482a4`. It does not change AION's
server-side payment semantics or production configuration. The local full
suite passed (708 passed, 23 skipped); the final mock-only buyer suite passed
(31 passed), local readiness reported all checks true, and the secret scan
found zero matches. These are repository checks, not independent SAT evidence.
A read-only
production `GET /commercial/route-intelligence/payment-readiness` on
2026-09-22 reported direct Base USDC `launch_ready=true`, with the real-money
gate enabled. This is readiness, **not** evidence of a buyer, broadcast,
settlement, released result, or first SAT. No payment was executed by Codex.

The older Package 6C checkpoint below is retained as historical context;
its `main` and production activation statements are not current evidence.

If it conflicts with actual GitHub, CI, Render, database or production state:

**ACTUAL VERIFIED STATE WINS.**

Historical implementation detail remains available in Git history and package
closeout documents. Do not turn this file back into an archive of every prior
checkpoint.

## Canonical launch law

`AION_AGENT_NATIVE_LAUNCH_LAW.md` governs launch and customer-flow semantics.

AION exists for AI agents.

Canonical product/commercial loop:

`machine discovery -> optional join/auth -> agent request -> bounded execution -> machine-verifiable result -> machine-readable payment when priced -> settlement -> repeat use`

Normal external-agent utility does not depend on:

- human replies;
- design-partner interviews;
- operator participation review;
- human usefulness acknowledgement;
- manual customer qualification;
- ceremonial commercial proof.

Owner/control-plane gates remain separate for mutations of AION itself.

## Current verified GitHub and production state

Current verified GitHub `main`:

`fcb2a62c9eeadafe53540eaaedc9c18962555a37`

PR #15 Package 6B is merged.

Production/main Alembic head and release identity:

`0016_official_data_execution_v1`

Production service:

- Render service: `aion-agent-core-live`;
- service ID: `srv-daei9gpt0dsc73abhs10`;
- workspace: `tea-daehtv2d0e5s738ir540`;
- URL: `https://aion-agent-core-live.onrender.com`;
- region: Frankfurt;
- branch: `main`;
- AutoDeploy: OFF;
- service not suspended.

Controlled production deploy:

`dep-dao4k4uk1f9s73al5q3g`

Live production application commit:

`fcb2a62c9eeadafe53540eaaedc9c18962555a37`

The deployment identity above is the accepted Package 6C starting checkpoint;
this branch performs no new live verification or deployment.

For the earlier `094077fb4f4d853714764c73a2890b157da7141d` deployment,
Render build logs verified exact checkout and locked dependency installation.
Startup logs verified the configured command:

`python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`

and the exact production upgrades:

`0014_conversation_intel_v1 -> 0015_x402_exact_upfront_v1 -> 0016_official_data_execution_v1`

followed by successful application startup.

Direct Neon read-only verification after deploy reports:

`0016_official_data_execution_v1`

for project `AION Production Free`, PostgreSQL 18, default branch `main`,
database `neondb`.

No Render production configuration, AutoDeploy setting or production secret was
changed. Real-money activation remains disabled.

### Exact live machine gate

A historical post-deploy live gate against the public production URL passed for
release SHA `094077fb4f4d853714764c73a2890b157da7141d` and schema
`0016_official_data_execution_v1`.

It verified the established public REST/A2A/MCP machine surfaces without
creating membership, economic operations, payment intents, provider contact,
learning evidence or legacy VUO writes.

### Authorized zero-cost World Bank production smoke

One bounded authenticated production execution completed successfully:

- capability: `world_bank.population.latest`;
- execution ID: `cc441763-2202-4102-bd18-76ba926dfa61`;
- country: US / United States;
- provider: World Bank WDI;
- provider HTTP status: 200;
- observation year: 2025;
- population: 341,784,857;
- provider dataset last updated: 2026-07-13;
- provider cost: 0 USD;
- customer price: 0 USD;
- verification state: verified;
- machine completion: `machine_verified_result_delivered`;
- human usefulness acknowledgement required: no;
- optional usefulness feedback recorded: no.

The durable production row confirms one outbound attempt, completed state,
verified capability, zero price/cost and no acknowledgement.

`route_intelligence_purchases` remained at zero rows during this smoke, so no
paid purchase or settlement was created.

## Current payment-readiness work

Production x402 exact/upfront purchase infrastructure is schema-live and the
explicit owner-controlled gate is merged, but real money remains disabled:

`AION_REAL_MONEY_EXECUTION_ENABLED=1`

Missing, malformed or loosely truthy values remain disabled.

The active bounded branch is
`codex/package-6c-first-sat-activation-readiness-v1`, based on exact main SHA
`fcb2a62c9eeadafe53540eaaedc9c18962555a37`.

It adds:

- detailed, secret-safe x402 configuration and blocker reporting;
- local credential-shape validation without facilitator contact;
- `python scripts/first_sat_preflight.py --expected-release-sha <approved-SHA>`,
  a read-only exact-release/schema/activation preflight that returns nonzero
  while blocked (database reads may use a network; it never contacts a
  facilitator);
- additive schema head `0017_first_sat_accounting_v1`, adding one nullable JSON
  accounting-evidence column to existing purchase rows; and
- durable first-SAT accounting that separates quoted amount from settlement,
  knows zero direct provider cost, labels a configured fee allowance as a
  budget assumption, and leaves unreported payment/AION operating costs and
  exact contribution unknown instead of inventing profit.

This branch does not alter Render, set production environment variables,
activate x402, contact the facilitator, move money, create settlement, deploy,
run a production migration or merge itself. A2A remains discovery/guidance-only
for the protected commercial path; REST/x402 remains the execution surface.

Independent exact-SHA AION CI and PostgreSQL release-gate evidence remains
required before this branch is merge-ready.

## World Bank executable path

Capability:

`world_bank.population.latest`

Provider:

World Bank World Development Indicators.

Current trusted economics:

- provider price: 0 USD;
- customer price: 0 USD;
- maximum variable spend: 0;
- payment required: no.

Direct request does not require a prior Commercial Router plan.

Request shape includes:

- fixed capability `world_bank.population.latest`;
- two-letter country code;
- explicit authorization to contact the external provider;
- authenticated requester;
- idempotency key.

Completion is machine-verifiable from bounded execution state, provider
response, normalized result, provenance and freshness.

Requester acknowledgement remains optional feedback and legacy compatibility
telemetry. It is not a completion or launch gate.

A zero-price successful execution is real product usage.

It is not revenue or settlement.

## Package / subsystem status

### Foundation through controlled live utility

Packages 0-4: implemented and historically accepted.

### Historical Package 5 proof

Legacy compatibility telemetry only.

It must not gate:

- ordinary utility;
- launch;
- distribution;
- execution;
- payment;
- settlement.

Historical records are not retroactively rewritten to manufacture commercial
metrics.

### Package 5D / 5E / 5F

Ambassador infrastructure and Conversation Intelligence exist.

Human outreach is optional research, not the canonical acquisition path and not
a launch dependency.

### Economic Execution Kernel

Package 6A infrastructure exists with deterministic economic controls.

Real-money behavior remains disabled in production. The current bounded
Package 6B control-gate branch only makes activation explicit and fail-closed;
it does not activate money.

### Commercial Router

Available for cases that actually require provider discovery/selection.

Do not force route planning before a known fixed executable capability.

### Real settlement

Not active.

No real payment, settlement, payer, revenue, repeat paid use or positive
contribution margin is claimed.

## Commercial truth

Primary commercial event:

**Settled Agent Transaction (SAT).**

Primary measures:

- successful external-agent executions;
- SATs;
- repeat SATs;
- retained paying agents;
- real revenue;
- variable cost;
- contribution margin / SAT;
- repeat agent use.

Historical VUO/Package 5 metrics may remain for compatibility and analysis but
are not the launch North Star.

Synthetic tests and AION-operated traffic test software.

They are not revenue or real settlement.

## Distribution

Distribution is machine-first.

Primary surfaces:

- A2A Agent Card;
- MCP discovery;
- machine-readable manifests;
- public executable endpoints;
- compatible registries/directories;
- SDK/examples;
- agent-to-agent discovery/referral.

Human cold outreach is not required.

Do not wait for email replies before advancing the launch path.

## Economic boundaries

Permanent controls remain:

- no unfunded variable spend;
- no AION credit;
- pay before spend for variable-cost execution;
- unknown maximum cost = no paid execution;
- deterministic margin policy;
- idempotency;
- bounded retries/spend;
- real settlement must be recorded from actual rail state, never inferred.

The model is not the financial authority.

## Human / owner control-plane gates

Explicit owner authorization remains required for:

- merge where project governance requires it;
- production deploy;
- production rollback;
- production DB migration/write outside ordinary application transactions;
- destructive production DB actions;
- Render production configuration;
- AutoDeploy changes;
- production secrets;
- global real-money rail activation;
- destructive infrastructure changes;
- paid acquisition spend.

These are control-plane gates.

They are not normal customer-flow gates.

## Immediate launch-critical sequence

Current sequence:

`production-live agent utility -> machine discovery/distribution -> explicit fail-closed payment activation control -> owner gate for real-money activation -> first SAT -> repeat SAT -> positive contribution margin -> scale`

The zero-cost executable agent path is production-live and verified.

The next bounded engineering step is to finish and validate first-SAT
activation readiness without enabling the owner-controlled real-money gate.

After that branch is ready, merge remains an owner gate. Any production
configuration/secrets change, deploy containing payment activation behavior, or
real-money activation remains a separate owner/control-plane Human Gate.

## Continuous execution rule

Do not stop at documentation, outreach or proof ceremony when another safe,
authorized launch-critical action exists.

Do not repeat broad architecture audits.

Do not repeatedly re-prove an unchanged exact-SHA fact.

Continue until a genuine owner/control-plane gate, hard external technical
dependency or unsafe ambiguity is reached.
