from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models
from app.db import SessionLocal
from app.main import app
from app.security import hash_key
from app.services import commercial_router
from app.services.external_registry import DiscoveryResult


client = TestClient(app)


def _agent():
    key = "aion_router_" + uuid.uuid4().hex
    with SessionLocal() as db:
        row = models.Agent(
            external_id="router-" + uuid.uuid4().hex,
            name="Commercial Router Test",
            protocol="REST",
            api_key_hash=hash_key(key),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, key


def _candidate(identifier: str, *, eligible: bool = True, registry_verified: bool = False):
    return {
        "source": "global_a2a_registry",
        "identifier": identifier,
        "name": identifier,
        "description": "bounded candidate",
        "url": f"https://{identifier}.example/.well-known/agent-card.json",
        "interaction_url": f"https://{identifier}.example/a2a",
        "manifest_reachable": eligible,
        "card_parseable": eligible,
        "declared_a2a_v1_jsonrpc": eligible,
        "interaction_url_validated": eligible,
        "authentication_requirement": "none" if eligible else "credentials_required",
        "protocol_binding": "JSONRPC",
        "protocol_version": "1.0",
        "registry_verified_claim": registry_verified,
    }


def _discovery(*candidates, status="success", failure=None, attempts=3):
    return DiscoveryResult(
        list(candidates),
        status,
        failure,
        {
            "candidate_limit": 5,
            "outbound_attempt_budget": 12,
            "outbound_attempts_used": attempts,
            "response_byte_limit": 256000,
        },
    )


def _plan(key: str, payload=None):
    return client.post(
        "/commercial/routes/plan",
        headers={"Authorization": "Bearer " + key},
        json=payload or {"need": "web research", "currency": "USD"},
    )


def _record_action(agent_id: int, identifier: str, *, verified: bool, failure_class: str | None = None):
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        run = models.ActionRun(
            action_id=str(uuid.uuid4()),
            requester_agent_id=agent_id,
            idempotency_key="router-history-" + uuid.uuid4().hex,
            request_digest="sha256:" + "a" * 64,
            requested_query="web research",
            requested_candidate_identifier=identifier,
            authorize_external_contact=True,
            selected_provider_identifier=identifier,
            source_id="global_a2a_registry",
            agent_card_url=f"https://{identifier}.example/card",
            interaction_url=f"https://{identifier}.example/a2a",
            discovery_evidence={"historical": True},
            protocol_binding="JSONRPC",
            protocol_version="1.0",
            state="completed" if verified else "failed",
            failure_class=failure_class,
            created_at=now,
            started_at=now,
            completed_at=now,
            duration_ms=1,
            discovery_attempt_count=1,
            action_attempt_count=1,
            request_bytes=1,
            response_bytes=1,
        )
        db.add(run)
        db.flush()
        db.add(
            models.ActionOutcome(
                action_run_id=run.id,
                outcome_type="callability_challenge_verified" if verified else "invocation_failed",
                protocol_response_received=verified,
                callability_verified=verified,
                capability_verified=False,
                verified_outcome=verified,
                normalized_result_kind="message" if verified else None,
                failure_class=failure_class,
                response_digest="sha256:" + "b" * 64 if verified else None,
                protocol_task_id=None,
                protocol_message_id=None,
                proof_present=verified,
                completed_at=now,
            )
        )
        db.commit()


def test_route_plan_requires_authentication(monkeypatch):
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("alpha")))
    response = client.post("/commercial/routes/plan", json={"need": "web research", "currency": "USD"})
    assert response.status_code in {401, 403}


