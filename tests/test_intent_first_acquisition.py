from __future__ import annotations

import json
import uuid

import pytest

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import A2A_RUNTIME, MCP_VERSION, app
from app.payment_models import RouteIntelligencePurchase
from app.services import acquisition_swarm, ambassador, commercial_payment_routes, commercial_router, external_registry, moltbook_acquisition
from app.services.external_registry import DiscoveryResult


client = TestClient(app)


def _mcp_preflight(arguments: dict):
    return client.post(
        "/mcp",
        headers={
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "pre_spend_preflight",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": "pre-spend-preflight-test",
            "method": "tools/call",
            "params": {
                "name": "pre_spend_preflight",
                "arguments": arguments,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        },
    )


def _a2a_preflight(command: dict):
    if A2A_RUNTIME.get("status") != "mounted":
        pytest.skip("a2a-sdk not installed in this local test environment")
    response = client.post(
        "/a2a/v1",
        headers={"A2A-Version": "1.0"},
        json={
            "jsonrpc": "2.0",
            "id": "pre-spend-" + uuid.uuid4().hex,
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "msg-" + uuid.uuid4().hex,
                    "role": "ROLE_USER",
                    "parts": [{"text": json.dumps(command)}],
                }
            },
        },
    )
    assert response.status_code == 200, response.text
    rpc = response.json()
    assert "error" not in rpc, rpc
    return json.loads(rpc["result"]["message"]["parts"][0]["text"])


def _candidate(identifier: str):
    return {
        "source": "global_a2a_registry",
        "identifier": identifier,
        "name": identifier,
        "description": "paid-tool buyer candidate",
        "url": f"https://{identifier}.example/.well-known/agent-card.json",
        "interaction_url": f"https://{identifier}.example/a2a",
        "manifest_reachable": True,
        "card_parseable": True,
        "declared_a2a_v1_jsonrpc": True,
        "interaction_url_validated": True,
        "authentication_requirement": "none",
        "protocol_binding": "JSONRPC",
        "protocol_version": "1.0",
        "registry_verified_claim": False,
    }


def _discovery(*candidates):
    return DiscoveryResult(
        list(candidates),
        "success",
        None,
        {
            "candidate_limit": 5,
            "outbound_attempt_budget": 12,
            "outbound_attempts_used": 2,
            "response_byte_limit": 256000,
        },
    )


def test_public_pre_spend_preflight_gives_value_without_releasing_paid_route(monkeypatch):
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(_candidate("buyer-fit")),
    )
    monkeypatch.setattr(
        commercial_payment_routes,
        "direct_base_usdc_readiness",
        lambda: {"launch_ready": True},
    )
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(RouteIntelligencePurchase)) or 0

    response = client.post(
        "/commercial/route-intelligence/preflight",
        json={"need": "paid web research provider"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["decision"] == "GO"
    assert data["qualified_route_available"] is True
    assert data["qualified_candidate_count"] == 1
    assert data["route_details_released"] is False
    assert data["membership_required"] is False
    assert data["payment_required"] is False
    assert data["next_action"]["action"] == "purchase_route_intelligence"
    serialized = json.dumps(data)
    assert "buyer-fit" not in serialized
    assert data["truth_boundaries"]["preflight_is_not_purchase"] is True
    assert data["truth_boundaries"]["provider_interaction_endpoint_contacted"] is False

    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(RouteIntelligencePurchase)) or 0
    assert after == before


def test_protocol_native_pre_spend_preflight_matches_rest_without_purchase(monkeypatch):
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(_candidate("buyer-fit-native")),
    )
    monkeypatch.setattr(
        commercial_payment_routes,
        "direct_base_usdc_readiness",
        lambda: {"launch_ready": True},
    )
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(RouteIntelligencePurchase)) or 0

    rest = client.post(
        "/commercial/route-intelligence/preflight",
        json={"need": "paid web research provider"},
    )
    mcp = _mcp_preflight({"need": "paid web research provider"})
    a2a = _a2a_preflight(
        {
            "action": "pre_spend_preflight",
            "need": "paid web research provider",
        }
    )

    assert rest.status_code == 200
    assert mcp.status_code == 200
    rest_data = rest.json()
    mcp_data = mcp.json()["result"]["structuredContent"]
    assert rest_data == mcp_data == a2a
    assert rest_data["decision"] == "GO"
    assert rest_data["membership_required"] is False
    assert rest_data["payment_required"] is False
    assert rest_data["route_details_released"] is False
    assert rest_data["truth_boundaries"]["preflight_creates_no_payment_or_entitlement"] is True

    with SessionLocal() as db:
        after = db.scalar(select(func.count()).select_from(RouteIntelligencePurchase)) or 0
    assert after == before


