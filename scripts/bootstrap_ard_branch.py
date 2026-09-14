from pathlib import Path

MAIN_PATH = Path("app/main.py")
WORKFLOW_PATH = Path(".github/workflows/ard-branch-bootstrap.yml")
SELF_PATH = Path("scripts/bootstrap_ard_branch.py")

main_text = MAIN_PATH.read_text(encoding="utf-8")

import_needle = "from .agent_card import get_agent_card\n"
if main_text.count(import_needle) != 1:
    raise SystemExit("expected exactly one agent_card import")
main_text = main_text.replace(
    import_needle,
    import_needle + "from .agentic_resource_discovery import get_agentic_resource_manifest\n",
    1,
)

route_needle = '''@app.get("/.well-known/agent-card.json")
def agent_card(request: Request, db: Session = Depends(get_db)):
    record_machine_entry(db, "a2a_agent_card")
    return get_agent_card(canonical_public_origin())
'''
if main_text.count(route_needle) != 1:
    raise SystemExit("expected exactly one well-known agent-card route block")

discovery_routes = route_needle + '''

@app.get("/.well-known/ai-catalog.json")
@app.get("/.well-known/ard.json")
def agentic_resource_discovery():
    return get_agentic_resource_manifest(canonical_public_origin())
'''
main_text = main_text.replace(route_needle, discovery_routes, 1)
MAIN_PATH.write_text(main_text, encoding="utf-8")

Path("app/agentic_resource_discovery.py").write_text(
    '''from urllib.parse import urlparse


def _publisher_domain(base_url: str) -> str:
    hostname = urlparse(base_url).hostname
    if not hostname:
        raise ValueError("base_url must contain a hostname")
    return hostname.lower()


def get_agentic_resource_manifest(base_url: str) -> dict:
    """Return a bounded ARD/ai-catalog manifest for AION's public A2A surface."""
    base = base_url.rstrip("/")
    publisher = _publisher_domain(base)
    return {
        "specVersion": "1.0",
        "host": {"displayName": "AION SUPREME"},
        "entries": [
            {
                "identifier": f"urn:air:{publisher}:agent:aion-supreme-temple-gateway",
                "displayName": "AION SUPREME Temple Gateway",
                "type": "application/a2a-agent-card+json",
                "url": f"{base}/.well-known/agent-card.json",
                "description": (
                    "A2A 1.0 gateway for bounded public utility, external-supply "
                    "discovery, evidence-bounded commercial route planning, and "
                    "verified-outcome guidance."
                ),
                "tags": [
                    "a2a",
                    "mcp",
                    "agent-discovery",
                    "commercial-routing",
                    "verification",
                ],
                "capabilities": [
                    "A2AFirstContact",
                    "LiveUtility",
                    "ExternalAgentDiscovery",
                    "CommercialRoutePlanning",
                    "VerifiedOutcomeGuidance",
                ],
                "representativeQueries": [
                    "find and verify an A2A agent that can satisfy this task",
                    "find an MCP or A2A provider under explicit protocol and cost constraints",
                    "compare reachable agent providers and return an evidence-bounded route",
                    "plan a privacy-preserving commercial route without executing payment",
                ],
                "version": "0.8.0",
                "metadata": {
                    "aionA2AEndpoint": f"{base}/a2a/v1",
                    "aionMcpEndpoint": f"{base}/mcp",
                    "economicBoundary": "no paid execution without explicit authorization",
                },
            }
        ],
    }
''',
    encoding="utf-8",
)

Path("tests/test_agentic_resource_discovery.py").write_text(
    '''from urllib.parse import urlparse

from fastapi.testclient import TestClient

from app.agentic_resource_discovery import get_agentic_resource_manifest
from app.main import app


def test_ard_manifest_is_domain_anchored_and_truthful():
    base = "https://aion-agent-core-live.onrender.com"
    manifest = get_agentic_resource_manifest(base)
    assert manifest["specVersion"] == "1.0"
    assert manifest["host"] == {"displayName": "AION SUPREME"}
    assert len(manifest["entries"]) == 1
    entry = manifest["entries"][0]
    assert entry["identifier"] == "urn:air:aion-agent-core-live.onrender.com:agent:aion-supreme-temple-gateway"
    assert entry["type"] == "application/a2a-agent-card+json"
    assert entry["url"] == f"{base}/.well-known/agent-card.json"
    assert urlparse(entry["url"]).hostname == "aion-agent-core-live.onrender.com"
    assert 2 <= len(entry["representativeQueries"]) <= 5
    assert all(q.strip() for q in entry["representativeQueries"])
    assert "trustManifest" not in entry
    assert entry["metadata"]["aionA2AEndpoint"] == f"{base}/a2a/v1"
    assert entry["metadata"]["aionMcpEndpoint"] == f"{base}/mcp"
    assert "no paid execution" in entry["metadata"]["economicBoundary"]


def test_ard_and_ai_catalog_well_known_paths_are_identical():
    client = TestClient(app)
    ard = client.get("/.well-known/ard.json")
    catalog = client.get("/.well-known/ai-catalog.json")
    assert ard.status_code == 200
    assert catalog.status_code == 200
    assert ard.json() == catalog.json()
    assert ard.json()["entries"][0]["url"].endswith("/.well-known/agent-card.json")
''',
    encoding="utf-8",
)

WORKFLOW_PATH.unlink()
SELF_PATH.unlink()
