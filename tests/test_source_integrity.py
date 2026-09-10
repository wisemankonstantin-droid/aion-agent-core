import ast
import json
from pathlib import Path
import subprocess
import sys
import yaml

import pytest

from app.db import SessionLocal
from app import a2a_official, main
from app.services import action_engine, external_registry, learning_engine, lifecycle, opportunities, package5_proof
from scripts import acquisition_scan


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clear_external_discovery_state(monkeypatch):
    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    external_registry._AION_VALIDATION_CACHE.clear()
    external_registry._AION_DISCOVERY_RATE_TIMES.clear()


def _top_level_definitions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_shadowed_public_definitions_do_not_return():
    external_defs = _top_level_definitions(ROOT / "app" / "services" / "external_registry.py")
    lifecycle_defs = _top_level_definitions(ROOT / "app" / "services" / "lifecycle.py")
    assert external_defs.count("discover_external_agents") == 1
    assert external_defs.count("_discover_external_agents_resolved") == 1
    assert lifecycle_defs.count("funnel_snapshot") == 1


def test_rest_mcp_a2a_and_opportunities_share_external_discovery_service():
    assert main.discover_external_agents is external_registry.discover_external_agents
    assert a2a_official.discover_external_agents is external_registry.discover_external_agents
    assert opportunities.discover_external_agents is external_registry.discover_external_agents
    assert (
        action_engine.discover_external_agents_with_status
        is external_registry.discover_external_agents_with_status
    )


def test_rest_and_mcp_share_package3b_evidence_service():
    assert main.submit_agent_evidence is learning_engine.submit_agent_evidence
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert source.count("submit_agent_evidence(") == 2


def test_acquisition_scan_reuses_bounded_external_discovery(monkeypatch):
    calls = []

    def discover(query, limit):
        calls.append((query, limit))
        return [{"identifier": query, "evidence_state": "registry_hit_unresolved"}]

    monkeypatch.setattr(acquisition_scan, "discover_external_agents", discover)
    assert acquisition_scan.scan(["research", "planning"]) == [
        {"identifier": "research", "evidence_state": "registry_hit_unresolved"},
        {"identifier": "planning", "evidence_state": "registry_hit_unresolved"},
    ]
    assert calls == [("research", 5), ("planning", 5)]


def test_readiness_recognizes_non_invoking_external_validation():
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "readiness.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["local_readiness"]["external_validation"] is True


def test_public_discovery_resolves_then_validates(monkeypatch):
    resolved = [
        {"identifier": "one", "url": "https://one.example/card"},
        {"identifier": "two", "url": "https://two.example/card"},
    ]
    calls = []

    def resolve(query, limit, budget):
        calls.append(("resolve", query, limit))
        return resolved

    def validate(row, budget):
        calls.append(("validate", row["identifier"]))
        return {**row, "verified_external_agent": False}

    monkeypatch.setattr(external_registry, "_AION_RESOLVED_DISCOVER", resolve)
    monkeypatch.setattr(external_registry, "_validate_external", validate)

    results = external_registry.discover_external_agents("research", 20)
    assert calls == [("resolve", "research", 5), ("validate", "one"), ("validate", "two")]
    assert [row["verified_external_agent"] for row in results] == [False, False]


def test_resolved_discovery_preserves_detail_and_package_resolver_flow(monkeypatch):
    calls = []

    def fake_read(method, url, payload=None, headers=None, timeout=4, budget=None):
        calls.append((method, url))
        budget.consume(1)
        if url.startswith(external_registry.A2A_REGISTRY_SEARCH + "?"):
            assert url.endswith("q=research")
            return 200, [{"identifier": "agent-one", "name": "Search Name"}], None
        if "/resolve/" in url:
            return 200, {
                "result": {
                    "manifest_url": "https://agent.example/card",
                    "name": "Resolved Name",
                }
            }, None
        return 200, {
            "agent": {
                "package_name": "io.github.owner/agent",
                "description": "Detail",
            }
        }, None

    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    monkeypatch.setattr(external_registry, "_read_json", fake_read)
    result = external_registry._discover_external_agents_resolved("research", 5)
    assert all(method == "GET" for method, _ in calls)
    assert result == [
        {
            "source": "global_a2a_registry",
            "identifier": "agent-one",
            "package_name": "io.github.owner/agent",
            "name": "Resolved Name",
            "description": "Detail",
            "url": "https://agent.example/card",
            "registry_verified_claim": None,
            "raw_category": None,
            "resolution_status": "manifest_url_declared",
            "resolution_reason": None,
            "evidence_state": "registry_manifest_url_declared",
            "followable": True,
        }
    ]


def test_funnel_snapshot_remains_identity_aware():
    with SessionLocal() as db:
        result = lifecycle.funnel_snapshot(db)

    assert {
        "M1_machine_entry_requests",
        "raw",
        "estimated_unique_external",
        "identity_resolution",
        "conversion",
        "definitions",
        "integrity_note",
    } <= result.keys()
    assert "M2_identity_rows" in result["raw"]
    assert "estimated_unique_external_agents" in result["identity_resolution"]
    assert "M1_to_unique_M2" in result["conversion"]
    assert "M2_joined_agents" not in result
    assert "M3_activated_agents" not in result


