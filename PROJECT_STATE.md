# AION PROJECT STATE

## Checkpoint

Date: 2026-09-20

Repository: `wisemankonstantin-droid/aion-agent-core`

This file is the concise mutable repository checkpoint.

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

## Current verified GitHub state

Current verified `main`:

`e1bbbec76be43de39ad213d2fe0ebb6f12d144d7`

PR #13, **Make AION launch and commerce agent-native**, is merged.

Exact pre-merge candidate:

`f3bc436de3dde30e18235597e5e71c179ae6e8ec`

Exact-candidate validation:

- AION CI push run #329: success;
- AION CI PR run #330: success;
- PostgreSQL pre-production release gate #68: success;
- PostgreSQL gate included fresh/upgrade migrations, application/concurrency,
  startup and readiness.

The candidate tree and merge-main tree are identical.

Post-merge exact-main AION CI:

- run #331;
- exact SHA `e1bbbec76be43de39ad213d2fe0ebb6f12d144d7`;
- success;
- locked install, dependency integrity, secret scan, full pytest, readiness,
  migration smoke and MCP/A2A interoperability passed.

Repository Alembic head:

`0016_official_data_execution_v1`

Current release identity expects:

`0016_official_data_execution_v1`

## Current verified production state

Render service:

`aion-agent-core-live`

Service ID:

`srv-daei9gpt0dsc73abhs10`

Workspace:

`tea-daehtv2d0e5s738ir540`

URL:

`https://aion-agent-core-live.onrender.com`

Region:

Frankfurt

Branch:

`main`

AutoDeploy:

OFF

Service is not suspended.

Build command:

`python -m pip install --require-hashes -r requirements.txt`

Start command:

`python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Current verified live deploy:

`dep-daju1vdg1s2s73c6gtp0`

Current verified live application commit:

`18afa934fdddef2a0489874c5ac2446fcf947475`

Deploy status:

LIVE

Therefore repository main is newer than production.

The current live artifact expects schema:

`0014_conversation_intel_v1`

Repository migration chain after that revision is linear:

`0014_conversation_intel_v1 -> 0015_x402_exact_upfront_v1 -> 0016_official_data_execution_v1`

Both upgrades are additive on upgrade: each creates its new table/indexes and
does not drop existing production tables or columns.

The exact live database revision was not independently re-read in the current
read-only verification. A Render read-only SQL attempt failed because the
connector could not establish the required SSL/TLS session. Do not convert that
tool failure into a guessed database revision.

A Render PostgreSQL instance named `aion-agent-db` is visible and available in
the workspace. Inventory presence alone does not prove the web service's active
DATABASE_URL association.

Reverify production DB identity/revision before the next production write if a
safe unambiguous method is available.

## What is production-live

The verified live ancestry includes the established AION foundation and the
pre-`0015` application line, including:

- core REST/MCP/A2A foundation;
- live utility and compatibility;
- safe action/callability foundation;
- continuous learning foundation;
- historical Package 5 compatibility/proof surfaces;
- Economic Execution Kernel V1 with real-money behavior disabled;
- Ambassador infrastructure;
- Conversation Intelligence V1;
- Commercial Router code present in the live commit ancestry where applicable.

Do not infer a capability is live merely because it exists in current main.
Current Render deploy provenance wins.

## What is merged to main but not yet production-live

Current main additionally contains:

- `0015_x402_exact_upfront_v1`;
- `0016_official_data_execution_v1`;
- direct authenticated `world_bank.population.latest` execution;
- machine-verifiable World Bank result/provenance/freshness handling;
- PR #13 agent-native machine journey and compatibility correction.

These require a separately authorized production release.

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

Real-money behavior remains disabled.

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

`verified current main -> controlled production deploy -> migrate to repository head -> live readiness/release verification -> bounded zero-cost World Bank production smoke -> machine discovery/distribution -> remove agent friction -> prepare/enable priced machine commerce -> first SAT -> repeat SAT -> positive contribution margin -> scale`

The next write step is a controlled production release of current verified main.

That release is NOT authorized merely by this document.

Before deploy:

1. reverify GitHub main is still the intended tested SHA;
2. reverify Render service and AutoDeploy OFF;
3. reverify live deploy provenance;
4. resolve production DB association/revision if safely possible;
5. preserve current production configuration/secrets;
6. keep real-money activation disabled unless separately authorized.

## Continuous execution rule

Do not stop at documentation, outreach or proof ceremony when another safe,
authorized launch-critical action exists.

Do not repeat broad architecture audits.

Do not repeatedly re-prove an unchanged exact-SHA fact.

Continue until a genuine owner/control-plane gate, hard external technical
dependency or unsafe ambiguity is reached.
