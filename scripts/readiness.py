from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parents[1]
main = (root / "app/main.py").read_text(encoding="utf-8")
requirements = (root / "requirements.txt").read_text(encoding="utf-8")
render = (root / "render.yaml").read_text(encoding="utf-8")
models = (root / "app/models.py").read_text(encoding="utf-8")

checks = {
    "version_0_7_1": 'APP_VERSION = "0.7.1"' in main,
    "render_blueprint": (root / "render.yaml").exists(),
    "migration_0004": (root / "alembic/versions/0004_reputation_idempotency.py").exists(),
    "migration_0005_live_utility": (root / "alembic/versions/0005_live_utility_persistence.py").exists(),
    "a2a_sdk_pinned": "a2a-sdk==1.1.2" in requirements and "a2a-sdk[fastapi]==1.1.2" in (root / "requirements.in").read_text(encoding="utf-8"),
    "a2a_required_in_render": "AION_REQUIRE_A2A" in render,
    "a2a_v1_route": '"/a2a/v1"' in main or "/a2a/v1" in (root / "app/a2a_official.py").read_text(encoding="utf-8"),
    "mcp_2026_07_28": 'MCP_VERSION = "2026-07-28"' in main,
    "mcp_meta_validation": "io.modelcontextprotocol/clientCapabilities" in main,
    "activation_funnel": (root / "app/services/lifecycle.py").exists() and '"M4"' in (root / "app/services/lifecycle.py").read_text(encoding="utf-8"),
    "db_reputation_idempotency": "uq_reputation_events_agent_reason" in models,
    "external_cold_start": (root / "app/services/external_registry.py").exists(),
    "external_validation": "AION_EXTERNAL_VALIDATION_V1" in (root / "app/services/external_registry.py").read_text(encoding="utf-8"),
    "identity_resolution": (root / "app/services/identity_resolution.py").exists() and '@app.get("/identity-resolution")' in main,
    "first_contact": (root / "app/services/first_contact.py").exists() and '@app.get("/first-contact")' in main,
    "matching_v1": '"version":"matching/1.0"' in main,
    "registry_generator": (root / "scripts/render_server_json.py").exists(),
    "live_smoke": (root / "scripts/smoke_live.py").exists(),
    "work_handoff": (root / "WORK_MINIMUM_HANDOFF.md").exists(),
    "agent_skill": (root / "SKILL.md").exists() and '@app.get("/skill.md"' in main,
    "github_ci": (root / ".github/workflows/ci.yml").exists(),
    "github_live_gate": (root / ".github/workflows/live-gate.yml").exists(),
    "github_mcp_oidc_publish": (root / ".github/workflows/publish-mcp.yml").exists(),
    "colony_bootstrap": (root / "scripts/colony_bootstrap.py").exists(),
    "known_limitations": (root / "KNOWN_LIMITATIONS.md").exists(),
    "security_notes": (root / "SECURITY.md").exists(),
    "env_example": (root / ".env.example").exists(),
    "version_file": (root / "VERSION").read_text(encoding="utf-8").strip() == "0.7.1",
    "no_bundled_runtime_db": not (root / "aion.db").exists() and not (root / ".aion-test.db").exists(),
}

external = [
    "Obtain independent review before any merge or deployment of the reconciled v0.7.1 source.",
    "Re-run the external A2A smoke after deployment and verify join_aion through the official SDK route.",
    "Obtain the first genuinely external M2/M3 journey; AION-operated or synthetic identities must not be counted as external adoption.",
    "Prove external activation and return before expanding distribution.",
    "Configure and verify a real settlement rail before claiming completed machine payments.",
]


result = {
    "local_readiness": checks,
    "all_local_checks": all(checks.values()),
    "external_actions_remaining": external,
}
print(json.dumps(result, indent=2))
sys.exit(0 if all(checks.values()) else 1)
