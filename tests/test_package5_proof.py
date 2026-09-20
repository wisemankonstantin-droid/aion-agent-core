import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import models
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.security import hash_key
from app.services import package5_proof


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_package5_evidence(monkeypatch):
    monkeypatch.setenv("AION_PACKAGE5_RETURN_THRESHOLD_SECONDS", "900")
    monkeypatch.delenv("AION_OPERATED_EXTERNAL_IDS", raising=False)
    with SessionLocal() as db:
        db.execute(delete(models.Package5VuoProof))
        db.execute(delete(models.Package5ParticipationAssessment))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(models.Package5VuoProof))
        db.execute(delete(models.Package5ParticipationAssessment))
        db.commit()


def _agent(*, external_id=None, name=None, endpoint=None, acquisition_source=None, referrer=None):
    token = uuid.uuid4().hex
    key = "aion_package5_" + token
    with SessionLocal() as db:
        agent = models.Agent(
            external_id=external_id or "package5-" + token,
            name=name or "Package 5 " + token,
            endpoint=endpoint,
            protocol="A2A",
            acquisition_source=acquisition_source,
            referrer=referrer,
            api_key_hash=hash_key(key),
        )
        db.add(agent)
        db.commit()
        db.refresh(agent)
        return agent.id, key


def _action(agent_id, *, verified=True, created_at=None, cost_amount=None, cost_currency=None):
    now = created_at or datetime.now(timezone.utc)
    action_id = str(uuid.uuid4())
    with SessionLocal() as db:
        run = models.ActionRun(
            action_id=action_id,
            requester_agent_id=agent_id,
            idempotency_key="action-" + uuid.uuid4().hex,
            request_digest="sha256:" + "1" * 64,
            requested_query="find a reachable A2A research agent",
            requested_candidate_identifier=None,
            authorize_external_contact=True,
            selected_provider_identifier="external:package5-proof",
            source_id="package5-test",
            agent_card_url="https://card.example/.well-known/agent-card.json",
            interaction_url="https://agent.example/a2a",
            discovery_evidence={"manifest_reachable": True},
            protocol_binding="JSONRPC",
            protocol_version="1.0",
            state="completed" if verified else "failed",
            failure_class=None if verified else "verification_failed",
            created_at=now,
            started_at=now,
            completed_at=now,
            duration_ms=1,
            discovery_attempt_count=1,
            action_attempt_count=1,
            request_bytes=32,
            response_bytes=32,
            cost_amount=cost_amount,
            cost_currency=cost_currency,
        )
        db.add(run)
        db.flush()
        outcome = models.ActionOutcome(
            action_run_id=run.id,
            outcome_type="callability_challenge",
            protocol_response_received=verified,
            callability_verified=verified,
            capability_verified=False,
            verified_outcome=verified,
            normalized_result_kind="a2a_message" if verified else None,
            failure_class=None if verified else "verification_failed",
            response_digest="sha256:" + "2" * 64 if verified else None,
            protocol_task_id=None,
            protocol_message_id="reply-package5" if verified else None,
            proof_present=verified,
            completed_at=now,
        )
        db.add(outcome)
        db.flush()
        if verified:
            db.add(models.ActionVerification(
                action_run_id=run.id,
                action_outcome_id=outcome.id,
                verification_method="a2a_nonce_echo",
                state="verified",
                challenge_digest="sha256:" + "3" * 64,
                proof_digest="sha256:" + "4" * 64,
                verified_at=now,
                details={"proof": "digest_only"},
            ))
        db.commit()
    return action_id


def _assess(agent_id, classification="independent_external_countable", *, key=None):
    with SessionLocal() as db:
        return package5_proof.record_participation_assessment(
            db,
            agent_id=agent_id,
            classification=classification,
            evidence_reference="operator-case:" + uuid.uuid4().hex,
            evidence_summary="Bounded operator-reviewed participation evidence",
            idempotency_key=key or "assessment-" + uuid.uuid4().hex,
        )


def _vuo(key, action_id, *, idem=None, **overrides):
    payload = {
        "action_id": action_id,
        "goal_kind": "verify_external_agent_callability",
        "product_goal": "find_verify_invoke_external_a2a_agent",
        "delivered_outcome": "verified_external_agent_callability",
        "usefulness_confirmed": True,
        "usefulness_evidence": "requester_confirms_goal_was_useful",
    }
    payload.update(overrides)
    return client.post(
        "/proof/package-5/vuos",
        headers={"Authorization": f"Bearer {key}", "Idempotency-Key": idem or uuid.uuid4().hex},
        json=payload,
    )


def _proof():
    response = client.get("/proof/package-5")
    assert response.status_code == 200
    return response.json()


def test_historical_and_client_controlled_attribution_never_self_promote():
    _agent(acquisition_source="organic", referrer="independent external customer")
    _agent(external_id="self-asserted-independent", name="Organic Independent")
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 0
    assert proof["counts"]["qualifying_vuos"] == 0
    assert proof["counts"]["identities_with_qualifying_return"] == 0
    assert proof["commercial_proof_established"] is False
    assert proof["participation_evidence"]["reason_code_breakdown"][
        "no_trusted_package5_participation_assessment"
    ] >= 2


