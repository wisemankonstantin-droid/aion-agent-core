from pathlib import Path
import json
import re
import sys

root = Path(__file__).resolve().parents[1]
main = (root / "app/main.py").read_text(encoding="utf-8")
requirements = (root / "requirements.txt").read_text(encoding="utf-8")
render = (root / "render.yaml").read_text(encoding="utf-8")
models = (root / "app/models.py").read_text(encoding="utf-8")
external_registry = (root / "app/services/external_registry.py").read_text(encoding="utf-8")
action_engine = (root / "app/services/action_engine.py").read_text(encoding="utf-8")
release_identity = (root / "app/release_identity.py").read_text(encoding="utf-8")
live_gate = (root / ".github/workflows/live-gate.yml").read_text(encoding="utf-8")
postgres_gate = (root / ".github/workflows/postgres-release-gate.yml").read_text(encoding="utf-8")
learning_cli = (root / "scripts/learning_cycle.py").read_text(encoding="utf-8")
machine_journey = (root / "app/machine_journey.py").read_text(encoding="utf-8")
economic_kernel = (root / "app/services/economic_kernel.py").read_text(encoding="utf-8")
ambassador = (root / "app/services/ambassador.py").read_text(encoding="utf-8")
conversation_intelligence = (root / "app/services/conversation_intelligence.py").read_text(encoding="utf-8")

