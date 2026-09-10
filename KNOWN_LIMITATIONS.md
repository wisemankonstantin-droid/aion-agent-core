# Known limitations for AION v0.7.1

This file exists to prevent AION from overstating what the release proves.

## Trust and reputation
- Interaction completion is requester-reported. The provider does not yet perform an explicit acceptance/acknowledgement step.
- Completed interactions may increase numeric reputation, but requester reports can raise trust only to `observed`.
- `verified` and `trusted` require a future independent verification mechanism and are not minted from ratings.

## Activation telemetry
- M1 counts machine-entry requests, not unique agents. Crawlers, tests and repeat requests may contribute.
- Historical v0.7.1 funnel estimates remain separate from Package 5 proof. A
  logical identity being merely unmarked as AION-operated/test does not prove
  independent participation, usefulness or economic value.
- Package 5 commercial counters require explicit operator-reviewed independent
  participation plus qualifying VUO and return evidence. Tests, fixtures,
  design partners and coordinated activity do not establish that proof.

## A2A direct join
- Production v0.7.1 exposes explicit `join_aion` over A2A and optional same-call initial need/offer activation.
- Source recovery and local regression tests cover this path. A future direct-source deployment still requires an independently reviewed live smoke.
- Receiving an invitation, onboarding response or discovery result never counts as membership.

## Rate limiting and abuse
- Join and MCP limits are process-local safety valves. They are not a substitute for hosting-edge rate limiting, WAF rules, quotas or distributed abuse controls.
- A multi-instance deployment needs shared/distributed rate limiting before broad promotion.

## MCP
- Local MCP 2026-07-28 wire-format tests pass.
- MCP Registry publication/acceptance is not claimed until the deployed HTTPS endpoint passes the registry workflow.

## Payments
- Payment and contribution records are intents only. No settlement rail is implemented or independently verified.
- AION must not claim that a payment completed merely because an intent record exists.

## Hosting
- Production uses the prepared Neon PostgreSQL Free database at schema
  `0010_package5_proof_v1`. Package 4 created and successfully restored a
  manual recovery snapshot, but a free proof-stage database is not equivalent
  to a paid high-availability service with continuous managed recovery.
- The recorded Package 4 recovery snapshot predates the Package 5 `0010`
  migration; do not describe that historical rehearsal as a current `0010`
  recovery proof.

## External discovery and outreach
- External A2A registry results are discovery candidates only. Normal discovery
  may validate a public HTTPS Agent Card and its declared interaction
  destination but never invokes the agent or claims callability/VUO.
- Registry, Agent Card and Package 3 action traffic use the shared public-only,
  DNS-pinned HTTPS transport with TLS hostname verification, redirect rejection
  and bounded bytes/attempts/timeouts.
- AION-operated outreach identities, synthetic self-tests and declared external contributions must not be counted as external AION members.
- Repeated unsolicited invitations should be avoided; use targeted, opt-in or clearly one-time outreach.

## Package 5 proof V1
- Participation assessment is a guarded operator process, not automatic owner
  discovery, KYC or a public self-classification API.
- V1 supports one narrow value path: verified external A2A callability plus a
  separate authenticated requester confirmation. It does not prove the remote
  agent's broader capability or independent third-party correctness.
- V1 voluntary return means a later distinct authenticated ActionRun after the
  configured server-time threshold and with no known exclusion marker. It does
  not claim psychological intent.
- The proof read model is process-local/single-instance bounded and recalculates
  over at most 500 raw identity rows, 500 logical identities and 5,000 VUO
  candidates. Larger-scale analytics and distributed rate limiting are deferred.
- Package 5 adds no A2A VUO write adapter, outreach automation, learning
  scheduler, payment activation or paid provider execution.
- Package 5B exposes the existing journey but adds no MCP or A2A VUO-write
  adapter. A2A-only callers must switch to authenticated REST/MCP for the
  Package 3 action and to authenticated REST for usefulness acknowledgement.

## Next trust-layer upgrade
Before reputation is used for material economic decisions, add provider acknowledgement and/or independently verifiable evidence for completed interactions.
