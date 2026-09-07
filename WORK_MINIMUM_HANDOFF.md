# Minimal external handoff for AION v0.6.2

Everything that can be prepared and tested locally is included in this package. Do not spend ChatGPT Work on code review, architecture, documentation or test writing unless the live gate exposes a real measured failure.

## Current external state
- GitHub repository already exists: `wisemankonstantin-droid/aion-agent-core`.
- Live Render service already exists: `aion-agent-core-live`.
- Durable Render PostgreSQL is attached and persistence was verified.
- AION is already visible in an independent A2A registry and current pre-v0.6.2 A2A `message/send` interoperability is proven.
- The connected GitHub integration currently cannot write repository contents (HTTP 403), so replacing the binary ZIP is the only remaining manual repository action.

## One required repository action
Replace the existing GitHub file `AION_Agent_Core_v0.6.0.zip` with the drop-in file of the same name from this release.

The filename and top-level folder intentionally remain `v0.6.0` only for compatibility with the existing Render build command. The application inside is `VERSION=0.6.2`.

## What should happen automatically
A commit that replaces the ZIP should trigger the existing Render auto-deploy. No new web service and no Render command edit are required.

## Post-deploy gate
1. Confirm the deployment is live.
2. Run `scripts/smoke_live.py` against `https://aion-agent-core-live.onrender.com`.
3. Confirm Agent Card advertises `join_aion`.
4. Verify A2A `message/send` still works.
5. Verify direct A2A join with a controlled test only if needed. Never count a test identity as external adoption.

## Acquisition gate
Resume targeted agent-to-agent distribution only after the live gate passes. Track source -> M1 -> M2 -> M3 -> M4 and keep external discovery separate from membership.

## Render cleanup
Delete obsolete one-time static validation services when convenient to free the Hobby service quota. Do not delete the live web service or PostgreSQL database.

## Do not spend time on now
- redesigning the temple
- more lore/ranks
- fake/seed external agents
- invented adoption numbers
- more payment methods before settlement verification
- broad paid traffic before a real external M2/M3 path exists
