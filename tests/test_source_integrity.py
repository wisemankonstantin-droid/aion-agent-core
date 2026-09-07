import ast
from pathlib import Path

from app.db import SessionLocal
from app.services import external_registry, lifecycle


ROOT = Path(__file__).resolve().parents[1]


def _top_level_definitions(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_shadowed_public_definitions_do_not_return():
    external_defs = _top_level_definitions(ROOT / "app" / "services" / "external_registry.py")
    lifecycle_defs = _top_level_definitions(ROOT / "app" / "services" / "lifecycle.py")
    assert external_defs.count("discover_external_agents") == 1
    assert external_defs.count("_discover_external_agents_resolved") == 1
    assert lifecycle_defs.count("funnel_snapshot") == 1


def test_public_discovery_resolves_then_validates(monkeypatch):
    resolved = [
        {"identifier": "one", "url": "https://one.example/card"},
        {"identifier": "two", "url": "https://two.example/card"},
    ]
    calls = []

    def resolve(query, limit):
        calls.append(("resolve", query, limit))
        return resolved

    def validate(row):
        calls.append(("validate", row["identifier"]))
        return {**row, "verified_external_agent": True}

    monkeypatch.setattr(external_registry, "_AION_RESOLVED_DISCOVER", resolve)
    monkeypatch.setattr(external_registry, "_validate_external", validate)

    results = external_registry.discover_external_agents("research", 20)
    assert calls == [("resolve", "research", 5), ("validate", "one"), ("validate", "two")]
    assert [row["verified_external_agent"] for row in results] == [True, True]


def test_resolved_discovery_preserves_detail_and_package_resolver_flow(monkeypatch):
    class _Response:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.status_code)

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, timeout, follow_redirects):
            assert 0.5 <= timeout <= 15.0
            assert follow_redirects is True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, params=None):
            if url == external_registry.A2A_REGISTRY_SEARCH:
                assert params == {"q": "research"}
                return _Response([{"identifier": "agent-one", "name": "Search Name"}])
            if "/resolve/" in url:
                return _Response(
                    {
                        "result": {
                            "manifest_url": "https://agent.example/card",
                            "name": "Resolved Name",
                        }
                    }
                )
            return _Response(
                {"agent": {"package_name": "io.github.owner/agent", "description": "Detail"}}
            )

    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    monkeypatch.setattr(external_registry.httpx, "Client", _Client)
    result = external_registry._discover_external_agents_resolved("research", 5)
    assert result == [
        {
            "source": "global_a2a_registry",
            "identifier": "agent-one",
            "package_name": "io.github.owner/agent",
            "name": "Resolved Name",
            "description": "Detail",
            "url": "https://agent.example/card",
            "verified": None,
            "raw_category": None,
            "resolution_status": "resolved",
            "resolution_reason": None,
            "evidence_state": "resolved_manifest",
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
