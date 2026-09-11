# Render production status and historical cutover runbook

## CURRENT PRODUCTION STATUS

The controlled direct-source cutover is complete and production is live.

- Repository state: verify the current `main` ref directly from GitHub; it is
  intentionally not embedded as a self-invalidating current-HEAD claim.
- HQ-verified Package 5C production SHA: `a2a53ff61ede7597651b2f1bac1ca3db809855f9`
- HQ-verified deploy: `dep-dahgei67bikc73fq0g3g`; verify live state again before
  any separately authorized production operation.
- Status: live
- Branch: `main`
- AutoDeploy: OFF (`autoDeployTrigger: off`)
- Root Directory: blank
- Build Command: `python -m pip install --require-hashes -r requirements.txt`
- Start Command: `python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Package 4 is HQ accepted, merged, deployed and live verified. Its historical
  persistence checkpoint was the prepared Neon PostgreSQL Free database at schema
  `0009_continuous_learning_v1`; its manual recovery snapshot was restored and
  integrity-checked during Package 4 closeout.
- Package 5 engineering is merged and live at schema
  `0010_package5_proof_v1`; its commercial proof counters remain legitimately
  zero. Package 5B and Package 5C are merged and live. Package 6A is
  repository-only, adds candidate migration `0011_economic_kernel_v1`,
  and has not been deployed or applied to production.

Production builds direct tracked source from GitHub main. A push or merge is not
permission to deploy, and AutoDeploy must not be enabled without a separately
authorized production change.

## Package 4 controlled-release procedure — historical

The completed Package 4 candidate prepared release safety only. This retained
procedure does not authorize a
deploy, migration, database read/write, backup operation, plan change, secret
change or learning cycle. `PRODUCTION_GATE.md` is the canonical ordered gate.

Before a future production action:

1. Confirm the HQ-approved exact Git SHA has passed AION CI and the PostgreSQL
   18 gate at that same SHA. A branch name is not release identity.
2. Resolve the free database durability/expiry blocker. Record the live plan's
   current and incremental monthly price, capability, acceptable uptime,
   backup/restore semantics and explicit cost approval. Do not assume a plan
   name or price from this repository.
3. Verify and record a real production recovery point, retention/expiry,
   restore procedure/destination, operator access and known RPO/RTO. Source
   history is not a database backup.
4. Read `SELECT version_num FROM alembic_version` through authorized read-only
   access and record the result. Stop if it is not an exact migration start
   state tested by the accepted candidate.
5. Obtain an explicit Human Gate naming the exact SHA, service, database
   revision, recovery point, costs, production operations and rollback owner.
6. Keep AutoDeploy OFF and manually deploy the exact approved `main` SHA to the
   existing service. Record Render's deploy ID and `RENDER_GIT_COMMIT`.
7. Observe the existing start command carefully: it runs
   `python -m alembic upgrade head` before Uvicorn, so deployment can migrate
   the live database before HTTP readiness exists.
8. Require `/health` and `/readiness` to report the exact SHA and schema head
   `0009_continuous_learning_v1`, then manually run the Live Gate with the
   expected exact SHA.
9. Only after that gate passes, inspect
   `python scripts/learning_cycle.py --plan`. A first one-shot production cycle
   requires separate explicit authorization and recorded observation.

AutoDeploy remains OFF through Package 4. Enabling it or adding a scheduler is
a separate later infrastructure decision. The Package 4 source rollback rule
is restore known-good source/config without an automatic Alembic downgrade;
the accepted gate must first prove legacy operations remain compatible with
the additive 0009 schema.

## Historical release and cutover evidence

The remaining Phase A-E material records the completed cutover and its rollback
plan. It is historical evidence and must not be interpreted as an instruction
to repeat the already completed cutover. Terms such as “current” and “existing”
below describe the pre-cutover checkpoint at which the runbook was written.

This runbook prepared the controlled direct-source cutover of the existing
Render service. It did not itself authorize a merge, Render configuration
change, database mutation or deployment.

### Fixed release and production references

- Release branch: `codex/postgres-release-gate-0.7.1`
- Reviewed release SHA: `6d5124fe9fd76578136288c5177fcc1a2f416a6c`
- Existing service: `aion-agent-core-live` (`srv-daei9gpt0dsc73abhs10`)
- Existing workspace: `tea-daehtv2d0e5s738ir540`
- Existing database: `aion-agent-db` (`dpg-daei1sv40ujc73faqr70-a`), PostgreSQL 18, Frankfurt
- Current production branch/SHA: `main` at `078aa55d144adaefa53a93e5411e7a24401d066a`
- Current live deploy: `dep-dafda3ad0e5s73buoq80`
- AutoDeploy: enabled on commit

The current service build extracts the historical ZIP and applies environment
backed source patches. The direct-source release keeps the ZIP as recovery
evidence, but does not execute it or use it as application source.

### Phase A - pre-cutover

1. Record the live service ID, exact active deploy ID, deployed Git SHA, branch,
   Root Directory, complete Build Command, complete Start Command, AutoDeploy
   state, and environment variable names. Save the exact historical build
   command because it is part of the rollback configuration.
2. Confirm the approved release tree is rooted at
   `6d5124fe9fd76578136288c5177fcc1a2f416a6c`. If the pull request adds only
   runbook metadata after that SHA, record the final reviewed PR head as well.
3. Confirm **AION CI** passed for the exact release/PR head.
4. Confirm **PostgreSQL pre-production release gate** passed for the exact
   release/PR head. The verified release gate used PostgreSQL 18.6.
5. If read-only production database inspection is available, confirm the live
   Alembic revision is `0004_reputation_idempotency`. A failed or unavailable
   read-only check does not authorize guessing the revision.
6. Establish the source/configuration rollback point: main SHA
   `078aa55d144adaefa53a93e5411e7a24401d066a` and deploy
   `dep-dafda3ad0e5s73buoq80`.
7. Confirm and record an available production database backup or snapshot and
   its restore procedure. No production backup has been confirmed by this
   repository task, so this remains required before cutover.
8. Freeze unrelated changes to `main` and obtain explicit authorization for
   the coordinated Render change, merge, and deployment window.

### Phase B - Render configuration change

Change the existing service; do not create another service or database.

- Root Directory: blank (repository root)
- Build Command: `python -m pip install --require-hashes -r requirements.txt`
- Start Command: `python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Preserve the current production `DATABASE_URL` and every required runtime
  environment variable.

