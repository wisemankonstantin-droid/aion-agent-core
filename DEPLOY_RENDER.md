# Render deployment gate

Verified 2026-09-07: https://aion-agent-core-live.onrender.com/health reports
v0.7.1 with A2A mounted. The exact production patch chain has been recovered,
applied to the 0.6.2 base and moved into direct files on
`codex/recover-production-0.7.1`. Do not merge or deploy this review branch
automatically.

The live Dashboard build command was verified: it extracts the historical ZIP,
appends a registry patch and executes four environment-backed source deltas.
That mechanism produced the recovered files but is no longer the target build
path. The original ZIP is retained unchanged as recovery evidence, not as the
development source of truth. See `docs/PRODUCTION_RECOVERY_0.7.1.md`.

## Reviewed direct-source target

- Repository root (Render Root Directory blank).
- Build: `python -m pip install --require-hashes -r requirements.txt`.
- Start: `python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Health: `/health`; Python 3.12 (blueprint specifies 3.12.8).
- Preserve existing managed database and DATABASE_URL.
- AION_REQUIRE_A2A=1; verified AION_PUBLIC_URL or RENDER_EXTERNAL_URL.
- Optional numeric variables must be valid numbers or absent, never empty.

render.yaml is a root-source blueprint, not a request to alter the existing live
service. Do not apply it to create replacement production resources. The live
service and database identities are recorded in the production recovery audit.

## Safe cutover

1. Independently review the recovered source, provenance and structured diff.
2. Reconfirm the production revision and snapshot the database before any
   future migration work. This recovery adds no migration after head 0004.
3. Test the reviewed source in CI and a separate PostgreSQL database, including upgrade
   compatibility, real startup and A2A/MCP/REST regressions.
4. Update the existing service to root-source commands and deploy a reviewed
   commit only after these gates. Check health, protocols and persistence.
5. Remove ZIP only once the direct-source deployment is verified. Git history
   and backup/pre-normalization-20260907 retain the original.

Local tests cover fresh SQLite migrations, forward upgrade from 0003 to 0004,
repeated upgrade/check and real Uvicorn startup. A separate PostgreSQL rehearsal
is still required before a future schema change. The live smoke now requires
v0.7.1 and must only be run as part of a separately authorized deployment review.

To inspect the original source use the backup tag; a separate recovery branch
can be created with `git switch -c recovery/from-backup backup/pre-normalization-20260907`.
This git backup is not a production database backup and is not a reason to roll
production back.
