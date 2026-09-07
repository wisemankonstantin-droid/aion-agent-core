# Coding-agent rules

1. Read PROJECT_STATE.md first, then AION_DIRECTIVE.md.
2. Inspect the actual branch, git status, code, tests and deployment before changing anything. Saved documents are context, not proof.
3. Continue the existing architecture; do not restart project design.
4. Preserve working production and data. Verify deployment compatibility before changing its source, commands or database.
5. GitHub is the source of truth. Edit tracked source directly; never develop by replacing ZIP archives.
6. A2A is the primary agent-to-agent layer. MCP is a separate integration/tool layer.
7. Do not add secondary features before the core product loop is proven.
8. Run relevant tests after substantial changes. A feature is not complete without a test. CI must require the A2A runtime, not silently skip it.
9. Update PROJECT_STATE.md after material changes, recording actual test results and unresolved failures.
10. Synthetic/test agents and AION-operated identities are not real external growth.
11. Never commit credentials, local databases, agent keys or populated environment files. Run the repository secret scan before committing.
12. Follow BLOCKER -> CRITICAL -> HIGH -> MEDIUM -> LOW. Continue useful authorized work autonomously; follow the execution rules in AION_DIRECTIVE.md.

Validation from repository root (Python 3.12):
```sh
python -m pip install -r requirements.txt
python -m pip check
python -m pytest -q
python scripts/readiness.py
python scripts/check_secrets.py
```
