# Coding-agent rules

## Required reading order

1. `PROJECT_STATE.md`.
2. `AION_DIRECTIVE.md`.
3. `AGENTS.md`.
4. `AION_LIVE_UTILITY_ENGINE.md` when Live Utility or product architecture work
   is relevant.
5. `GROWTH_AND_REVENUE.md` when acquisition, retention, monetization, metrics or
   product economics are relevant.
6. `DEPLOY_RENDER.md` when deployment or release work is relevant.
7. `MACHINE_PROTOCOLS.md` when protocol behavior is relevant.

## Execution rules

1. Inspect the actual branch, git status, code, tests and deployment before changing anything. Saved documents are context, not proof.
2. Continue the existing architecture; do not restart project design.
3. Preserve working production and data. Verify deployment compatibility before changing its source, commands or database.
4. GitHub is the source of truth. Edit tracked source directly; never develop by replacing ZIP archives.
5. A2A is the primary agent-to-agent layer. MCP is a separate integration/tool layer.
6. Do not add secondary features before the core product loop is proven.
7. Run relevant tests after substantial changes. A feature is not complete without a test. CI must require the A2A runtime, not silently skip it.
8. Update PROJECT_STATE.md after material changes, recording actual test results and unresolved failures.
9. Synthetic/test agents and AION-operated identities are not real external growth.
10. Never commit credentials, local databases, agent keys or populated environment files. Run the repository secret scan before committing.
11. Follow BLOCKER -> CRITICAL -> HIGH -> MEDIUM -> LOW. Continue useful authorized work autonomously; follow the execution rules in AION_DIRECTIVE.md.

Validation from repository root (Python 3.12):
```sh
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -q
python scripts/readiness.py
python scripts/check_secrets.py
```
