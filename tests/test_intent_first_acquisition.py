from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import SessionLocal
from app.main import app
from app.payment_models import RouteIntelligencePurchase
from app.services import acquisition_swarm, ambassador, commercial_payment_routes, commercial_router
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


def test_swarm_has_independent_intent_lanes_and_300_target_capacity(monkeypatch):
    assert len(acquisition_swarm.INTENT_WORKERS) == 10
    assert (
        len(acquisition_swarm.INTENT_WORKERS) * ambassador.MAX_CAMPAIGN_TARGETS
        == 300
    )
    flattened = [
        query
        for queries in acquisition_swarm.INTENT_WORKERS.values()
        for query in queries
    ]
    assert len(flattened) == len(set(flattened))
    assert "provider selection" in flattened
    assert "x402 payments" in flattened
    monkeypatch.delenv("AION_ACQUISITION_SWARM_ENABLED", raising=False)
    assert acquisition_swarm.start_acquisition_swarm_if_enabled() is False
