# Production source recovery — AION 0.7.1

Audit date: 2026-09-07. All Render access in this recovery was read-only. No deploy, service setting, environment value or database row was changed.

## Production provenance

| Field | Verified value |
|---|---|
| Workspace | `My Workspace` (`tea-daehtv2d0e5s738ir540`) |
| Live service | `aion-agent-core-live` (`srv-daei9gpt0dsc73abhs10`) |
| Public URL | `https://aion-agent-core-live.onrender.com` |
| Repository | `https://github.com/wisemankonstantin-droid/aion-agent-core` |
| Branch | `main` |
| Git commit cloned by Render | `078aa55d144adaefa53a93e5411e7a24401d066a` |
| Live deploy | `dep-dafda3ad0e5s73buoq80` |
| Deploy trigger/status | API / live |
| Root Directory | blank, repository root |
| Runtime | Python |
| Python | `3.12.8`, confirmed by build log and environment setting |
| Auto deploy | yes, on commit |
| Start command | `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Database | `aion-agent-db` (`dpg-daei1sv40ujc73faqr70-a`), Render PostgreSQL 18, primary, Frankfurt |

The linked Git commit contains the historical ZIP rather than v0.7.1 direct source. The deploy's exact build command extracted `AION_Agent_Core_v0.6.0.zip`, whose internal application version is 0.6.2, appended an external-registry resolver, and executed four environment-backed source deltas in this order:

`0.6.2 archive -> external registry resolver -> AION_V42_PATCH -> AION_V4_DELTA -> AION_V5_DELTA -> AION_V6_DELTA`

The live build log recorded all four success markers before dependency installation:

- `AION_IDENTITY_A2A_COMPOSITE_V3_READY`
- `AION_GROWTH_INTEGRITY_V4_READY`
- `AION_V5_CORE_070_READY`
- `AION_V6_EXTERNAL_VALIDATION_071_READY`

The exact patch inputs were recovered through the authenticated Render Dashboard, stored only in an untracked recovery workspace, hashed, and applied mechanically to a fresh archive extraction. Their source values are not required at runtime after the resulting direct files are committed. Patch environment values and the legacy ZIP extraction are therefore removed from the future source path.

## Environment inventory

Names observed on the live service, without credential values:

- `AION_APP_VERSION`
- `AION_COMPOSITE_SMOKE`
- `AION_DISABLE_EXTERNAL_DISCOVERY`
- `AION_ENABLE_FIRST_CONTACT`
- `AION_EXTERNAL_DISCOVERY_TIMEOUT`
- `AION_FIRST_CONTACT_PATCH`
- `AION_JOIN_RATE_PER_MINUTE`
- `AION_MCP_RATE_PER_MINUTE`
- `AION_PATCH_B64`
- `AION_PUBLIC_URL`
- `AION_REQUIRE_A2A`
- `AION_RETURN_THRESHOLD_MINUTES`
- `AION_V4_DELTA`
- `AION_V42_PATCH`
- `AION_V5_DELTA`
- `AION_V6_DELTA`
- `DATABASE_URL`
- `PYTHON_VERSION`

`DATABASE_URL` identifies the managed database binding. Its credential value was not read or copied. The AION patch variables are deployment-era source carriers; the reconciled repository contains their output as ordinary files and does not need them to build.

## Source comparison: 0.6.2 to 0.7.1

| Area | Classification | Recovered change | Production significance |
|---|---|---|---|
| Identity resolution | NEW, PRODUCTION-CRITICAL | Groups strong logical identities using stable external ID, durable package, canonical resolver, or canonical endpoint plus declared identity. | Prevents duplicate rows from becoming false growth and blocks duplicate joins. |
| Join/deduplication | MODIFIED, PRODUCTION-CRITICAL | Duplicate guard returns structured evidence and credential-reuse guidance. | Existing rows are preserved; duplicate credential issuance is rejected. |
| First contact | NEW | Adds a useful read-only opportunity response before membership and A2A first-contact behavior. | Shortens discovery-to-value without creating an identity. |
| Canonical needs/offers | NEW | Adds `/needs/canonical` and `/offers/canonical`; superseded rows remain auditable. | Growth views collapse logical duplicates without deleting history. |
| Matching | MODIFIED, PRODUCTION-CRITICAL | Adds normalized token matching, scores, evidence, route state, deterministic match IDs and next actions; validates provider compatibility before interaction. | Response shape changes from a flat provider row to structured `provider`, `offer`, `need` and integrity objects. |
| A2A | MODIFIED, PRODUCTION-CRITICAL | Adds first contact, duplicate-identity response, bounded legacy ingress normalization and version 0.7.1. | Keeps A2A 1.0 primary while accepting a bounded older input shape. |
| MCP | MODIFIED indirectly | Existing tool layer remains separate; match results and server version reflect 0.7.1 behavior. | MCP callers must consume the structured matching response. |
| External discovery | MODIFIED, SECURITY-CRITICAL | Resolves registry details, validates public HTTPS, blocks redirects/private addresses, reads a bounded Agent Card and requires a successful harmless A2A 1.0 handshake for verification. | Registry presence or a URL alone no longer proves a working agent. |
| Funnel metrics | MODIFIED, PRODUCTION-CRITICAL | Separates raw rows from estimated unique external M2/M2b/M3/M4 and excludes AION-operated/test identities. | Product metrics stop treating duplicate rows as growth. |
| Reputation/history | UNCHANGED | Existing interaction and reputation models remain. `/interactions` gains logical-party annotations. | No schema change. |
| Payments | UNCHANGED | Payment intents remain non-settlement records. | No new payment claim or migration. |
| Models/migrations | UNCHANGED, DATABASE-SENSITIVE | Models and Alembic files are byte-equivalent to the 0.6.2 application baseline; head remains `0004_reputation_idempotency`. | v0.7.1 adds no production schema migration. |
| Rate limiting | UNCHANGED | Existing process-local join and MCP limits remain. | Multi-instance/edge limitations remain documented. |
| Deployment | MODIFIED by reconciliation | Direct repository source, hash-locked dependencies, CI, readiness, secret scan and startup tests replace ZIP plus environment source mutation. | Proposed configuration is reviewable and reproducible; it has not been applied to Render. |

Nine application files differ from the 0.6.2 base: `app/main.py`, `app/agent_card.py`, `app/a2a_official.py`, `app/services/external_registry.py`, `app/services/joining.py`, `app/services/lifecycle.py`, `app/services/matching.py`, plus new `app/services/identity_resolution.py` and `app/services/first_contact.py`.

The recovery branch initially copied all nine files from the mechanically reconstructed artifact. Eight remain content-identical. `app/a2a_official.py` has one reviewed reconciliation fix: A2A acquisition attribution is forced to the observed `a2a_direct` transport, restoring the previous invariant that a remote caller cannot spoof its acquisition source.

## Database compatibility and safety gate

The production build used the same four migrations as 0.6.2, with head `0004_reputation_idempotency`. Its start log shows PostgreSQL Alembic initialization completed and Uvicorn started only after `alembic upgrade head` exited successfully. With no newer migration in the deployed artifact, this establishes deployed head `0004_reputation_idempotency`. A direct read-only query through the Render connector was also attempted, but the connector could not establish its required TLS connection; no credential was exposed and no SQL mutation occurred.

Local migration gates cover an empty database, repeated upgrade/check, and forward upgrade from `0003_activation_funnel` to `0004_reputation_idempotency`. There is no v0.7.1 schema delta to apply. Before any future production migration: take a managed backup, inspect the live revision again, test the forward path on a separate PostgreSQL database, define rollback, and never use downgrade or destructive column/table removal as routine recovery.

## Review and deployment boundary

This branch recovers source and tests it; it does not prove that the direct-source configuration has been deployed. Do not merge or deploy automatically. Independent review must compare this document, the nine recovered application files, the A2A attribution fix, migrations, tests and Render safety configuration before any separately authorized production action.
