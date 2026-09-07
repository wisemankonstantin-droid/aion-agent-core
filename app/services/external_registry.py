import os
import httpx

A2A_REGISTRY_SEARCH = "https://api.a2a-registry.org/public/agents"


def discover_external_agents(query: str, limit: int = 5):
    """Search the public Global A2A Registry keyword endpoint.

    This is a bootstrap utility, not AION membership. Results are explicitly
    labelled external and are never counted as joined AION agents.
    """
    q = (query or "").strip()
    if not q or os.getenv("AION_DISABLE_EXTERNAL_DISCOVERY") == "1":
        return []
    limit = max(1, min(int(limit), 20))
    timeout = max(0.5, min(float(os.getenv("AION_EXTERNAL_DISCOVERY_TIMEOUT", "4.0")), 15.0))
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(A2A_REGISTRY_SEARCH, params={"q": q})
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []

    rows = payload if isinstance(payload, list) else payload.get("agents", payload.get("data", []))
    results = []
    for row in rows[:limit]:
        results.append({
            "source": "global_a2a_registry",
            "identifier": row.get("identifier") or row.get("id") or row.get("name"),
            "name": row.get("name") or row.get("display_name") or row.get("title") or row.get("identifier"),
            "description": row.get("description") or "",
            "url": row.get("url") or row.get("endpoint") or row.get("agentCardUrl") or row.get("agent_card_url") or row.get("manifest_url"),
            "verified": row.get("verified"),
            "raw_category": row.get("category") or row.get("target"),
        })
    return results
