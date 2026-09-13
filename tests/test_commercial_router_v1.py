from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models
from app.conversation_models import ConversationEvidence, ConversationIntelligence
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


def _record_action(
    agent_id: int,
    identifier: str,
    *,
    verified: bool,
    failure_class: str | None = None,
    verification: bool = True,
):
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
        outcome = models.ActionOutcome(
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
        db.add(outcome)
        db.flush()
        if verification:
            db.add(models.ActionVerification(
                action_run_id=run.id, action_outcome_id=outcome.id,
                verification_method="a2a_nonce_roundtrip_v1",
                state="verified" if verified else "failed",
                challenge_digest="sha256:" + "c" * 64,
                proof_digest="sha256:" + "d" * 64 if verified else None,
                verified_at=now,
                details={"proof_present": verified},
            ))
        db.commit()


def test_route_plan_requires_authentication(monkeypatch):
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("alpha")))
    response = client.post("/commercial/routes/plan", json={"need": "web research", "currency": "USD"})
    assert response.status_code in {401, 403}
    assert _plan("invalid-key").status_code == 401
    malformed = client.post(
        "/commercial/routes/plan",
        headers={"Authorization": "Basic not-a-bearer"},
        json={"need": "web research", "currency": "USD"},
    )
    assert malformed.status_code == 401


def test_route_plan_is_fail_closed_unpriced_and_side_effect_free(monkeypatch):
    agent_id, key = _agent()
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("alpha", registry_verified=True)))
    with SessionLocal() as db:
        protected_models = (
            models.EconomicOperation, models.EconomicTransition, models.PaymentIntent,
            models.ActionRun, models.ActionAttempt, models.ActionOutcome,
            models.Package5VuoProof, models.Interaction, models.Need, models.Offer,
            models.Agent, models.AmbassadorTarget, models.AmbassadorContactAttempt,
            ConversationEvidence, ConversationIntelligence,
        )
        counts_before = {
            model: db.scalar(select(func.count()).select_from(model)) or 0
            for model in protected_models
        }
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
        assert {
            model: db.scalar(select(func.count()).select_from(model)) or 0
            for model in protected_models
        } == counts_before
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
    assert data["next_actions"][0]["required_before_current-job_execution"] is True


def test_verified_history_does_not_cross_endpoint_or_protocol_identity(monkeypatch):
    agent_id, key = _agent()
    identifier = "drift-" + uuid.uuid4().hex
    _record_action(agent_id, identifier, verified=True)

    changed_endpoint = _candidate(identifier)
    changed_endpoint["interaction_url"] = f"https://new-{identifier}.example/a2a"
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(changed_endpoint))
    endpoint_plan = _plan(key).json()
    assert endpoint_plan["selected_provider"]["provider_verification_state"] == "declaration_qualified_only"
    assert endpoint_plan["selected_provider"]["verified_work_history"]["verified_callability_outcomes"] == 0

    changed_protocol = _candidate(identifier)
    changed_protocol["protocol_version"] = "1.1"
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(changed_protocol))
    protocol_plan = _plan(key).json()
    assert protocol_plan["selected_provider"] is None
    assert protocol_plan["candidates"][0]["qualification_state"] == "ineligible"


def test_unverified_outcome_flags_cannot_manufacture_verified_history(monkeypatch):
    agent_id, key = _agent()
    _record_action(agent_id, "forged", verified=True, verification=False)
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("forged")))
    selected = _plan(key).json()["selected_provider"]
    assert selected["provider_verification_state"] == "declaration_qualified_only"
    assert selected["verified_work_history"]["recorded_outcomes"] == 1
    assert selected["verified_work_history"]["verified_callability_outcomes"] == 0


