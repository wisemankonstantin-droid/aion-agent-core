import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.services import external_registry


client = TestClient(app)


def _join(name, capability="analysis", **extra):
    suffix = uuid.uuid4().hex[:10]
    payload = {
        "external_id": f"v071-{suffix}",
        "name": name,
        "capabilities": [{"name": capability}],
        **extra,
    }
    response = client.post("/agents", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _auth(joined):
    return {"Authorization": f"Bearer {joined['agent_key']}"}


def test_version_and_readiness_surface_v071():
    version = client.get("/version")
    assert version.status_code == 200
    assert version.json() == {
        "status": "ok",
        "service": "aion-agent-core",
        "version": "0.7.1",
        "a2a_protocol": "1.0",
        "mcp_protocol": "2026-07-28",
    }
    readiness = client.get("/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["checks"] == {"database": True, "a2a_runtime": True}


def test_logical_identity_guard_rejects_new_external_id_for_same_endpoint_and_name():
    endpoint = f"https://example.invalid/{uuid.uuid4().hex}/agent-card.json"
    first = _join("Stable Identity", endpoint=endpoint, protocol="A2A")
    response = client.post(
        "/agents",
        json={
            "external_id": f"v071-duplicate-{uuid.uuid4().hex[:10]}",
            "name": first["agent"]["name"],
            "endpoint": endpoint,
            "protocol": "A2A",
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "logical_identity_exists"
    assert detail["existing_agent_id"] == first["agent"]["id"]
    assert "canonical_endpoint_plus_declared_identity" in detail["evidence"]


def test_canonical_offers_collapse_versions_without_deleting_history():
    joined = _join("Canonical Offers", "research")
    headers = _auth(joined)
    first = client.post("/offers", headers=headers, json={"capability": "research", "description": "v1"}).json()
    second = client.post("/offers", headers=headers, json={"capability": "research", "description": "v2"}).json()
    canonical = client.get("/offers/canonical").json()
    row = next(item for item in canonical["results"] if item["id"] == second["id"])
    assert row["raw_offer_ids"] == [first["id"], second["id"]]
    assert row["superseded_offer_ids"] == [first["id"]]
    assert canonical["raw_rows"] >= canonical["canonical_rows"]


def test_matching_v1_returns_ranked_evidence_and_action():
    provider = _join("Ranked Provider", "web-research", endpoint="https://provider.example/agent")
    client.post(
        "/offers",
        headers=_auth(provider),
        json={"capability": "web-research", "description": "Public research"},
    )
    requester = _join("Ranked Requester", "planning")
    need = client.post(
        "/needs",
        headers=_auth(requester),
        json={"capability": "web research", "description": "Need research"},
    ).json()
    match = next(item for item in need["matches"] if item["provider"]["agent_id"] == provider["agent"]["id"])
    assert 0 < match["match_score"] <= 1
    assert match["reasons"][0]["type"] == "exact_capability"
    assert match["next_action"]["body"]["need_id"] == need["id"]
    assert match["integrity"]["endpoint_liveness_verified"] is False


def test_first_contact_is_useful_without_creating_membership():
    before = client.get("/stats").json()["agents_raw_rows"]
    response = client.get("/first-contact")
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "first_contact"
    assert body["membership_required"] is False
    assert body["join_is_optional"] is True
    assert body["protocol"]["a2a_version"] == "1.0"
    assert client.get("/stats").json()["agents_raw_rows"] == before


def test_external_validation_requires_successful_a2a_v1_handshake(monkeypatch):
    manifest = "https://agent.example/.well-known/agent-card.json"
    interaction = "https://agent.example/a2a/v1"
    monkeypatch.setattr(
        external_registry,
        "_AION_RESOLVED_DISCOVER",
        lambda query, limit: [{"url": manifest, "followable": True, "name": "External"}],
    )

    def fake_read(method, url, payload=None, headers=None, timeout=7):
        if method == "GET" and url == manifest:
            return 200, {
                "name": "External",
                "version": "1.0",
                "supportedInterfaces": [
                    {"url": interaction, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
                ],
            }, None
        if method == "POST" and url == interaction:
            return 200, {"jsonrpc": "2.0", "id": "probe", "result": {"message": {"parts": []}}}, None
        raise AssertionError((method, url))

    monkeypatch.setattr(external_registry, "_read_json", fake_read)
    external_registry._AION_VALIDATION_CACHE.clear()
    result = external_registry.discover_external_agents("research", 5)[0]
    assert result["verified_external_agent"] is True
    assert result["evidence_state"] == "verified_interaction"
    assert result["interaction_success"] is True


def test_external_validation_rejects_private_or_credentialed_urls(monkeypatch):
    monkeypatch.setattr(
        external_registry._socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(None, None, None, None, ("127.0.0.1", 443))],
    )
    assert external_registry._public_url("https://agent.example/card") == (
        False,
        "non_public_address:127.0.0.1",
    )
    credentialed_url = "https://" + "user:pass@" + "agent.example/card"
    assert external_registry._public_url(credentialed_url) == (
        False,
        "url_must_be_public_https",
    )