def test_route_plan_is_fail_closed_unpriced_and_side_effect_free(monkeypatch):
    agent_id, key = _agent()
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("alpha", registry_verified=True)))
    with SessionLocal() as db:
        operations_before = db.scalar(select(func.count()).select_from(models.EconomicOperation)) or 0
        actions_before = db.scalar(select(func.count()).select_from(models.ActionRun)) or 0
        agent_before = db.get(models.Agent, agent_id)
        lifecycle_before = (agent_before.authenticated_calls, agent_before.last_seen_at, agent_before.first_useful_action_at)

    response = _plan(key, {"need": "web research", "currency": "USD", "requester_max_price": "25.00"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["state"] == "qualified_unpriced"
    assert data["selected_provider"]["identifier"] == "alpha"
    assert data["selected_provider"]["registry_verified_claim"] is True
    assert data["selected_provider"]["provider_verification_state"] == "declaration_qualified_only"
    assert data["commercial"]["requester_max_price"] == "25"
    assert data["commercial"]["provider_price_state"] == "unknown"
    assert data["commercial"]["provider_maximum_cost"] is None
    assert data["commercial"]["customer_price"] is None
    assert data["commercial"]["expected_margin_bps"] is None
    assert data["commercial"]["policy_eligible"] is False
    assert data["commercial"]["execution_eligible"] is False
    for reason in (
        "provider_price_unknown",
        "unknown_maximum_cost",
        "commercial_rights_unknown",
        "margin_not_computable",
        "payment_not_authorized",
        "reserve_not_established",
        "real_money_adapter_disabled",
    ):
        assert reason in data["commercial"]["decision_reasons"]
    assert data["execution"]["provider_interaction_endpoint_contacted"] is False
    assert data["execution"]["payment_rail_contacted"] is False
    assert data["execution"]["economic_operation_created"] is False
    assert data["execution"]["real_money_execution_enabled"] is False
    assert data["truth_boundaries"]["route_plan_is_not_vuo_or_adoption_proof"] is True

    with SessionLocal() as db:
        assert (db.scalar(select(func.count()).select_from(models.EconomicOperation)) or 0) == operations_before
        assert (db.scalar(select(func.count()).select_from(models.ActionRun)) or 0) == actions_before
        agent_after = db.get(models.Agent, agent_id)
        assert (agent_after.authenticated_calls, agent_after.last_seen_at, agent_after.first_useful_action_at) == lifecycle_before


def test_verified_work_history_outranks_declaration_only_candidate(monkeypatch):
    agent_id, key = _agent()
    _record_action(agent_id, "beta", verified=True)
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(_candidate("alpha"), _candidate("beta")),
    )
    data = _plan(key).json()
    assert data["selected_provider"]["identifier"] == "beta"
    assert data["selected_provider"]["provider_verification_state"] == "historical_callability_verified"
    assert data["selected_provider"]["verified_work_history"]["verified_callability_outcomes"] >= 1
    assert data["truth_boundaries"]["historical_callability_is_not_current_job_completion"] is True


def test_requested_candidate_filters_without_falling_back(monkeypatch):
    _, key = _agent()
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(_candidate("alpha"), _candidate("beta")),
    )
    selected = _plan(key, {"need": "web research", "currency": "USD", "candidate_identifier": "beta"}).json()
    assert selected["selected_provider"]["identifier"] == "beta"
    missing = _plan(key, {"need": "web research", "currency": "USD", "candidate_identifier": "missing"}).json()
    assert missing["state"] == "candidate_not_found"
    assert missing["selected_provider"] is None


def test_ineligible_and_discovery_failure_truth_is_preserved(monkeypatch):
    _, key = _agent()
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("locked", eligible=False)))
    ineligible = _plan(key).json()
    assert ineligible["state"] == "no_eligible_candidate"
    assert ineligible["candidates"][0]["qualification_state"] == "ineligible"
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(status="rate_limited", failure="rate_limited", attempts=0),
    )
    unavailable = _plan(key).json()
    assert unavailable["state"] == "discovery_unavailable"
    assert unavailable["discovery"]["failure_class"] == "rate_limited"
    assert unavailable["selected_provider"] is None


def test_request_validation_rejects_injected_or_noncanonical_economic_material(monkeypatch):
    _, key = _agent()
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("alpha")))
    extra = _plan(key, {"need": "web research", "currency": "USD", "provider_cost": "0"})
    assert extra.status_code == 422
    assert _plan(key, {"need": "web research", "currency": "usd"}).status_code == 422
    assert _plan(key, {"need": "web research", "currency": "USD", "requester_max_price": "01"}).status_code == 422


def test_body_limit_fails_before_route_processing(monkeypatch):
    _, key = _agent()
    calls = []
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: calls.append(1) or _discovery(_candidate("alpha")))
    response = client.post(
        "/commercial/routes/plan",
        headers={"Authorization": "Bearer " + key, "Content-Length": str(commercial_router.MAX_COMMERCIAL_ROUTE_BODY_BYTES + 1)},
        content=b"{}",
    )
    assert response.status_code == 413
    assert calls == []