def test_ranking_penalizes_failures_and_has_stable_tie_break(monkeypatch):
    agent_id, key = _agent()
    prefix = uuid.uuid4().hex
    alpha, beta, gamma = (f"{prefix}-{name}" for name in ("alpha", "beta", "gamma"))
    for identifier in (alpha, beta, gamma):
        _record_action(agent_id, identifier, verified=True)
    _record_action(agent_id, beta, verified=False, failure_class="timeout")
    monkeypatch.setattr(
        commercial_router, "_DISCOVER",
        lambda *_: _discovery(_candidate(gamma), _candidate(beta), _candidate(alpha)),
    )
    data = _plan(key).json()
    assert data["selected_provider"]["identifier"] == alpha
    assert [item["identifier"] for item in sorted(data["candidates"], key=commercial_router._ranking_key)] == [alpha, gamma, beta]


def test_currently_ineligible_candidate_cannot_win_with_verified_history(monkeypatch):
    agent_id, key = _agent()
    _record_action(agent_id, "historical", verified=True)
    monkeypatch.setattr(
        commercial_router, "_DISCOVER",
        lambda *_: _discovery(_candidate("historical", eligible=False), _candidate("current")),
    )
    assert _plan(key).json()["selected_provider"]["identifier"] == "current"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manifest_reachable", False), ("card_parseable", False),
        ("declared_a2a_v1_jsonrpc", False), ("interaction_url_validated", False),
        ("authentication_requirement", "credentials_required"),
        ("interaction_url", None), ("identifier", None),
    ],
)
def test_each_candidate_qualification_predicate_fails_closed(monkeypatch, field, value):
    _, key = _agent()
    candidate = _candidate("candidate")
    candidate[field] = value
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(candidate))
    data = _plan(key).json()
    assert data["state"] == "no_eligible_candidate"
    assert data["selected_provider"] is None
    assert data["candidates"][0]["qualification_state"] == "ineligible"


def test_overlong_remote_identifier_cannot_alias_verified_history(monkeypatch):
    agent_id, key = _agent()
    valid = "a" * 240
    _record_action(agent_id, valid, verified=True)
    candidate = _candidate(valid + "attacker-suffix")
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(candidate))
    data = _plan(key).json()
    assert data["state"] == "no_eligible_candidate"
    assert data["selected_provider"] is None
    assert data["candidates"][0]["identifier"] is None


def test_remote_candidate_output_redacts_secrets_and_unsafe_url_cannot_qualify(monkeypatch):
    _, key = _agent()
    secret = "remote-secret-1234567890123456789012345678901234567890"
    candidate = _candidate("malicious")
    candidate["name"] = "Bearer " + secret
    candidate["description"] = "api_key=" + secret + " useful discovery provider"
    candidate["url"] += "?token=" + secret
    userinfo = "account" + ":" + "opaque-value"
    candidate["interaction_url"] = f"https://{userinfo}@malicious.example/a2a?token=" + secret
    candidate["interaction_url_validated"] = True
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(candidate))
    data = _plan(key).json()
    serialized = str(data)
    assert secret not in serialized
    assert data["selected_provider"] is None
    assert data["candidates"][0]["qualification_state"] == "ineligible"
    assert "?" not in data["candidates"][0]["agent_card_url"]


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
    requested = _plan(key, {"need": "web research", "currency": "USD", "candidate_identifier": "locked"}).json()
    assert requested["state"] == "candidate_ineligible"
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(status="rate_limited", failure="rate_limited", attempts=0),
    )
    unavailable = _plan(key).json()
    assert unavailable["state"] == "discovery_unavailable"
    assert unavailable["discovery"]["failure_class"] == "rate_limited"
    assert unavailable["selected_provider"] is None
    monkeypatch.setattr(
        commercial_router,
        "_DISCOVER",
        lambda *_: _discovery(_candidate("timed-out", eligible=False), status="endpoint_unreachable", failure="endpoint_unreachable"),
    )
    bounded_failure = _plan(key).json()
    assert bounded_failure["state"] == "discovery_unavailable"
    assert bounded_failure["selected_provider"] is None