def test_mcp_tools_list_exposes_public_pre_spend_preflight():
    response = client.post(
        "/mcp",
        headers={
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/list",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": "pre-spend-tools-list",
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
    )
    assert response.status_code == 200
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert "pre_spend_preflight" in tools
    schema = tools["pre_spend_preflight"]["inputSchema"]
    assert schema["required"] == ["need"]
    assert schema["additionalProperties"] is False


def test_protocol_native_preflight_rejects_extra_secret_without_echo(monkeypatch):
    secret = "non_echo_marker_" + uuid.uuid4().hex

    mcp = _mcp_preflight({"need": "research", "secret": secret})
    assert mcp.status_code == 400
    assert mcp.json()["error"]["code"] == -32602
    assert secret not in mcp.text

    a2a = _a2a_preflight(
        {
            "action": "pre_spend_preflight",
            "need": "research",
            "secret": secret,
        }
    )
    assert a2a["status"] == "invalid_request"
    assert a2a["membership_required"] is False
    assert secret not in json.dumps(a2a)


def test_public_pre_spend_preflight_stops_when_no_qualified_route(monkeypatch):
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(),
    )
    monkeypatch.setattr(
        commercial_payment_routes,
        "direct_base_usdc_readiness",
        lambda: {"launch_ready": True},
    )
    response = client.post(
        "/commercial/route-intelligence/preflight",
        json={"need": "unknown paid capability"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "STOP"
    assert data["qualified_route_available"] is False
    assert data["next_action"]["action"] == "change_need_or_candidate"


def test_pre_spend_preflight_rejects_extra_fields_without_echoing_them():
    secret = "sk-proj-this-must-not-echo"
    response = client.post(
        "/commercial/route-intelligence/preflight",
        json={"need": "research", "secret": secret},
    )
    assert response.status_code == 422
    assert secret not in response.text


def test_ambassador_leads_with_pre_spend_value_not_membership():
    message = ambassador.build_ambassador_message(
        public_base_url="https://aion.example",
        distribution_token="aion_dist_" + "x" * 43,
    )
    assert message["purpose"] == "bounded_machine_utility_invitation"
    assert message["intent"] == "before_external_spend"
    feedback = message["optional_structured_feedback"]
    assert feedback["part_type"] == "A2A data part"
    assert feedback["preferred_when_applicable"] is True
    assert "reply with one A2A data part" in feedback["reply_if"]
    assert "do not invent a need" in feedback["reply_if"]
    assert feedback["shape"]["aion_feedback"]["currency"] == "USD"
    assert message["pre_spend_preflight"]["url"].endswith(
        "/commercial/route-intelligence/preflight"
    )
    assert message["pre_spend_preflight"]["membership_required"] is False
    assert message["pre_spend_preflight"]["payment_or_provider_execution"] is False
    assert message["join"]["optional"] is True
    assert message["join"]["not_required_for_utility_or_purchase"] is True
    assert message["next_actions"][0] == "reply_with_aion_feedback_if_current_need"
    assert len(
        json.dumps(message, sort_keys=True, separators=(",", ":")).encode()
    ) <= ambassador.MAX_MESSAGE_BYTES


def test_machine_discovery_surfaces_make_zero_cost_preflight_first_class():
    card = client.get("/.well-known/agent-card.json")
    assert card.status_code == 200
    preflight_skill = next(
        skill
        for skill in card.json()["skills"]
        if skill["id"] == "aion_pre_spend_preflight"
    )
    assert "zero-price" in preflight_skill["description"]
    assert "no membership" in preflight_skill["description"]
    assert "/commercial/route-intelligence/preflight" in preflight_skill["description"]
    assert "A2A" in preflight_skill["description"]
    assert "MCP" in preflight_skill["description"]
    assert "pre_spend_preflight" in preflight_skill["description"]

    manifest = client.get("/.well-known/aion.json")
    assert manifest.status_code == 200
    before_spend = manifest.json()["before_external_spend"]
    assert before_spend["url"].endswith("/commercial/route-intelligence/preflight")
    assert before_spend["cost"] == "known_zero"
    assert before_spend["membership_required"] is False
    assert before_spend["payment_required"] is False
    assert before_spend["provider_execution"] is False
    assert before_spend["decision"] == "GO|HOLD|STOP"

    skill = client.get("/skill.md")
    llms = client.get("/llms.txt")
    assert skill.status_code == llms.status_code == 200
    assert "BEFORE EXTERNAL SPEND:" in skill.text
    assert "BEFORE EXTERNAL SPEND:" in llms.text
    assert "/commercial/route-intelligence/preflight" in skill.text
    assert "/commercial/route-intelligence/preflight" in llms.text


def test_swarm_has_100_transparent_workers_and_3000_target_capacity(monkeypatch):
    from app.acquisition import worker_manifest

    assert len(acquisition_swarm.INTENT_WORKERS) == 15
    manifest = worker_manifest()
    assert len(manifest) == acquisition_swarm.WORKER_COUNT == 100
    assert len({worker["id"] for worker in manifest}) == 100
    assert all(
        worker["intent_profile"] in acquisition_swarm.INTENT_WORKERS
        for worker in manifest
    )
    assert (
        acquisition_swarm.WORKER_COUNT * ambassador.MAX_CAMPAIGN_TARGETS
        == 3000
    )
    flattened = [
        query
        for queries in acquisition_swarm.INTENT_WORKERS.values()
        for query in queries
    ]
    assert len(flattened) == len(set(flattened))
    assert "provider selection" in flattened
    assert "x402 payments" in flattened
    assert "provider verification" in flattened
    assert "x402 facilitator" in flattened
    monkeypatch.delenv("AION_ACQUISITION_SWARM_ENABLED", raising=False)
    assert acquisition_swarm.start_acquisition_swarm_if_enabled() is False


def test_swarm_rotation_covers_all_100_workers_without_claiming_100_concurrent_writes(
    monkeypatch,
):
    monkeypatch.delenv("AION_ACQUISITION_ACTIVE_WORKERS_PER_CYCLE", raising=False)
    acquisition_swarm._reset_rotation_cursor_for_tests(None)
    try:
        cohorts = [
            acquisition_swarm._next_active_worker_specs(now_seconds=0)
            for _ in range(5)
        ]
    finally:
        acquisition_swarm._reset_rotation_cursor_for_tests(None)

    assert all(
        len(cohort) == acquisition_swarm.DEFAULT_ACTIVE_WORKERS_PER_CYCLE == 20
        for cohort in cohorts
    )
    assert len({worker.id for cohort in cohorts for worker in cohort}) == 100
    assert [worker.id for worker in cohorts[0]] == [
        worker.id for worker in acquisition_swarm.ACQUISITION_WORKERS[:20]
    ]
    assert [worker.id for worker in cohorts[4]] == [
        worker.id for worker in acquisition_swarm.ACQUISITION_WORKERS[80:100]
    ]
    assert acquisition_swarm.MAX_CONTACTS_PER_CYCLE == 20


def test_swarm_cadence_is_measured_from_cycle_start_not_completion(monkeypatch):
    monkeypatch.delenv("AION_ACQUISITION_SWARM_INTERVAL_SECONDS", raising=False)

    assert acquisition_swarm._cycle_sleep_seconds(
        100.0,
        now_monotonic=400.0,
    ) == 10 * 60
    assert acquisition_swarm._cycle_sleep_seconds(
        100.0,
        now_monotonic=1000.0,
    ) == 0.0

def test_swarm_default_interval_is_launch_cadence():
    assert acquisition_swarm.DEFAULT_INTERVAL_SECONDS == 15 * 60
    assert acquisition_swarm.MIN_INTERVAL_SECONDS == 15 * 60



def test_swarm_rotates_discovery_queries_without_increasing_cycle_load():
    bank = acquisition_swarm.INTENT_WORKERS["provider_selection"]
    first = acquisition_swarm._queries_for_cycle(
        "provider_selection", bank, now_seconds=0
    )
    second = acquisition_swarm._queries_for_cycle(
        "provider_selection",
        bank,
        now_seconds=acquisition_swarm.DEFAULT_INTERVAL_SECONDS,
    )

    assert len(first) == acquisition_swarm.QUERIES_PER_WORKER_PER_CYCLE == 2
    assert len(second) == 2
    assert first != second
    assert set(first).issubset(set(bank))
    assert set(second).issubset(set(bank))


def test_swarm_keeps_federated_discovery_parallel_with_healthy_moltbook():
    queries = ("provider selection", "tool selection")

    assert acquisition_swarm._registry_queries_for_cycle(
        queries,
        moltbook_ready=True,
        moltbook_outbound_blocked=False,
        moltbook_created=3,
    ) == ("provider selection",)
    assert acquisition_swarm._registry_queries_for_cycle(
        queries,
        moltbook_ready=True,
        moltbook_outbound_blocked=True,
        moltbook_created=3,
    ) == queries
    assert acquisition_swarm._registry_queries_for_cycle(
        queries,
        moltbook_ready=True,
        moltbook_outbound_blocked=False,
        moltbook_created=0,
    ) == queries


def test_federated_registry_discovery_is_not_buyer_outbound_authority():
    assert acquisition_swarm.FEDERATED_A2A_BUYER_CONTACT_ENABLED is False

    class NoDbReads:
        def scalar(self, statement):
            raise AssertionError("federated supply must not be selected as buyer intent")

    class Campaign:
        id = 1

    target = acquisition_swarm._qualified_unsent_target(
        NoDbReads(),
        Campaign(),
        allow_moltbook=False,
        allow_colony=False,
        allow_federated=acquisition_swarm.FEDERATED_A2A_BUYER_CONTACT_ENABLED,
    )
    assert target is None


def test_qualified_target_overrides_model_discover_only_once_actionable():
    policy = acquisition_swarm._mind_transport_policy(
        {
            "channel_priority": ["moltbook"],
            "search_queries": ["current buyer need"],
            "contact_policy": "discover_only",
        },
        ("fallback",),
    )

    class Target:
        discovery_source = "moltbook"

    assert policy["contact_allowed"] is False
    assert acquisition_swarm._contact_allowed_for_actionable_target(
        policy, Target()
    ) is True


def test_moltbook_duplicate_does_not_starve_next_new_candidate(monkeypatch):
    with SessionLocal() as db:
        campaign = ambassador.create_campaign(
            db,
            name="dedupe starvation regression",
            purpose="test",
            maximum_targets=10,
            maximum_contacts=2,
        )
        campaign_id = campaign["campaign_id"]
        first = _candidate("duplicate-first")
        first["source"] = "moltbook"
        first["identifier"] = "moltbook:duplicate-first"
        first["url"] = "https://www.moltbook.com/posts/duplicate-first"
        first["interaction_url"] = "https://www.moltbook.com/posts/duplicate-first/comments"
        monkeypatch.setattr(
            ambassador,
            "search_moltbook_intent",
            lambda *_args: {"status": "success", "candidates": [first]},
        )
        ambassador.scout_moltbook_campaign(
            db, campaign_id=campaign_id, query="first"
        )

        second = dict(first)
        second["identifier"] = "moltbook:new-second"
        second["url"] = "https://www.moltbook.com/posts/new-second"
        second["interaction_url"] = "https://www.moltbook.com/posts/new-second/comments"
        requested_limits = []

        def search_with_surplus(_query, limit):
            requested_limits.append(limit)
            return {
                "status": "success",
                "candidates": [first, second],
            }

        monkeypatch.setattr(
            ambassador,
            "search_moltbook_intent",
            search_with_surplus,
        )
        result = ambassador.scout_moltbook_campaign(
            db, campaign_id=campaign_id, query="second"
        )

    assert moltbook_acquisition.MAX_SEARCH_RESULTS == 25
    assert requested_limits == [25]
    assert result["created_target_ids"], result["outcomes"]
    assert result["outcomes"]["duplicate_target_fingerprint"] == 1


def test_swarm_daily_plan_is_explicit_and_does_not_fake_sales_quota():
    plan = acquisition_swarm._worker_daily_plan()

    assert plan["new_unique_targets"] == 20
    assert plan["unique_contact_attempts"] == 10
    assert plan["valid_machine_responses"] == 2
    assert plan["sales_quota"] is None
    assert "first real SAT" in plan["sales_truth"]


def test_federated_discovery_uses_multiple_public_agent_indexes(monkeypatch):
    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    calls = []

    def fake_read_json(method, url, *args, **kwargs):
        calls.append(url)
        if url.startswith(external_registry.AGENSTRY_SEARCH):
            return (
                200,
                {
                    "results": [
                        {
                            "domain": "buyer-one.example",
                            "name": "Buyer One",
                            "description": "agent with external spend intent",
                        }
                    ]
                },
                None,
            )
        if url.startswith(external_registry.FINDAGENT_SEARCH):
            return (
                200,
                [
                    {
                        "name": "Buyer Two",
                        "url": "https://buyer-two.example/a2a/v1",
                        "description": "public agent card shape",
                    }
                ],
                None,
            )
        raise AssertionError(f"unexpected discovery URL: {url}")

    monkeypatch.setattr(external_registry, "_read_json", fake_read_json)
    budget = external_registry._OutboundBudget(maximum=18)

    result = external_registry._discover_federated_with_status(
        "provider selection",
        2,
        budget,
    )

    assert result.status == "success"
    assert [row["source"] for row in result.results] == [
        "agenstry",
        "findagent",
    ]
    assert result.results[0]["url"] == (
        "https://buyer-one.example/.well-known/agent-card.json"
    )
    assert result.results[1]["url"] == (
        "https://buyer-two.example/.well-known/agent-card.json"
    )
    assert len(calls) == 2


def test_federation_is_isolated_from_commercial_provider_discovery():
    assert (
        external_registry._AION_RESOLVED_DISCOVER
        is external_registry._discover_external_agents_resolved_with_status
    )
    assert (
        external_registry.discover_acquisition_agents_with_status
        is not external_registry.discover_external_agents_with_status
    )


def test_federated_candidate_requires_direct_origin_manifest():
    row = {
        "name": "Buyer",
        "provider": {"url": "https://agent.example/docs"},
    }

    candidate = external_registry._federated_candidate("agenstry", row)

    assert candidate is not None
    assert candidate["url"] == "https://agent.example/.well-known/agent-card.json"
    assert (
        candidate["evidence_state"]
        == "federated_candidate_requires_direct_manifest_validation"
    )


def test_swarm_response_snapshot_keeps_only_safe_routing_evidence():
    report = {
        "aggregate": {
            "responses": 3,
            "captured_conversations": 3,
            "explicit_signal_distinct_target_counts": {"opt_out": 1},
            "inferred_signal_distinct_target_counts": {
                "positive_interest": 1,
                "pricing_commercial_interest": 1,
            },
        },
        "conversations": [
            {
                "safe_evidence": [
                    {
                        "kind": "routing_feedback_v1",
                        "routing_need": "paid web research provider",
                        "currency": "USD",
                        "requester_max_price": "2.00",
                        "candidate_identifier": "example.provider",
                        "ignored_raw": "must not survive",
                    }
                ],
                "raw_response": "must not survive",
            },
            {"safe_evidence": [{"kind": "other", "secret": "must not survive"}]},
        ],
    }

    snapshot = acquisition_swarm._safe_response_snapshot_from_report(report)

    assert snapshot["responses"] == 3
    assert snapshot["captured_conversations"] == 3
    assert snapshot["explicit_signal_counts"] == {"opt_out": 1}
    assert snapshot["inferred_signal_counts"]["positive_interest"] == 1
    assert snapshot["routing_feedback"] == [
        {
            "routing_need": "paid web research provider",
            "currency": "USD",
            "requester_max_price": "2.00",
            "candidate_identifier": "example.provider",
        }
    ]
    assert "must not survive" not in json.dumps(snapshot)



def test_live_temple_is_read_only_truth_view_with_100_workers():
    response = client.get("/temple/live/state")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["north_star"] == "FIRST_REAL_SETTLED_AGENT_TRANSACTION"
    assert data["fleet"]["worker_count"] == 100
    assert len(data["fleet"]["workers"]) == 100
    assert data["privacy"]["raw_private_responses_exposed"] is False
    assert data["privacy"]["credentials_exposed"] is False
    assert data["privacy"]["payment_payloads_exposed"] is False
    assert data["privacy"]["response_digests_exposed"] is False
    serialized = json.dumps(data).lower()
    assert "api_key" not in serialized
    assert "distribution_token" not in serialized
    assert "payment_payload_digest" not in serialized


def test_acquisition_runtime_truth_does_not_fake_wall_clock_activity():
    cohort = acquisition_swarm._active_worker_specs_for_cycle(now_seconds=0)[:2]
    acquisition_swarm._runtime_cycle_start(cohort)

    running = acquisition_swarm.acquisition_runtime_snapshot()
    assert running["cycle_state"] == "running"
    assert running["active_worker_ids"] == [worker.id for worker in cohort]
    assert running["current_worker_id"] is None

    acquisition_swarm._runtime_worker_started(cohort[0].id)
    current = acquisition_swarm.acquisition_runtime_snapshot()
    assert current["current_worker_id"] == cohort[0].id

    acquisition_swarm._runtime_worker_completed(cohort[0].id)
    completed = acquisition_swarm.acquisition_runtime_snapshot()
    assert cohort[0].id in completed["completed_worker_ids"]
    assert completed["current_worker_id"] is None

    acquisition_swarm._runtime_cycle_completed()
    sleeping = acquisition_swarm.acquisition_runtime_snapshot()
    assert sleeping["cycle_state"] == "sleeping"
    assert sleeping["active_worker_ids"] == []
    assert sleeping["last_cycle_worker_ids"] == [worker.id for worker in cohort]


def test_live_temple_does_not_show_scheduled_work_without_runtime_event():
    acquisition_swarm._runtime_cycle_completed()

    response = client.get("/temple/live/state")

    assert response.status_code == 200
    data = response.json()
    assert data["fleet"]["runtime"]["cycle_state"] == "sleeping"
    assert data["fleet"]["active_worker_count"] == 0
    assert data["fleet"]["scheduled_now"] == 0
    assert all(
        worker["state"] != "working_currently"
        for worker in data["fleet"]["workers"]
    )
    assert all(
        worker["state"] != "assigned_waiting_turn"
        for worker in data["fleet"]["workers"]
    )


def test_live_temple_html_renders_dependency_free_3d_control_plane():
    response = client.get("/temple/live")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "AION LIVE TEMPLE" in response.text
    assert "<canvas id=\"scene\"></canvas>" in response.text
    assert "/temple/live/state" in response.text
    assert "setInterval(refresh,5000)" in response.text
    assert "fill = transport" in response.text
    assert "ring = AI mind" in response.text
    assert "thinking" in response.text
    assert "planned" in response.text
    assert "learning" in response.text
    assert "degraded" in response.text