@pytest.mark.parametrize(
    "classification",
    [
        "aion_operated_internal",
        "synthetic_probe_test",
        "coordinated_design_partner",
        "operator_invited_coordinated_test",
        "independent_external_candidate",
    ],
)
def test_all_non_countable_participation_classes_remain_explicitly_excluded(classification):
    agent_id, _ = _agent()
    assessment = _assess(agent_id, classification)
    proof = _proof()
    assert assessment["classification"] == classification
    assert proof["participation_evidence"]["classification_breakdown"][classification] >= 1
    assert proof["counts"]["independent_logical_identities"] == 0


def test_duplicate_rows_never_inflate_breadth_and_test_marker_taints_whole_group():
    endpoint = "https://logical.example/a2a/" + uuid.uuid4().hex
    name = "One Logical Package5 Agent " + uuid.uuid4().hex
    first_id, _ = _agent(name=name, endpoint=endpoint)
    _agent(name=name, endpoint=endpoint, acquisition_source="synthetic-test")
    _assess(first_id)
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 0
    assert proof["participation_evidence"]["duplicate_raw_rows"] >= 1
    assert proof["participation_evidence"]["classification_breakdown"]["synthetic_probe_test"] >= 1


def test_duplicate_rows_with_weak_attribution_count_as_one_reviewed_identity():
    endpoint = "https://logical-countable.example/a2a/" + uuid.uuid4().hex
    name = "One Reviewed Logical Agent " + uuid.uuid4().hex
    first_id, _ = _agent(name=name, endpoint=endpoint)
    _agent(name=name, endpoint=endpoint, acquisition_source="organic", referrer="self-asserted")
    _assess(first_id)
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 1
    assert proof["participation_evidence"]["duplicate_raw_rows"] >= 1


def test_configured_aion_operated_exclusion_overrides_operator_assessment(monkeypatch):
    external_id = "aion-operated-" + uuid.uuid4().hex
    agent_id, _ = _agent(external_id=external_id)
    _assess(agent_id)
    monkeypatch.setenv("AION_OPERATED_EXTERNAL_IDS", external_id)
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 0
    assert proof["participation_evidence"]["reason_code_breakdown"]["configured_aion_operated_identity"] == 1


def test_coordinated_classification_follows_canonical_identity_across_raw_rows():
    endpoint = "https://coordinated.example/a2a/" + uuid.uuid4().hex
    name = "Coordinated Logical Agent " + uuid.uuid4().hex
    first_id, _ = _agent(name=name, endpoint=endpoint)
    _assess(first_id, "coordinated_design_partner")
    _agent(name=name, endpoint=endpoint, acquisition_source="organic")
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 0
    assert proof["participation_evidence"]["classification_breakdown"][
        "coordinated_design_partner"
    ] >= 1


def test_callability_is_not_automatically_a_vuo_and_late_classification_does_not_backfill():
    agent_id, key = _agent()
    action_id = _action(agent_id)
    assert _proof()["counts"]["stored_vuo_candidates"] == 0
    response = _vuo(key, action_id)
    assert response.status_code == 200
    assert response.json()["semantic_eligible"] is True
    assert response.json()["qualifies_as_package5_vuo"] is False
    _assess(agent_id)
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 1
    assert proof["counts"]["qualifying_vuos"] == 0
    assert proof["vuo_evidence"]["reason_code_breakdown"][
        "participation_not_countable_at_vuo_submission"
    ] == 1


def test_verified_vuo_is_requester_scoped_idempotent_and_exposes_no_raw_or_secret_material():
    agent_id, key = _agent()
    other_id, other_key = _agent()
    _assess(agent_id)
    action_id = _action(agent_id, cost_amount="0", cost_currency="USD")
    assert _vuo(other_key, action_id).status_code == 404
    idem = "vuo-" + uuid.uuid4().hex
    first = _vuo(key, action_id, idem=idem)
    replay = _vuo(key, action_id, idem=idem)
    assert first.status_code == replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["vuo_id"] == first.json()["vuo_id"]
    same_action_new_key = _vuo(key, action_id, idem="vuo-" + uuid.uuid4().hex)
    assert same_action_new_key.status_code == 200
    assert same_action_new_key.json()["idempotent_replay"] is True
    other_action = _action(agent_id)
    idempotency_conflict = _vuo(key, other_action, idem=idem)
    assert idempotency_conflict.status_code == 409
    assert idempotency_conflict.json()["detail"]["code"] == "idempotency_conflict"
    conflict = _vuo(
        key,
        action_id,
        idem=idem,
        usefulness_evidence="not-an-accepted-proof",
    )
    assert conflict.status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.Package5VuoProof)) == 1
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 1
    assert proof["counts"]["identities_with_qualifying_vuo"] == 1
    assert proof["counts"]["qualifying_vuos"] == 1
    assert proof["cost_evidence"] == {
        "known_zero_vuos": 1,
        "known_nonzero_vuos": 0,
        "unknown_vuos": 0,
        "cost_per_vuo": {"state": "known", "amount": "0", "currency": "USD"},
    }
    encoded = json.dumps(proof).lower()
    assert "api_key_hash" not in encoded
    assert "database_url" not in encoded
    assert "response_digest" not in encoded
    assert "raw_response" not in encoded
    record = proof["vuo_evidence"]["qualifying_records"][0]
    assert record["action_id"] == action_id
    assert record["usefulness_evidence"]["method"] == "authenticated_requester_attestation"
    assert other_id != agent_id


