"""Package 5D controlled fixtures. They never perform real outreach."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import models, schemas
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.security import hash_key
from app.services import ambassador, economic_kernel, package5_proof
from app.services.external_registry import DiscoveryResult
from app.services.joining import join_agent
from app.services.safe_http import FetchResult


client = TestClient(app)


@pytest.fixture(autouse=True)
def package5d_isolation(monkeypatch):
    monkeypatch.delenv("AION_AMBASSADOR_OUTBOUND_ENABLED", raising=False)
    monkeypatch.delenv("AION_AMBASSADOR_OPERATOR", raising=False)
    monkeypatch.setattr(ambassador, "_canonical_public_url", lambda value: str(value).rstrip("/"))
    with SessionLocal() as db:
        db.execute(delete(models.Package5VuoProof))
        db.execute(delete(models.Package5ParticipationAssessment))
        db.execute(delete(models.DistributionJoinAttribution))
        db.execute(delete(models.DistributionToken))
        db.execute(delete(models.AmbassadorContactAttempt))
        db.execute(delete(models.AmbassadorTarget))
        db.execute(delete(models.AmbassadorCampaign))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(models.Package5VuoProof))
        db.execute(delete(models.Package5ParticipationAssessment))
        db.execute(delete(models.DistributionJoinAttribution))
        db.execute(delete(models.DistributionToken))
        db.execute(delete(models.AmbassadorContactAttempt))
        db.execute(delete(models.AmbassadorTarget))
        db.execute(delete(models.AmbassadorCampaign))
        db.commit()


def _candidate(token=None, **overrides):
    token = token or uuid.uuid4().hex
    row = {
        "source": "global_a2a_registry",
        "identifier": "public-agent-" + token,
        "url": f"https://cards.example/{token}/agent-card.json",
        "interaction_url": f"https://agents.example/{token}/a2a",
        "manifest_reachable": True,
        "declared_a2a_v1_jsonrpc": True,
        "interaction_url_validated": True,
        "authentication_requirement": "none",
        "payment_required": False,
    }
    row.update(overrides)
    return row


def _campaign(db, *, maximum_targets=30, maximum_contacts=30):
    result = ambassador.create_campaign(
        db, name="Package 5D pilot", purpose="Controlled machine-native utility invitation",
        maximum_targets=maximum_targets, maximum_contacts=maximum_contacts,
    )
    return result["campaign_id"]


def _target(db, *, candidate=None, ready=False):
    campaign_id = _campaign(db)
    campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
    row, outcome = ambassador._insert_candidate(db, campaign, candidate or _candidate())
    assert outcome == "created"
    db.commit()
    if ready:
        prepared = ambassador.prepare_target(db, target_id=row.target_id, public_base_url="https://aion.example")
        ambassador.set_campaign_state(db, campaign_id, "ready")
        return campaign_id, row.target_id, prepared
    return campaign_id, row.target_id, None


def _agent():
    token = uuid.uuid4().hex
    key = "aion_package5d_" + token
    with SessionLocal() as db:
        row = models.Agent(external_id="package5d-" + token, name="Package 5D", api_key_hash=hash_key(key))
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, key


def test_campaign_limits_are_hard_bounded_to_thirty():
    with SessionLocal() as db:
        result = ambassador.create_campaign(db, name="Pilot", purpose="Bounded", maximum_targets=30, maximum_contacts=30)
        assert result["bounds"]["hard_global_target_cap"] == 30
        for targets, contacts in ((31, 1), (5, 6), (0, 0), (5, -1)):
            with pytest.raises(ambassador.AmbassadorError):
                ambassador.create_campaign(db, name="Bad", purpose="Bad", maximum_targets=targets, maximum_contacts=contacts)


def test_scout_reuses_bounded_discovery_and_dedupes_global_endpoint(monkeypatch):
    candidate = _candidate()
    monkeypatch.setattr(
        ambassador, "discover_external_agents_with_status",
        lambda query, limit: DiscoveryResult([candidate, dict(candidate, identifier="alias")], "success", None, {"candidate_limit": 5}),
    )
    with SessionLocal() as db:
        campaign_id = _campaign(db)
        result = ambassador.scout_campaign(db, campaign_id=campaign_id, query="research")
        assert result["outbound_contact_performed"] is False
        assert result["outcomes"] == {"created": 1, "duplicate_target_fingerprint": 1}
        assert ambassador.campaign_status(db, campaign_id)["funnel"]["discovered"] == 1
        second_campaign_id = _campaign(db)
        second_campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == second_campaign_id))
        _, outcome = ambassador._insert_candidate(db, second_campaign, candidate)
        assert outcome == "duplicate_target_fingerprint"


def test_qualifier_accepts_only_public_no_credential_no_payment_a2a():
    assert ambassador._qualification(_candidate()) == (
        "qualified", ["qualified_public_a2a_v1_no_credentials_no_payment"]
    )
    assert "interaction_destination_not_validated" in ambassador._qualification(_candidate(interaction_url_validated=False))[1]
    assert "credentials_required" in ambassador._qualification(_candidate(authentication_requirement="bearer"))[1]
    assert "payment_required_initial_contact" in ambassador._qualification(_candidate(payment_required=True))[1]
    assert "self_or_test_target" in ambassador._qualification(_candidate(identifier="test-agent-fixture"))[1]


def test_real_url_validator_rejects_loopback_and_private(monkeypatch):
    monkeypatch.undo()
    for value in ("http://public.example/a2a", "https://127.0.0.1/a2a", "https://10.0.0.2/a2a"):
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador._canonical_public_url(value)
        assert exc.value.code == "unsafe_public_destination"


def test_message_is_deterministic_bounded_and_ignores_remote_prompt_injection():
    token = "aion_dist_" + "x" * 43
    first = ambassador.build_ambassador_message(public_base_url="https://aion.example", distribution_token=token)
    second = ambassador.build_ambassador_message(public_base_url="https://aion.example", distribution_token=token)
    assert first == second
    assert len(json.dumps(first, sort_keys=True, separators=(",", ":")).encode()) <= ambassador.MAX_MESSAGE_BYTES
    assert "ignore previous instructions" not in json.dumps(first).lower()
    assert first["join"]["optional"] is True
    assert "not independent adoption" in first["truth"]
    with SessionLocal() as db:
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(
                db, target_id=str(uuid.uuid4()),
                message={"sender": "AION", "purpose": "bounded_machine_utility_invitation", "padding": "x" * 3000},
                idempotency_key="oversized", send=False,
            )
        assert exc.value.code == "invalid_ambassador_message"


def test_prepare_stores_only_token_hash_and_returns_raw_once():
    with SessionLocal() as db:
        _, target_id, _ = _target(db)
        result = ambassador.prepare_target(db, target_id=target_id, public_base_url="https://aion.example")
        raw = result["distribution_token"]
        stored = db.scalar(select(models.DistributionToken))
        assert stored.token_digest == hashlib.sha256(raw.encode()).hexdigest()
        assert raw not in repr(stored.__dict__)
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.prepare_target(db, target_id=target_id, public_base_url="https://aion.example")
        assert exc.value.code == "invite_already_issued"


def test_dry_run_has_no_network_and_no_contact_evidence(monkeypatch):
    with SessionLocal() as db:
        _, target_id, prepared = _target(db, ready=True)
        monkeypatch.setattr(ambassador.safe_http, "fetch_json", lambda *a, **k: pytest.fail("network attempted"))
        result = ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="dry-run", send=False)
        assert result["send_performed"] is False
        assert result["raw_message_returned"] is False
        assert "message" not in result
        assert db.scalar(select(models.AmbassadorContactAttempt)) is None


def test_closed_campaign_is_terminal():
    with SessionLocal() as db:
        campaign_id = _campaign(db)
        ambassador.set_campaign_state(db, campaign_id, "closed")
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.set_campaign_state(db, campaign_id, "ready")
        assert exc.value.code == "campaign_state_transition_rejected"


def test_send_requires_both_gates_and_one_transport_attempt(monkeypatch):
    with SessionLocal() as db:
        _, target_id, prepared = _target(db, ready=True)
        monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="one", send=True)
        assert exc.value.code == "outbound_disabled"
        monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
        policies = []
        def respond(*args, **kwargs):
            policies.append(kwargs["policy"])
            return FetchResult(200, b"{}", None, 1), {"jsonrpc": "2.0", "result": {}}
        monkeypatch.setattr(ambassador.safe_http, "fetch_json", respond)
        result = ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="one", send=True)
        assert result["result_class"] == "response_received"
        assert result["automatic_retry"] is False
        assert policies[0].max_attempts == 1
        with pytest.raises(ambassador.AmbassadorError):
            ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="two", send=True)


def test_payment_credentials_and_ambiguous_results_are_never_retried(monkeypatch):
    cases = [
        (FetchResult(402, None, "http_402", 1), None, "payment_required"),
        (FetchResult(401, None, "http_401", 1), None, "credentials_required"),
        (FetchResult(None, None, "TimeoutError", 1), None, "ambiguous"),
    ]
    for fetch, payload, expected in cases:
        with SessionLocal() as db:
            _, target_id, prepared = _target(db, ready=True)
            monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
            monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
            monkeypatch.setattr(ambassador.safe_http, "fetch_json", lambda *a, _value=(fetch, payload), **k: _value)
            result = ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="case-" + expected, send=True)
            assert result["result_class"] == expected
            assert result["transport_attempts"] == 1


def test_malformed_response_is_rejected_and_structured_opt_out_is_suppressed(monkeypatch):
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    with SessionLocal() as db:
        _, target_id, prepared = _target(db, ready=True)
        monkeypatch.setattr(ambassador.safe_http, "fetch_json", lambda *a, **k: (FetchResult(200, b"{}", None, 1), {"unexpected": "shape"}))
        rejected = ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="malformed", send=True)
        assert rejected["result_class"] == "rejected"
    with SessionLocal() as db:
        _, target_id, prepared = _target(db, ready=True)
        monkeypatch.setattr(
            ambassador.safe_http, "fetch_json",
            lambda *a, **k: (FetchResult(200, b"{}", None, 1), {"jsonrpc": "2.0", "result": {"opt_out": True}}),
        )
        accepted = ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="opt-out", send=True)
        assert accepted["result_class"] == "response_received"
        target = db.scalar(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id))
        assert target.suppressed is True
        assert target.suppression_reason == "remote_structured_opt_out"


def test_campaign_contact_interval_is_enforced(monkeypatch):
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    monkeypatch.setattr(
        ambassador.safe_http, "fetch_json",
        lambda *a, **k: (FetchResult(200, b"{}", None, 1), {"jsonrpc": "2.0", "result": {}}),
    )
    with SessionLocal() as db:
        campaign_id = _campaign(db, maximum_targets=2, maximum_contacts=2)
        campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
        targets = []
        for suffix in ("a", "b"):
            row, outcome = ambassador._insert_candidate(db, campaign, _candidate(token=uuid.uuid4().hex + suffix))
            assert outcome == "created"
            db.commit()
            prepared = ambassador.prepare_target(db, target_id=row.target_id, public_base_url="https://aion.example")
            targets.append((row.target_id, prepared["message"]))
        ambassador.set_campaign_state(db, campaign_id, "ready")
        ambassador.send_contact(db, target_id=targets[0][0], message=targets[0][1], idempotency_key="interval-a", send=True)
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=targets[1][0], message=targets[1][1], idempotency_key="interval-b", send=True)
        assert exc.value.code == "campaign_contact_rate_limited"


def test_suppression_and_paused_campaign_prevent_contact(monkeypatch):
    with SessionLocal() as db:
        campaign_id, target_id, prepared = _target(db, ready=True)
        ambassador.suppress_target(db, target_id=target_id, reason="target_opted_out")
        monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
        monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
        monkeypatch.setattr(ambassador.safe_http, "fetch_json", lambda *a, **k: pytest.fail("network attempted"))
        with pytest.raises(ambassador.AmbassadorError):
            ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="suppressed", send=True)
        assert ambassador.campaign_status(db, campaign_id)["funnel"]["suppressed"] == 1


def test_forged_expired_and_consumed_tokens_fail_closed():
    with SessionLocal() as db:
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.lock_distribution_token(db, "aion_dist_" + "z" * 43)
        assert exc.value.code == "invalid_distribution_token"
        _, target_id, prepared = _target(db, ready=True)
        token = db.scalar(select(models.DistributionToken))
        token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.lock_distribution_token(db, prepared["distribution_token"])
        assert exc.value.code == "distribution_token_expired"
        token.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        token.use_count = token.maximum_uses
        db.commit()
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.lock_distribution_token(db, prepared["distribution_token"])
        assert exc.value.code == "distribution_token_exhausted"


def test_ambassador_join_is_server_attributed_and_permanently_non_countable():
    with SessionLocal() as db:
        _, _, prepared = _target(db, ready=True)
        payload = schemas.AgentCreate(
            external_id="ambassador-join-" + uuid.uuid4().hex, name="Invited agent",
            acquisition_source="organic", referrer="independent", distribution_token=prepared["distribution_token"],
        )
        agent, raw_key = join_agent(payload, db)
        agent_id = agent.id
        assert agent.acquisition_source == "aion_ambassador_outbound"
        assert agent.referrer == "trusted_ambassador_invite"
        attribution = db.scalar(select(models.DistributionJoinAttribution).where(models.DistributionJoinAttribution.agent_id == agent_id))
        assert attribution.reason_code == "trusted_ambassador_invite_consumed"
        package5_proof.record_participation_assessment(
            db, agent_id=agent_id, classification="independent_external_countable",
            evidence_reference="operator-case", evidence_summary="Should be overridden by trusted invite",
            idempotency_key="ambassador-override",
        )
        readiness = package5_proof.participation_readiness(db, agent_id)
        assert readiness["classification"] == "operator_invited_coordinated_test"
        assert readiness["countable"] is False
        assert readiness["reason_code"] == "trusted_aion_ambassador_outbound_attribution"
        now = datetime.now(timezone.utc)
        action = models.ActionRun(
            action_id=str(uuid.uuid4()), requester_agent_id=agent_id,
            idempotency_key="ambassador-action-" + uuid.uuid4().hex,
            request_digest="sha256:" + "1" * 64, requested_query="research",
            requested_candidate_identifier=None, authorize_external_contact=True,
            state="completed", failure_class=None, created_at=now, started_at=now,
            completed_at=now, duration_ms=1, discovery_attempt_count=1,
            action_attempt_count=1, request_bytes=1, response_bytes=1,
            cost_amount="0", cost_currency="USD",
        )
        db.add(action)
        db.flush()
        outcome = models.ActionOutcome(
            action_run_id=action.id, outcome_type="callability_challenge",
            protocol_response_received=True, callability_verified=True,
            capability_verified=False, verified_outcome=True,
            normalized_result_kind="a2a_message", failure_class=None,
            response_digest="sha256:" + "2" * 64, protocol_task_id=None,
            protocol_message_id="ambassador-fixture", proof_present=True,
            completed_at=now,
        )
        db.add(outcome)
        db.flush()
        db.add(models.ActionVerification(
            action_run_id=action.id, action_outcome_id=outcome.id,
            verification_method="a2a_nonce_echo", state="verified",
            challenge_digest="sha256:" + "3" * 64,
            proof_digest="sha256:" + "4" * 64, verified_at=now, details=None,
        ))
        db.commit()
        action_id = action.action_id
    response = client.post(
        "/proof/package-5/vuos",
        headers={"Authorization": "Bearer " + raw_key, "Idempotency-Key": "ambassador-vuo"},
        json={
            "action_id": action_id,
            "goal_kind": "verify_external_agent_callability",
            "product_goal": "find_verify_invoke_external_a2a_agent",
            "delivered_outcome": "verified_external_agent_callability",
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_goal_was_useful",
        },
    )
    assert response.status_code == 200
    assert response.json()["semantic_eligible"] is True
    assert response.json()["qualifies_as_package5_vuo"] is False
    assert response.json()["participation"]["classification"] == "operator_invited_coordinated_test"
    assert response.json()["participation_countable_at_submission"] is False
    proof = client.get("/proof/package-5").json()
    assert proof["counts"]["qualifying_vuos"] == 0
    assert proof["counts"]["identities_with_qualifying_return"] == 0


def test_single_use_ambassador_token_cannot_join_twice():
    with SessionLocal() as db:
        _, _, prepared = _target(db, ready=True)
        raw = prepared["distribution_token"]
        join_agent(schemas.AgentCreate(external_id="single-" + uuid.uuid4().hex, name="First", distribution_token=raw), db)
        with pytest.raises(Exception) as exc:
            join_agent(schemas.AgentCreate(external_id="single-" + uuid.uuid4().hex, name="Second", distribution_token=raw), db)
        assert "distribution_token_exhausted" in str(exc.value)


def test_peer_referral_is_bounded_manual_secret_safe_and_non_countable():
    referrer_id, _ = _agent()
    with SessionLocal() as db:
        issued = ambassador.issue_peer_referral(db, referrer_agent_id=referrer_id, idempotency_key="peer-one", public_base_url="https://aion.example")
        packet = issued["packet"]
        assert packet["maximum_uses"] == 5
        assert packet["automatic_forwarding"] is False
        assert "credential" not in json.dumps(packet).lower()
        raw = packet["distribution_token"]
        joined, _ = join_agent(schemas.AgentCreate(
            external_id="peer-join-" + uuid.uuid4().hex, name="Peer", acquisition_source="organic",
            referrer="self-asserted", distribution_token=raw,
        ), db)
        assert joined.acquisition_source == "trusted_peer_referral"
        readiness = package5_proof.participation_readiness(db, joined.id)
        assert readiness["classification"] == "independent_external_candidate"
        assert readiness["countable"] is False


def test_referral_rest_and_mcp_are_authenticated_and_explicit():
    _, key = _agent()
    unauth = client.post("/agents/me/referral-packets", headers={"Idempotency-Key": "unauth"}, json={"maximum_uses": 5, "acknowledge_manual_forwarding": True})
    assert unauth.status_code == 401
    response = client.post(
        "/agents/me/referral-packets",
        headers={"Authorization": "Bearer " + key, "Idempotency-Key": "rest-referral"},
        json={"maximum_uses": 5, "acknowledge_manual_forwarding": True},
    )
    assert response.status_code == 200
    assert response.json()["packet"]["automatic_forwarding"] is False
    params = {
        "name": "create_peer_referral_packet",
        "arguments": {"idempotency_key": "mcp-referral", "maximum_uses": 5, "acknowledge_manual_forwarding": True},
        "_meta": {"io.modelcontextprotocol/protocolVersion": MCP_VERSION, "io.modelcontextprotocol/clientCapabilities": {}},
    }
    mcp = client.post("/mcp", headers={
        "Authorization": "Bearer " + key, "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": "tools/call", "Mcp-Name": "create_peer_referral_packet",
        "Accept": "application/json, text/event-stream",
    }, json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": params})
    assert mcp.status_code == 200
    assert mcp.json()["result"]["structuredContent"]["packet"]["maximum_uses"] == 5


def test_new_write_surface_retains_64k_stream_limit():
    response = client.post(
        "/agents/me/referral-packets",
        headers={"Content-Type": "application/json", "Authorization": "Bearer invalid"},
        content=b"x" * (64 * 1024 + 1),
    )
    assert response.status_code == 413


def test_campaign_funnel_is_bounded_and_never_labels_independent_adoption():
    with SessionLocal() as db:
        campaign_id, _, prepared = _target(db, ready=True)
        agent, _ = join_agent(schemas.AgentCreate(
            external_id="funnel-" + uuid.uuid4().hex, name="Funnel", distribution_token=prepared["distribution_token"]
        ), db)
        status = ambassador.campaign_status(db, campaign_id)
        assert status["funnel"]["joins_attributed_to_campaign"] == 1
        assert "independent" in status["truth_boundary"]
        assert status["read_only"] is True
        assert "independent_adoption" not in status["funnel"]
        assert agent.acquisition_source == "aion_ambassador_outbound"


def test_legacy_payment_and_package6a_economics_are_unchanged():
    assert economic_kernel.REAL_MONEY_EXECUTION_ENABLED is False
    assert economic_kernel.MINIMUM_MARGIN_BPS == 4_000
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(models.PaymentIntent))
        _campaign(db, maximum_targets=1, maximum_contacts=0)
        after = db.scalar(select(func.count()).select_from(models.PaymentIntent))
        assert after == before