def test_request_validation_rejects_injected_or_noncanonical_economic_material(monkeypatch):
    _, key = _agent()
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("alpha")))
    extra = _plan(key, {"need": "web research", "currency": "USD", "provider_cost": "0"})
    assert extra.status_code == 422
    assert _plan(key, {"need": "web research", "currency": "usd"}).status_code == 422
    assert _plan(key, {"need": "web research", "currency": "USD", "requester_max_price": "01"}).status_code == 422
    for bad_need in ("", "   ", "x" * 129, "line\nbreak"):
        assert _plan(key, {"need": bad_need, "currency": "USD"}).status_code == 422
    assert _plan(key, {"need": "research", "currency": "USD", "candidate_identifier": "x" * 241}).status_code == 422
    for bad_money in ("-1", "NaN", "Infinity", "9999999999999999999", "1e9"):
        assert _plan(key, {"need": "research", "currency": "USD", "requester_max_price": bad_money}).status_code == 422
    unicode_response = _plan(key, {"need": "研究" * 64, "currency": "USD"})
    assert unicode_response.status_code == 200


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


def _body_limit_request(chunks, content_lengths=()):
    messages = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    received = 0
    downstream = None
    status = None

    async def receive():
        nonlocal received
        message = messages[received]
        received += 1
        return message

    async def app(scope, bounded_receive, send):
        nonlocal downstream
        parts = []
        while True:
            message = await bounded_receive()
            parts.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        downstream = b"".join(parts)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        nonlocal status
        if message["type"] == "http.response.start":
            status = message["status"]

    scope = {
        "type": "http", "method": "POST", "path": "/commercial/routes/plan",
        "headers": [(b"content-length", value.encode("ascii")) for value in content_lengths],
    }
    asyncio.run(commercial_router._CommercialRouteBodyLimit(app)(scope, receive, send))
    return status, received, downstream


def test_stream_body_limit_handles_declared_malformed_exact_and_oversized():
    limit = commercial_router.MAX_COMMERCIAL_ROUTE_BODY_BYTES
    assert _body_limit_request([b"unread"], (str(limit + 1),)) == (413, 0, None)
    assert _body_limit_request([b"unread"], ("invalid",)) == (400, 0, None)
    assert _body_limit_request([b"unread"], ("1", "1")) == (400, 0, None)
    exact = b"x" * limit
    assert _body_limit_request([exact], (str(limit),)) == (204, 1, exact)
    chunks = [b"a" * (limit // 2), b"b" * (limit // 2), b"c", b"unread"]
    assert _body_limit_request(chunks) == (413, 3, None)


def test_repeated_plans_never_invoke_or_persist_execution(monkeypatch):
    _, key = _agent()
    calls = []
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: calls.append("discovery") or _discovery(_candidate("alpha")))
    first = _plan(key)
    second = _plan(key)
    assert first.status_code == second.status_code == 200
    assert calls == ["discovery", "discovery"]
    for response in (first.json(), second.json()):
        assert response["execution"] == {
            "mode": "planning_only",
            "external_discovery_performed": True,
            "registry_or_manifest_discovery_contact_may_have_occurred": True,
            "provider_interaction_endpoint_contacted": False,
            "provider_execution_started": False,
            "payment_rail_contacted": False,
            "economic_operation_created": False,
            "real_money_execution_enabled": False,
        }


def test_concurrent_identical_plans_are_read_only(monkeypatch):
    _, key = _agent()
    monkeypatch.setattr(commercial_router, "_DISCOVER", lambda *_: _discovery(_candidate("concurrent"), attempts=0))
    with SessionLocal() as db:
        before = (
            db.scalar(select(func.count()).select_from(models.EconomicOperation)) or 0,
            db.scalar(select(func.count()).select_from(models.PaymentIntent)) or 0,
            db.scalar(select(func.count()).select_from(models.ActionRun)) or 0,
        )
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: _plan(key), range(8)))
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["state"] == "qualified_unpriced" for response in responses)
    with SessionLocal() as db:
        after = (
            db.scalar(select(func.count()).select_from(models.EconomicOperation)) or 0,
            db.scalar(select(func.count()).select_from(models.PaymentIntent)) or 0,
            db.scalar(select(func.count()).select_from(models.ActionRun)) or 0,
        )
    assert after == before
