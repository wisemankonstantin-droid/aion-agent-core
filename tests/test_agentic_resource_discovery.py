from urllib.parse import urlparse

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
    assert "PaidRouteIntelligence" in entry["capabilities"]
    assert entry["metadata"]["routeIntelligencePaymentReadiness"] == f"{base}/commercial/route-intelligence/payment-readiness"
    assert entry["metadata"]["routeIntelligencePurchase"] == f"{base}/commercial/route-intelligence/purchase"
    assert entry["metadata"]["routeIntelligencePaymentProtocol"] == "direct-base-usdc-eip3009-buyer-broadcast"
    assert entry["metadata"]["routeIntelligenceNetwork"] == "eip155:8453"
    assert entry["metadata"]["routeIntelligenceAsset"] == "USDC"
    assert entry["metadata"]["routeIntelligenceBuyerPaysGas"] is True
    assert entry["metadata"]["routeIntelligenceFacilitatorRequired"] is False


def test_ard_and_ai_catalog_well_known_paths_are_identical():
    client = TestClient(app)
    ard = client.get("/.well-known/ard.json")
    catalog = client.get("/.well-known/ai-catalog.json")
    assert ard.status_code == 200
    assert catalog.status_code == 200
    assert ard.json() == catalog.json()
    assert ard.json()["entries"][0]["url"].endswith("/.well-known/agent-card.json")