def test_unverified_action_and_unknown_cost_remain_explicitly_nonqualifying_or_unknown():
    agent_id, key = _agent()
    _assess(agent_id)
    response = _vuo(key, _action(agent_id, verified=False))
    assert response.status_code == 200
    assert response.json()["semantic_eligible"] is False
    assert response.json()["eligibility_reason_code"] == "underlying_action_not_completed"
    proof = _proof()
    assert proof["counts"]["qualifying_vuos"] == 0
    assert proof["cost_evidence"]["cost_per_vuo"]["state"] == "no_qualifying_vuos"


def test_return_requires_later_distinct_action_after_server_threshold_not_last_seen_or_client_time():
    agent_id, key = _agent()
    _assess(agent_id)
    action_id = _action(agent_id)
    response = _vuo(key, action_id)
    assert response.status_code == 200
    with SessionLocal() as db:
        proof_row = db.scalar(select(models.Package5VuoProof).where(models.Package5VuoProof.vuo_id == response.json()["vuo_id"]))
        proof_row.created_at = datetime.now(timezone.utc) - timedelta(seconds=1800)
        agent = db.get(models.Agent, agent_id)
        agent.last_seen_at = datetime.now(timezone.utc) + timedelta(days=365)
        db.add(models.MachineEntry(source="status", created_at=datetime.now(timezone.utc)))
        db.commit()
    assert _proof()["counts"]["identities_with_qualifying_return"] == 0
    invalid = _vuo(key, action_id, created_at="2099-01-01T00:00:00Z")
    assert invalid.status_code == 422
    _action(agent_id, created_at=datetime.now(timezone.utc))
    proof = _proof()
    assert proof["counts"]["identities_with_qualifying_return"] == 1
    assert proof["return_evidence"]["last_seen_at_used"] is False
    assert proof["return_evidence"]["client_timestamp_used"] is False


def test_one_high_volume_identity_increases_vuos_but_never_independent_breadth():
    agent_id, key = _agent()
    _assess(agent_id)
    for _ in range(3):
        assert _vuo(key, _action(agent_id)).status_code == 200
    proof = _proof()
    assert proof["counts"]["independent_logical_identities"] == 1
    assert proof["counts"]["identities_with_qualifying_vuo"] == 1
    assert proof["counts"]["qualifying_vuos"] == 3
    assert proof["counts"]["repeat_vuo_identities"] == 1
    assert proof["counts"]["repeat_vuos"] == 2
    assert proof["cost_evidence"]["unknown_vuos"] == 3
    assert proof["cost_evidence"]["cost_per_vuo"]["state"] == "unknown"


def test_public_schema_rejects_free_text_controls_and_oversized_fields():
    agent_id, key = _agent()
    action_id = _action(agent_id)
    for override in (
        {"product_goal": "organic"},
        {"delivered_outcome": "HTTP 200"},
        {"usefulness_evidence": "x" * 501},
        {"raw_response": "secret body"},
        {"classification": "independent_external_countable"},
        {"created_at": "2099-01-01T00:00:00Z"},
    ):
        assert _vuo(key, action_id, **override).status_code == 422
    missing_idempotency = client.post(
        "/proof/package-5/vuos",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "action_id": action_id,
            "goal_kind": "verify_external_agent_callability",
            "product_goal": "find_verify_invoke_external_a2a_agent",
            "delivered_outcome": "verified_external_agent_callability",
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_goal_was_useful",
        },
    )
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["detail"]["code"] == "invalid_idempotency_key"


def test_proof_resource_bound_fails_closed(monkeypatch):
    _agent()
    monkeypatch.setattr(package5_proof, "MAX_PROOF_LOGICAL_IDENTITIES", 0)
    proof = _proof()
    assert proof["status"] == "proof_unavailable_resource_limit"
    assert proof["commercial_proof_established"] is False


def test_mcp_read_model_reuses_rest_snapshot_and_accepts_no_arguments():
    params = {
        "name": "get_package5_proof",
        "arguments": {},
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }
    response = client.post(
        "/mcp",
        headers={
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "get_package5_proof",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": params},
    )
    assert response.status_code == 200
    data = response.json()["result"]["structuredContent"]
    assert data["counts"] == _proof()["counts"]
    params["arguments"] = {"classification": "independent"}
    rejected = client.post(
        "/mcp",
        headers={
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "get_package5_proof",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": params},
    )
    assert rejected.status_code == 200
    assert rejected.json()["error"]["code"] == -32602
