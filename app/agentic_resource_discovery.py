from urllib.parse import urlparse


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