checks = {
    "version_0_8_0": 'APP_VERSION = "0.8.0"' in main,
    "render_blueprint": (root / "render.yaml").exists(),
    "migration_0004": (root / "alembic/versions/0004_reputation_idempotency.py").exists(),
    "migration_0005_live_utility": (root / "alembic/versions/0005_live_utility_persistence.py").exists(),
    "migration_0006_live_utility_data": (root / "alembic/versions/0006_live_utility_data.py").exists(),
    "migration_0007_agent_utility_checkpoints": (root / "alembic/versions/0007_agent_utility_checkpoints.py").exists(),
    "migration_0008_action_outcome_evidence": (root / "alembic/versions/0008_action_outcome_evidence.py").exists(),
    "migration_0009_continuous_learning_v1": (root / "alembic/versions/0009_continuous_learning_v1.py").exists(),
    "migration_0010_package5_proof_v1": (root / "alembic/versions/0010_package5_proof_v1.py").exists(),
    "migration_0011_economic_kernel_v1": (root / "alembic/versions/0011_economic_kernel_v1.py").exists(),
    "migration_0012_ambassador_pilot_v1": (root / "alembic/versions/0012_ambassador_pilot_v1.py").exists(),
    "migration_0013_ambassador_control_v1": (root / "alembic/versions/0013_ambassador_control_v1.py").exists(),
    "migration_0014_conversation_intel_v1": (root / "alembic/versions/0014_conversation_intel_v1.py").exists(),
    "migration_0015_x402_exact_upfront_v1": (root / "alembic/versions/0015_x402_exact_upfront_v1.py").exists(),
    "migration_0016_official_data_execution_v1": (root / "alembic/versions/0016_official_data_execution_v1.py").exists(),
    "migration_0017_first_sat_accounting_v1": (root / "alembic/versions/0017_first_sat_accounting_v1.py").exists(),
    "package_3b_learning_engine": (root / "app/services/learning_engine.py").exists()
        and (root / "scripts/learning_cycle.py").exists(),
    "repository_release_identity": (
        'EXPECTED_SCHEMA_REVISION = "0017_first_sat_accounting_v1"' in release_identity
        and "RENDER_GIT_COMMIT" in release_identity
        and "AION_RELEASE_SHA" in release_identity
    ),
    "repository_schema_readiness": (
        '"schema_current"' in main and "SELECT version_num FROM alembic_version" in main
    ),
    "package_4_exact_sha_live_gate": (
        "expected_release_sha" in live_gate and "AION_EXPECTED_RELEASE_SHA" in live_gate
    ),
    "package_4_legacy_postgres_gate": (
        "upgrade 0004_reputation_idempotency" in postgres_gate
        and "postgres_0004_release_proof.py verify" in postgres_gate
    ),
    "package_4_learning_preflight": "--plan" in learning_cli,
    "package_5_proof_engine": (
        (root / "app/services/package5_proof.py").exists()
        and '@app.get("/proof/package-5")' in main
        and '@app.post("/proof/package-5/vuos")' in main
    ),
    "package_6a_economic_kernel": (
        '@app.post("/economic/preflight")' in main
        and '"name": "economic_preflight"' in main
        and 'REAL_MONEY_ENABLE_ENV = "AION_REAL_MONEY_EXECUTION_ENABLED"' in economic_kernel
        and "REAL_MONEY_EXECUTION_ENABLED = configured_real_money_execution_enabled()" in economic_kernel
        and "MINIMUM_MARGIN_BPS = 4_000" in economic_kernel
        and "parent_economic_operation_id" in models
    ),
    "package_5d_ambassador_pilot": (
        (root / "scripts/ambassador_pilot.py").exists()
        and "MAX_CAMPAIGN_TARGETS = 30" in ambassador
        and 'os.getenv("AION_AMBASSADOR_OUTBOUND_ENABLED") != "1"' in ambassador
        and 'os.getenv("AION_AMBASSADOR_OPERATOR") != "1"' in ambassador
        and "discover_external_agents_with_status" in ambassador
        and "aion_ambassador_outbound" in ambassador
    ),
    "package_5e_ambassador_operator_control": (
        (root / "app/services/ambassador_operator.py").exists()
        and 'AION_AMBASSADOR_CONTROL_TOKEN' in (root / "app/services/ambassador_operator.py").read_text(encoding="utf-8")
        and '@app.post("/ops/ambassador/targets/{target_id}/contact", include_in_schema=False)' in main
        and "prepare_and_send_operator_contact" in ambassador
    ),
    "package_5f_conversation_intelligence": (
        (root / "app/conversation_models.py").exists()
        and (root / "app/services/conversation_intelligence.py").exists()
        and "capture_ambassador_response" in ambassador
        and "campaign_intelligence_report" in ambassador
        and '"message_text_persisted": False' in conversation_intelligence
        and '"raw_response_persisted": False' in conversation_intelligence
        and '"paid_inference_used": False' in conversation_intelligence
    ),
    "package_5b_conversion_journey": (
        "verified_outcome_journey" in main
        and "verify_external_callability" in machine_journey
        and "world_bank.population.latest" in machine_journey
        and '"operator_participation_review_required": False' in machine_journey
        and '"human_usefulness_confirmation_required": False' in machine_journey
        and '"blocks_launch": False' in machine_journey
        and '"blocks_payment": False' in machine_journey
    ),
    "live_utility_data_engine": (root / "app/services/live_utility_engine.py").exists() and (root / "app/services/live_utility_sources.py").exists(),
    "agent_utility_compatibility": (root / "app/services/agent_utility.py").exists() and '@app.post("/utility/query")' in main,
    "mcp_live_utility": '"name": "get_live_utility"' in main,
    "a2a_live_utility": 'id="aion_live_utility"' in (root / "app/a2a_official.py").read_text(encoding="utf-8"),
    "a2a_sdk_pinned": "a2a-sdk==1.1.2" in requirements and "a2a-sdk[fastapi]==1.1.2" in (root / "requirements.in").read_text(encoding="utf-8"),
    "a2a_required_in_render": "AION_REQUIRE_A2A" in render,
    "a2a_v1_route": '"/a2a/v1"' in main or "/a2a/v1" in (root / "app/a2a_official.py").read_text(encoding="utf-8"),
    "mcp_2026_07_28": 'MCP_VERSION = "2026-07-28"' in main,
    "mcp_meta_validation": "io.modelcontextprotocol/clientCapabilities" in main,
    "activation_funnel": (root / "app/services/lifecycle.py").exists() and '"M4"' in (root / "app/services/lifecycle.py").read_text(encoding="utf-8"),
    "db_reputation_idempotency": "uq_reputation_events_agent_reason" in models,
    "external_cold_start": (root / "app/services/external_registry.py").exists(),
    "external_validation": (
        "from app.services import safe_http as _safe_http" in external_registry
        and '"interaction_contacted": False' in external_registry
        and '"verified_outcome": False' in external_registry
    ),
    "package_3_safe_action": (
        '@app.post("/actions/verify-callability")' in main
        and '"name": "verify_external_callability"' in main
        and "ACTION_MAX_POST_ATTEMPTS = 1" in action_engine
        and "a2a_nonce_roundtrip_v1" in action_engine
    ),
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
    "version_file": (root / "VERSION").read_text(encoding="utf-8").strip() == "0.8.0",
    "no_bundled_runtime_db": not (root / "aion.db").exists() and not (root / ".aion-test.db").exists(),
}

external = [
    "Production deploy/migration remains an owner control-plane gate; it is not part of the normal agent customer loop.",
    "Publish and verify production machine-discovery surfaces after deployment so agents can discover and execute AION autonomously.",
    "Configure, owner-enable and verify a real settlement rail before any priced capability can claim completed machine payments or revenue.",
    "After a real-money rail is enabled, measure real Settled Agent Transactions, repeat paid use, revenue, variable cost and contribution margin from durable production records.",
]


result = {
    "local_readiness": checks,
    "all_local_checks": all(checks.values()),
    "external_actions_remaining": external,
}
print(json.dumps(result, indent=2))
sys.exit(0 if all(checks.values()) else 1)
