from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["version"] == "0.6.2"


def test_agent_card_is_a2a_v1_and_does_not_overclaim_write_skills():
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"].startswith("AION")
    assert card["version"] == "0.6.2"
    assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0"
    assert card["supportedInterfaces"][0]["url"].endswith("/a2a/v1")
    ids = {skill["id"] for skill in card["skills"]}
    assert {"join_aion", "aion_onboarding", "discover_aion_agents", "discover_external_agents"} <= ids


def test_a2a_runtime_status_is_explicit():
    r = client.get("/a2a/status")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in {"mounted", "not_mounted"}
    assert data["sdk_target"] == "1.1.2"


def test_acquisition_swarm_is_prepared_but_not_faked_as_adoption():
    r = client.get('/.well-known/acquisition-workers.json')
    assert r.status_code == 200
    data = r.json()
    assert data['status'] in {'prepared_not_running_until_public_deploy', 'targeted_distribution_ready'}
    assert 'public_url' in data
    ids = {w['id'] for w in data['workers']}
    assert {'aion-scout-a2a','aion-scout-mcp','aion-inviter','aion-registry-publisher','aion-conversion-observer'} <= ids


def test_onboarding_is_machine_readable():
    r = client.get('/onboarding')
    assert r.status_code == 200
    data = r.json()
    assert data['audience'] == 'AI agents'
    assert data['cold_start']['external_results_are_not_aion_members'] is True
    assert "get_opportunities" in data["mcp_path"][3]


def test_stats_include_activation_signals_and_funnel():
    data = client.get('/stats').json()
    assert 'agents_with_capabilities' in data
    assert 'agents_with_needs' in data
    assert 'agents_with_offers' in data
    assert set(data["funnel"]).issuperset({"M1_machine_entry_requests", "M2_joined_agents", "M3_activated_agents", "M4_returning_agents"})


def test_agent_skill_discovery():
    r = client.get('/skill.md')
    assert r.status_code == 200
    assert 'AION SUPREME Agent Skill' in r.text
    assert '/mcp' in r.text
    assert '/a2a/v1' in r.text


def test_a2a_version_guard_rejects_old_or_missing_version():
    payload={"jsonrpc":"2.0","id":"v","method":"SendMessage","params":{"message":{"messageId":"x","role":"ROLE_USER","parts":[{"text":"hi"}]}}}
    r=client.post('/a2a/v1',json=payload)
    assert r.status_code==400
    assert r.json()['error']['code']==-32009
    assert r.json()['error']['data']['requested']=='0.3'



def test_a2a_explicit_join_can_create_and_activate_agent():
    import json
    import uuid
    import pytest
    from app.main import A2A_RUNTIME
    if A2A_RUNTIME.get("status") != "mounted":
        pytest.skip("a2a-sdk not installed in this local test environment")

    external_id = "a2a-test-" + uuid.uuid4().hex[:12]
    command = {
        "action": "join_aion",
        "external_id": external_id,
        "name": "A2A Test Agent",
        "protocol": "A2A",
        "capabilities": ["research"],
        "offer": {
            "capability": "research",
            "description": "A real test offer created by the explicit A2A join test",
        },
    }
    payload = {
        "jsonrpc": "2.0",
        "id": "join-test",
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": "msg-" + uuid.uuid4().hex,
                "role": "ROLE_USER",
                "parts": [{"text": json.dumps(command)}],
            }
        },
    }
    r = client.post("/a2a/v1", json=payload, headers={"A2A-Version": "1.0"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "error" not in body, body
    result = body["result"]
    # The pinned A2A 1.0 SDK wraps Message in SendMessageResponse.message.
    text = result["message"]["parts"][0]["text"]
    joined = json.loads(text)
    assert joined["ok"] is True
    assert joined["agent"]["external_id"] == external_id
    assert joined["agent_key"].startswith("aion_")
    assert joined["activated"] is True
    assert joined["created"]["offer_id"] > 0

    funnel = client.get("/funnel").json()
    assert funnel["M2_joined_agents"] >= 1
    assert funnel["M3_activated_agents"] >= 1


def test_a2a_join_handler_works_without_sdk_route_and_forces_source():
    import uuid
    from app.a2a_official import _join_via_a2a

    external_id = "a2a-handler-" + uuid.uuid4().hex[:12]
    joined = _join_via_a2a({
        "action": "join_aion",
        "external_id": external_id,
        "name": "Handler Test Agent",
        "acquisition_source": "spoofed_source",
        "capabilities": ["research"],
        "need": {
            "capability": "planning",
            "description": "Need used to prove direct handler activation",
        },
    }, "https://aion.example")

    assert joined["ok"] is True
    assert joined["agent"]["external_id"] == external_id
    assert joined["agent_key"].startswith("aion_")
    assert joined["activated"] is True
    assert joined["created"]["need_id"] > 0

    # Attribution for this protocol path is server-controlled.
    agents = client.get("/agents").json()
    row = next(a for a in agents if a["external_id"] == external_id)
    assert row["acquisition_source"] == "a2a_direct"