def test_package4_live_gate_is_manual_exact_sha_only():
    workflow = yaml.load(
        (ROOT / ".github" / "workflows" / "live-gate.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"public_url", "expected_release_sha"}
    assert inputs["expected_release_sha"]["required"] == "true"
    source = (ROOT / "scripts" / "smoke_live.py").read_text(encoding="utf-8")
    assert "AION_EXPECTED_RELEASE_SHA" in source
    assert '"/agents"' not in source
    assert "Authorization" not in source
    assert "verify_external_callability(" not in source
    assert "submit_agent_evidence(" not in source


def test_package4_schema_and_postgres_legacy_jump_are_release_gates():
    identity = (ROOT / "app" / "release_identity.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "postgres-release-gate.yml").read_text(encoding="utf-8")
    proof = (ROOT / "scripts" / "postgres_0004_release_proof.py").read_text(encoding="utf-8")
    assert 'EXPECTED_SCHEMA_REVISION = "0010_package5_proof_v1"' in identity
    assert "upgrade 0004_reputation_idempotency" in workflow
    assert "postgres_0004_release_proof.py seed" in workflow
    assert "postgres_0004_release_proof.py verify" in workflow
    assert "codex/package-4-controlled-production-release" in workflow
    assert "sys.path.insert(0, str(ROOT))" in proof


def test_package4_has_no_automatic_learning_scheduler_or_autodeploy_workflow():
    workflow_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / ".github" / "workflows").glob("*.yml")
    )
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "learning_cycle.py" not in workflow_text
    assert "cron:" not in workflow_text
    assert "schedule:" not in workflow_text
    assert "autoDeploy: true" not in render


def test_package5b_manifest_has_current_production_baseline_and_no_fake_proof():
    manifest = json.loads((ROOT / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
    assert manifest["package"].startswith("Package 5B")
    assert manifest["task_start_sha"] == "b9d3521f6b5a7fd9ac61c3670ac150d8a16df772"
    assert manifest["candidate_database_migration_head"] == "0010_package5_proof_v1"
    assert manifest["production_baseline"]["deployed_git_sha"] == "48b8be9a0fe52f9febd17d563aa43715ee2a542f"
    assert manifest["production_baseline"]["deploy_id"] is None
    assert manifest["production_baseline"]["deploy_id_status"] == "not_supplied_by_package_5b_checkpoint_verify_render"
    assert manifest["production_baseline"]["actual_live_database_revision"] == "0010_package5_proof_v1"
    assert manifest["package_5_proof_state"]["independent_agents_proven"] == 0
    assert manifest["package_5_proof_state"]["qualifying_vuos_proven"] == 0
    assert manifest["package_5_proof_state"]["qualifying_returns_proven"] == 0
    assert manifest["production_action_authorized_by_candidate"] is False
    assert manifest["package_5_semantics_changed_by_candidate"] is False
    assert "final_candidate_sha" not in manifest


def test_package5b_uses_shared_journey_and_does_not_add_a2a_protected_adapter():
    main_source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    a2a_source = (ROOT / "app" / "a2a_official.py").read_text(encoding="utf-8")
    journey_source = (ROOT / "app" / "machine_journey.py").read_text(encoding="utf-8")
    migration_names = {
        path.name for path in (ROOT / "alembic" / "versions").glob("*.py")
    }

    assert "verified_outcome_journey" in main_source
    assert "verified_outcome_journey" in a2a_source
    assert "No credential-bearing A2A Package 3 action adapter exists" in journey_source
    assert "No credential-bearing A2A Package 5 write adapter exists" in journey_source
    assert '"available": False' in journey_source
    assert 'action == "verify_external_callability"' not in a2a_source
    assert 'action == "submit_package5_vuo"' not in a2a_source
    assert not any(name.startswith("0011_") for name in migration_names)


def test_package5_has_one_shared_read_model_and_no_public_classification_write():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert main.package5_proof_snapshot is package5_proof.package5_proof_snapshot
    assert source.count("package5_proof_snapshot(db)") == 2
    assert '@app.get("/proof/package-5")' in source
    assert '@app.post("/proof/package-5/vuos")' in source
    assert "/proof/package-5/class" not in source
    assert "record_participation_assessment(" not in source
    assert '"/proof/package-5/vuos"' in source


def test_package5_migration_and_postgres_0009_gate_are_wired():
    workflow = (ROOT / ".github" / "workflows" / "postgres-release-gate.yml").read_text(encoding="utf-8")
    migration = (ROOT / "alembic" / "versions" / "0010_package5_proof_v1.py").read_text(encoding="utf-8")
    assert 'down_revision = "0009_continuous_learning_v1"' in migration
    assert "codex/package-5-independent-external-agent-proof-v1" in workflow
    assert "upgrade 0009_continuous_learning_v1" in workflow
    assert "postgres_0009_package5_proof.py seed" in workflow
    assert "postgres_0009_package5_proof.py verify" in workflow
    workflow_data = yaml.load(workflow, Loader=yaml.BaseLoader)
    assert "schedule" not in workflow_data["on"]
