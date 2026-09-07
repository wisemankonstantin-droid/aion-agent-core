# Render deployment gate

Verified 2026-09-07: https://aion-agent-core-live.onrender.com/health reports
v0.7.1 with A2A mounted. Recovered source is v0.6.2. Do not merge this branch
into an auto-deployed branch or deploy it over the newer production service
until its source has been recovered and compared.

Historical instructions inside the ZIP describe a build extracting
AION_Agent_Core_v0.6.0.zip into AION_Agent_Core_v0.6.0/. This is historical
evidence, not a verified current Dashboard setting. The original ZIP is
retained unchanged for compatibility, not as development source of truth.

## Target after source reconciliation

- Repository root (Render Root Directory blank).
- Build: `python -m pip install --require-hashes -r requirements.txt`.
- Start: `python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Health: `/health`; Python 3.12 (blueprint specifies 3.12.8).
- Preserve existing managed database and DATABASE_URL.
- AION_REQUIRE_A2A=1; verified AION_PUBLIC_URL or RENDER_EXTERNAL_URL.
- Optional numeric variables must be valid numbers or absent, never empty.

render.yaml is a root-source blueprint, not proof of live settings. Its resource
names and free database plan are historical. Do not apply it to create replacement
production resources; confirm current plans and backups before provisioning.

## Safe cutover

1. In the correct Render workspace inspect live repository, branch, deployed
   commit, rootDir, commands and environment names (never expose values).
2. Recover v0.7.1 source and migrations. Preserve newer behavior and snapshot
   the production database before any migration work.
3. Test reconciled source in CI and a separate database, including upgrade
   compatibility, real startup and A2A/MCP/REST regressions.
4. Update the existing service to root-source commands and deploy a reviewed
   commit only after these gates. Check health, protocols and persistence.
5. Remove ZIP only once the direct-source deployment is verified. Git history
   and backup/pre-normalization-20260907 retain the original.

Local tests cover fresh SQLite migrations, repeated upgrade and real Uvicorn;
they do not prove compatibility with an unknown newer production database.
The v0.6.2 live smoke intentionally rejects v0.7.1. Update version expectations
only alongside recovery of that newer code.

To inspect the original source use the backup tag; a separate recovery branch
can be created with `git switch -c recovery/from-backup backup/pre-normalization-20260907`.
This git backup is not a production database backup and is not a reason to
roll production back to v0.6.2.
