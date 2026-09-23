from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.payment_models import RouteIntelligencePurchase
from app.services import acquisition_swarm, ambassador, commercial_payment_routes, commercial_router, external_registry
from app.services.external_registry import DiscoveryResult


client = TestClient(app)


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
    assert message["optional_structured_feedback"]["part_type"] == "A2A data part"
    assert message["optional_structured_feedback"]["reply_if"] == "current real provider-selection or external-spend need"
    assert message["optional_structured_feedback"]["shape"]["aion_feedback"]["currency"] == "USD"
    assert message["pre_spend_preflight"]["url"].endswith(
        "/commercial/route-intelligence/preflight"
    )
    assert message["pre_spend_preflight"]["membership_required"] is False
    assert message["pre_spend_preflight"]["payment_or_provider_execution"] is False
    assert message["join"]["optional"] is True
    assert message["join"]["not_required_for_utility_or_purchase"] is True
    assert message["next_actions"][0] == "inspect_pre_spend_preflight"
    assert len(
        json.dumps(message, sort_keys=True, separators=(",", ":")).encode()
    ) <= ambassador.MAX_MESSAGE_BYTES


def test_swarm_has_independent_intent_lanes_and_450_target_capacity(monkeypatch):
    assert len(acquisition_swarm.INTENT_WORKERS) == 15
    assert (
        len(acquisition_swarm.INTENT_WORKERS) * ambassador.MAX_CAMPAIGN_TARGETS
        == 450
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

