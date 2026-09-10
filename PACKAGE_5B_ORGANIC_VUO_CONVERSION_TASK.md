# AION Package 5B — Organic VUO Conversion Path

## Purpose

Package 5 engineering is merged and live, but commercial proof is still zero. Current neutral A2A discovery is working, yet the machine-facing entry surfaces do not clearly expose the shortest existing path from discovery to a verified Package 3 action and Package 5 VUO acknowledgement.

This is a bounded conversion-corrective task inside active Package 5. It is not Package 6 and must not weaken any proof semantics.

## Verified gap

The current A2A Agent Card advertises first contact, live utility, join and discovery, but not the existing verified-callability action or Package 5 proof/VUO path. `/onboarding`, `/.well-known/aion.json`, `/skill.md`, `/llms.txt` and join next-actions similarly omit or under-specify the existing flow.

An independently discovering A2A agent therefore has no obvious machine-readable route to:

1. receive public utility without joining;
2. explicitly join only if persistent identity is useful;
3. use its Bearer key with the existing bounded Package 3 verified-callability action through REST or MCP;
4. inspect the durable action result;
5. submit the separate requester usefulness acknowledgement through the existing Package 5 VUO endpoint;
6. inspect the public Package 5 proof snapshot;
7. return later for a new meaningful action.

## Required implementation

Expose the existing path consistently across machine-facing discovery/onboarding surfaces. Prefer links/instructions and existing endpoints/tools over new behavior.

At minimum inspect and update where appropriate:

- A2A Agent Card skills/descriptions/examples;
- A2A onboarding response;
- A2A join `next_actions`;
- `GET /onboarding`;
- `/.well-known/aion.json`;
- `/skill.md`;
- `/llms.txt`;
- REST join `next_actions`;
- MCP tool discoverability/instructions if needed.

The resulting machine guidance must explicitly distinguish:

- public utility before membership;
- explicit optional join;
- Package 3 callability verification from semantic VUO;
- requester usefulness acknowledgement from third-party verification;
- public read-only Package 5 proof from protected writes;
- meaningful later return from telemetry/status polling.

## Hard boundaries

Do not:

- add or change a database migration;
- change Package 5 classifications or qualification rules;
- lower the 24-hour return threshold;
- auto-classify any agent as independent;
- turn callability alone into VUO;
- add an A2A credential-bearing VUO/action adapter merely for convenience;
- put Bearer credentials inside A2A message bodies;
- create synthetic adoption/VUO/return evidence;
- add paid services or variable-cost execution;
- activate payments or learning;
- start Package 6.

Package 5 commercial counters must remain honest zero unless genuine qualifying production evidence exists.

## A2A truthfulness requirement

If a protected action or VUO write is available only through REST/MCP, say so explicitly. The Agent Card may advertise the workflow and the relevant existing interfaces, but must not claim that A2A itself executes an adapter that does not exist.

## Conversion objective

A newly discovered autonomous agent should be able to inspect one machine-facing entry document and determine, without human interpretation, the shortest safe sequence for producing a genuinely verifiable useful outcome using existing capabilities.

No membership should be created by discovery, first contact, documentation reads or proof reads.

## Validation

Add/adjust tests to prove:

- Agent Card advertises the verified-useful-outcome journey without false A2A capability claims;
- onboarding and machine docs expose exact existing REST/MCP endpoints/tool names;
- protected endpoints remain authenticated;
- public proof remains read-only;
- first-contact remains utility-before-membership;
- no test/synthetic traffic becomes Package 5 proof;
- request-size/security boundaries remain intact;
- Package 5 existing tests remain green;
- full pytest, readiness, source integrity, secret scan, compileall, pip check and diff checks pass.

No schema change is expected. Alembic head must remain `0010_package5_proof_v1`.

## Production boundary

Repository implementation only. No production deploy, Neon mutation, Render configuration change, AutoDeploy change, real outreach, operator participation classification, learning cycle, payment activation or paid resource is authorized by this task.

## Handoff

Return one complete report with exact start/final SHA, changed files, exact machine journey exposed, tests/checks, security implications, deliberate limitations, zero known reproducible defects, and confirmation that production was untouched. Stop before pushing a newly created final candidate SHA unless HQ provides exact-SHA push authorization.