The new build command must not extract `AION_Agent_Core_v0.6.0.zip`, append
source, or execute `AION_V42_PATCH` or another environment-backed source
mutation. Leave historical patch variables temporarily present if they are
inert under the direct-source commands; capture their names and do not expose
their values. Remove them only in a later cleanup after successful production
verification. If any old variable affects direct-source runtime, resolve that
conflict before cutover rather than deleting rollback evidence during the
deployment window.

### Phase C - source cutover

Because AutoDeploy currently follows `main`, use this order:

1. Disable AutoDeploy and verify that it is disabled before merging anything.
2. Reconfirm the rollback records and backup/restore readiness from Phase A.
3. Merge only the approved release pull request into `main`, then record the
   resulting main SHA. AutoDeploy must remain disabled, so the old ZIP/patch
   build cannot run against the new main tree.
4. Confirm Render is still serving `dep-dafda3ad0e5s73buoq80` and that no
   deployment was triggered by the merge.
5. Apply the Root Directory, Build Command, and Start Command changes above to
   the existing service as one coordinated configuration change. If saving the
   configuration starts a deploy, verify before allowing it to proceed that it
   targets the newly approved main SHA and uses the direct-source commands.
6. Otherwise, manually deploy that exact approved main SHA. Do not deploy a
   moving branch tip or an unreviewed commit.
7. Keep AutoDeploy disabled until Phase D passes and the operator explicitly
   decides to restore commit-based deployment.

This ordering permits a brief repository/configuration staging interval while
AutoDeploy is disabled, but it prevents a production build or deploy combining
the new main source with the historical ZIP/patch command. It also prevents an
unintended deployment before rollback preparation is complete.

### Phase D - post-deploy verification

Immediately verify the new deploy ID and deployed Git SHA, then check:

1. `/health` and `/readiness` return success.
2. The reported application version is `0.7.1`.
3. Readiness reports the database ready and A2A mounted.
4. A non-destructive REST basic flow succeeds.
5. MCP and A2A basic flows succeed.
6. Persistence is visible across separate requests.
7. Matching output keeps unverified endpoints neutral and reports
   `directly_callable: false` with unverified liveness.
8. A controlled duplicate join returns the documented conflict without
   creating a second identity or exposing another credential.
9. Logs show no abnormal migration, database, startup, or 5xx errors.

Use `python scripts/smoke_live.py` or the existing GitHub **Live Gate** against
`https://aion-agent-core-live.onrender.com` where appropriate. Use disposable,
clearly identified test identities and avoid destructive traffic. Record every
result and the deployed SHA.

### Phase E - rollback conditions and procedure

Rollback is required for any of these conditions:

- build or startup failure;
- readiness or database failure;
- REST, MCP, or A2A regression;
- persistence failure;
- unexpected Alembic revision or migration behavior;
- abnormal 5xx behavior;
- serious join identity/deduplication regression;
- serious matching integrity regression.

Keep AutoDeploy disabled. Restore the captured previous source/configuration
pair and redeploy the known-good production revision represented by main SHA
`078aa55d144adaefa53a93e5411e7a24401d066a` and deploy
`dep-dafda3ad0e5s73buoq80`. Use a reviewed revert/rollback operation supported
by the repository and Render; do not force-push shared history. Restore the
exact recorded historical Build and Start commands with the source revision
that expects them. Verify health, readiness, protocols, persistence, and logs
again. Do not downgrade the production database or delete production data.

The backup tag `backup/pre-normalization-20260907` and retained ZIP are source
recovery evidence. They are not a production database backup.
