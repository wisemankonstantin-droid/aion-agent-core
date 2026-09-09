import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.db import SessionLocal
from app import a2a_official, main
from app.services import action_engine, external_registry, lifecycle, opportunities
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
