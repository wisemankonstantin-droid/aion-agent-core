# AION v0.6.2 launch without ChatGPT Work

> Historical v0.6.2 operational handoff. It does not describe current source,
> deployment or authorization. See `PROJECT_STATE.md`, `DEPLOY_RENDER.md` and
> `AION_MASTER_DELIVERY_ROADMAP.md`.

The code, tests, release archive and deployment handoff can be completed without ChatGPT Work. Do not spend Work on redesign, documentation, code editing or local testing.

## Current external state
- GitHub repository exists: `wisemankonstantin-droid/aion-agent-core`.
- The live Render service exists and already builds from `AION_Agent_Core_v0.6.0.zip` in that repository.
- Durable Render PostgreSQL is attached and persistence was verified.
- The connected GitHub integration currently returns HTTP 403 for repository-content writes, so it cannot replace the binary archive from this chat.
- Render is at the Hobby service-count limit because many one-time validation static sites accumulated; this does not stop the existing live web service.

## Minimal deployment action
Use the **drop-in archive** produced with this release:

`AION_Agent_Core_v0.6.0.zip`

Despite the compatibility filename/folder, its internal application version is `0.6.2`. It intentionally preserves the old archive name and top-level folder because the existing Render build command already expects them.

Replace the existing GitHub file with this drop-in archive in one commit. Auto-deploy on the live Render service should then rebuild without changing the service command.

## After deployment
1. Confirm `/health` and `/a2a/status`.
2. Run `scripts/smoke_live.py` against the public URL.
3. Verify one A2A `message/send` onboarding request.
4. Verify the new `join_aion` route only with a clearly marked controlled test identity if necessary; delete/do not count test identities as external adoption.
5. Resume targeted federation and wait for a genuinely external agent to choose `join_aion`.
6. Measure M1 -> M2 -> M3 -> M4 honestly.

## Render cleanup
Delete obsolete one-time static validation services when convenient. Keep:
- `aion-agent-core-live`
- `aion-agent-db`
- only the small number of reusable diagnostics actually needed

This cleanup is operational hygiene, not a prerequisite for replacing the archive in the existing live service.
