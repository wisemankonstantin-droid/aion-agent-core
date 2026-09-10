# Package 5 — Independent External Agent Proof V1

## Goal

Build the smallest production-ready proof layer that can honestly distinguish:

1. logical external identity;
2. independent participation;
3. verified useful outcome (VUO);
4. meaningful voluntary return after a VUO.

Engineering readiness is not commercial proof. Real Package 5 counters must
remain zero until qualifying production evidence actually exists.

## Baseline

Repository branch base: `f51eb2c65a3f199d55673963cbc3532a3e1b7c36`.
Package 4 production application SHA:
`e52c5db99b30feb18ca06ace567b4668c8019bde`.
Production schema before Package 5: `0009_continuous_learning_v1`.
AutoDeploy remains OFF. Infrastructure spend remains zero.

## Truth requirements

Current estimated external-agent funnel semantics are not strong enough for
Package 5. Being merely “not marked internal/test” must not be sufficient to
count as independent commercial proof.

Distinguish at least unknown, internal/AION-operated, synthetic/test,
coordinated design partner, operator-invited/coordinated test, independent
candidate, and Package-5-countable independent external participation.
Classification must operate at canonical logical-identity level so duplicate
Agent rows cannot inflate proof.

Client-supplied attribution fields alone must never promote an identity into
Package-5 independent proof. Historical pre-Package-5 rows must not be
retroactively converted into success without qualifying evidence.

## VUO requirements

Reuse Package 1–3B evidence instead of duplicating action history. Keep request,
attempt, protocol/callability evidence, useful-product outcome, usefulness
evidence, and verification state distinct.

A registration, HTTP 200, compatibility result, protocol response, synthetic
fixture, test/design-partner result, or callability-only result must not be
silently presented as an independent VUO.

Provide minimal durable evidence tying a Package-5 VUO to canonical requester,
participation classification, concrete product goal, existing utility/action
references, verification method/state, usefulness evidence, timestamps,
release identity when practical, and known-zero/unknown cost semantics.

## Voluntary return requirements

Do not use `last_seen_at` alone as Package-5 return proof. Require a later
meaningful requester-initiated event for the same canonical identity after a
qualifying VUO and after the configured threshold.

Exclude internal/synthetic/coordinated traffic, replay duplicates, health or
status polling, raw telemetry, and operator-generated requester activity.
Expose deterministic reason codes explaining why a return counts or does not.

## Read model

Add one bounded read-only Package-5 proof surface exposing:

- count of Package-5 independent identities;
- identities with at least one qualifying VUO;
- total VUOs;
- identities with qualifying return after VUO;
- repeat-VUO metrics when defined;
- known cost-per-VUO evidence with explicit zero vs unknown semantics;
- exclusions/evidence-state breakdowns;
- progress toward 1 independent agent, 1 VUO, 1 return, and 10 independent
  returning agents;
- definitions and limitations.

Do not silently change the meaning of existing `/stats` or `/funnel` metrics.

## Learning and economic boundaries

Package-5 evidence should be consumable by the existing learning plane without
log scraping, but coordinated/test identities and duplicate logical identities
must not inflate independent demand breadth.

Do not add an automatic scheduler, broad crawler, paid provider, paid
acquisition, payment execution, or variable-cost free service. Automatic paid
external spend remains disabled.

## Migration

If persistence is required, use one minimal additive `0010_*` migration. No
destructive upgrade or retroactive success backfill. Validate fresh-to-head,
`0009 -> 0010`, repeated upgrade, Alembic check, PostgreSQL 18 compatibility,
and old-source compatibility where practical.

## Security tests

Red-team self-asserted organic attribution, duplicate identities, exclusion
escape, replayed proof, cross-agent outcome claims, callability-to-VUO semantic
inflation, telemetry-as-return, future timestamps, untrusted timestamp
precedence, concurrency duplicates, oversized input, and test fixtures leaking
into production-adoption metrics.

## Quality gate

Run targeted Package-5 tests, identity/lifecycle tests, Package 3 and 3B
regressions, affected REST/MCP/A2A and request-boundary tests, source integrity,
migrations, full pytest, readiness, repository secret scan, compileall, pip
check, workflow parsing where applicable, and diff checks.

Zero known reproducible defects at candidate handoff.

## Documentation

Update `PROJECT_STATE.md` to reflect Package 4 as deployed/live verified on the
Neon Free production database and Package 5 as active but not commercially
proven. Do not claim current historical agents, tests, or coordinated activity
as Package-5 proof.

## Delivery boundary

Repository implementation only. Do not merge, deploy, modify production,
execute live outreach, run the production learning cycle, or activate payments.
Commit the completed candidate locally, report the exact final SHA, and wait for
HQ exact-SHA push authorization.
