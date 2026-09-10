# Package 4 production closeout

Date: 2026-09-10

## Status

Package 4 is **DONE**.

HQ accepted the release candidate, merged it to `main`, deployed the exact
accepted SHA to production, switched production persistence to the prepared
Neon PostgreSQL Free database, and independently live-verified the release.

Accepted/deployed SHA:

`e52c5db99b30feb18ca06ace567b4668c8019bde`

Render service:

`aion-agent-core-live` (`srv-daei9gpt0dsc73abhs10`)

Production deploy:

`dep-dah96uu1egvs73d4gvh0`

Production URL:

`https://aion-agent-core-live.onrender.com`

AutoDeploy:

`OFF`

Infrastructure spend:

`$0`

## Pre-production acceptance evidence

The accepted candidate passed:

- AION CI run `34463123839` on exact SHA
  `e52c5db99b30feb18ca06ace567b4668c8019bde`;
- PostgreSQL 18 gate run `34463123885` on the same exact SHA;
- targeted tests: 153 passed, 10 skipped;
- full pytest: 312 passed, 10 skipped;
- source integrity: 12 passed;
- migration tests: 5 passed;
- secret scan: 121 files, 0 findings;
- compileall, pip check, workflow parsing and diff checks;
- exact Alembic head `0009_continuous_learning_v1`;
- seeded PostgreSQL `0004 -> 0009` preservation proof;
- fresh-to-head and `0008 -> 0009` PostgreSQL paths;
- repeated upgrade no-op checks and Alembic check;
- additive migration red-team and old-source compatibility review.

The candidate was fast-forwarded to `main`; resulting-main AION CI run
`34463854424` passed on the identical SHA.

## Production database cutover

The expiring Render Free PostgreSQL dependency was replaced with a Neon
PostgreSQL Free production database before the Package 4 deployment.

The legacy Render database was temporarily exposed only for the bounded copy,
then public access was closed again. No Render database mutation or migration
was performed during the copy.

The copied pre-cutover production dataset was verified as:

- 2 agent rows;
- 3 capability rows;
- 1 need row;
- 2 offer rows;
- 0 interactions;
- 0 reputation events;
- 0 payment intents;
- 657 `machine_entries` with continuous IDs 1 through 657;
- Alembic head `0009_continuous_learning_v1` on the prepared Neon target.

The production `DATABASE_URL` was then changed only to the prepared pooled Neon
connection string. No password or connection string is recorded in repository
documentation.

## Recovery evidence

A complete post-copy Neon snapshot was created:

`snap-raspy-brook-b2kto175`

It was restored to a separate rehearsal branch without switching the production
default branch. The rehearsal verified:

- Alembic `0009_continuous_learning_v1`;
- all 657 pre-cutover `machine_entries`;
- continuous IDs with no gaps;
- the expected business-row counts.

This proves a real recovery path for the captured pre-cutover state on the
current free infrastructure. It does not imply HA, PITR or paid durability
features that were not verified.

## Deployment evidence

Render manual deploy `dep-dah96uu1egvs73d4gvh0` checked out exact SHA
`e52c5db99b30feb18ca06ace567b4668c8019bde`.

Build succeeded. Startup executed:

`python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Alembic connected through `PostgresqlImpl` with transactional DDL and required no
new migration because the Neon database was already current. Uvicorn startup
completed and Render marked the service live.

## Post-deploy live verification

`/health` returned HTTP 200 with:

- status `ok`;
- version `0.7.1`;
- A2A runtime mounted;
- exact release SHA
  `e52c5db99b30feb18ca06ace567b4668c8019bde`;
- release source `render_git_commit`.

`/readiness` returned HTTP 200 with status `ready` and all checks true:

- database;
- A2A runtime;
- schema current;
- Package 3B configuration;
- release identity.

Both expected and observed database schema revision were exactly:

`0009_continuous_learning_v1`

The safe live verification also confirmed public REST, MCP and A2A discovery
and utility surfaces, required MCP tools, first-contact and onboarding behavior,
and protected Package 3 / Package 3B boundaries.

Unauthenticated action and evidence submissions returned 401 before protected
execution/persistence. Agent row count stayed at 2 before and after the safe
smoke.

A direct Neon post-smoke check found:

- interactions: 0;
- payment intents: 0;
- action runs: 0;
- action attempts: 0;
- action outcomes: 0;
- action verifications: 0;
- agent evidence claims: 0;
- learning runs: 0;
- learning source watch states: 0;
- learning opportunity candidates: 0.

`machine_entries` increased from the 657 pre-cutover baseline to 664 because the
live verification itself generates bounded machine-entry telemetry. Those rows
are observability traffic, not membership, independent adoption, a verified
external VUO, learning execution or payment.

## Boundaries after Package 4

Package 4 does **not** prove:

- independent external production adoption;
- a real independent external VUO;
- voluntary return by an independent external agent;
- payment settlement;
- revenue;
- repeat payer behavior;
- commercial unit economics.

No automatic scheduler, payment activation or paid external provider was
introduced. AutoDeploy remains OFF.

The next package is Package 5: **First Independent External Agent Proof**.
