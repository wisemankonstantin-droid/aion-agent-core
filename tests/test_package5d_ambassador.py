"""Package 5D controlled fixtures. They never perform real outreach."""

from datetime import datetime, timedelta, timezone
import copy
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


def _verified_action(agent_id: int, *, created_at: datetime) -> str:
    action_id = str(uuid.uuid4())
    with SessionLocal() as db:
        run = models.ActionRun(
            action_id=action_id, requester_agent_id=agent_id,
            idempotency_key="package5d-action-" + uuid.uuid4().hex,
            request_digest="sha256:" + "5" * 64,
            requested_query="bounded campaign return fixture",
            requested_candidate_identifier=None, authorize_external_contact=True,
            selected_provider_identifier="external:package5d-return",
            source_id="package5d-test", agent_card_url="https://card.example/agent-card.json",
            interaction_url="https://agent.example/a2a", discovery_evidence={"manifest_reachable": True},
            protocol_binding="JSONRPC", protocol_version="1.0", state="completed",
            failure_class=None, created_at=created_at, started_at=created_at,
            completed_at=created_at, duration_ms=1, discovery_attempt_count=1,
            action_attempt_count=1, request_bytes=1, response_bytes=1,
            cost_amount="0", cost_currency="USD",
        )
        db.add(run)
        db.flush()
        outcome = models.ActionOutcome(
            action_run_id=run.id, outcome_type="callability_challenge",
            protocol_response_received=True, callability_verified=True,
            capability_verified=False, verified_outcome=True,
            normalized_result_kind="a2a_message", failure_class=None,
            response_digest="sha256:" + "6" * 64, protocol_task_id=None,
            protocol_message_id="package5d-return", proof_present=True,
            completed_at=created_at,
        )
        db.add(outcome)
        db.flush()
        db.add(models.ActionVerification(
            action_run_id=run.id, action_outcome_id=outcome.id,
            verification_method="a2a_nonce_echo", state="verified",
            challenge_digest="sha256:" + "7" * 64,
            proof_digest="sha256:" + "8" * 64,
            verified_at=created_at, details=None,
        ))
        db.commit()
    return action_id


def _submit_vuo(key: str, action_id: str):
    return client.post(
        "/proof/package-5/vuos",
        headers={"Authorization": "Bearer " + key, "Idempotency-Key": uuid.uuid4().hex},
        json={
            "action_id": action_id,
            "goal_kind": "verify_external_agent_callability",
            "product_goal": "find_verify_invoke_external_a2a_agent",
            "delivered_outcome": "verified_external_agent_callability",
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_goal_was_useful",
        },
    )


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


def test_url_canonicalization_preserves_safe_ports_and_endpoint_identity(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(
        ambassador.safe_http._socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [(2, 1, 6, "", ("93.184.216.34", port))],
    )
    assert ambassador._canonical_public_url("https://EXAMPLE.com:8443/a2a/") == "https://example.com:8443/a2a"
    assert ambassador._canonical_public_url("https://EXAMPLE.com/a2a/") == "https://example.com/a2a"
    assert ambassador._canonical_public_url("https://example.com:443/a2a") == "https://example.com/a2a"
    assert ambassador._canonical_public_url("https://[2606:2800:220:1:248:1893:25c8:1946]:8443/a2a") == "https://[2606:2800:220:1:248:1893:25c8:1946]:8443/a2a"
    assert ambassador._target_fingerprint("https://example.com:8443/a2a") != ambassador._target_fingerprint("https://example.com/a2a")
    with SessionLocal() as db:
        campaign_id = _campaign(db, maximum_targets=2, maximum_contacts=0)
        campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
        _, standard = ambassador._insert_candidate(
            db, campaign, _candidate(identifier="standard-port", interaction_url="https://example.com/a2a")
        )
        _, explicit = ambassador._insert_candidate(
            db, campaign, _candidate(identifier="explicit-port", interaction_url="https://example.com:8443/a2a")
        )
        db.commit()
        assert (standard, explicit) == ("created", "created")
    with pytest.raises(ambassador.AmbassadorError):
        ambassador._canonical_public_url("https://example.com:99999/a2a")


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
        target = db.scalar(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id))
        assert target.prepared_message_digest == ambassador._digest_json(result["message"])
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
        replay = ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="one", send=True)
        assert replay["idempotent_replay"] is True
        assert replay["send_performed"] is False
        assert replay["contact_id"] == result["contact_id"]
        assert len(policies) == 1
        with pytest.raises(ambassador.AmbassadorError):
            ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="two", send=True)


def test_send_rejects_any_tampered_or_cross_target_prepared_message(monkeypatch):
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    monkeypatch.setattr(ambassador.safe_http, "fetch_json", lambda *a, **k: pytest.fail("invalid message reached network"))
    with SessionLocal() as db:
        _, target_a, prepared_a = _target(db, ready=True)
        _, target_b, prepared_b = _target(db, ready=True)

        tampered = copy.deepcopy(prepared_a["message"])
        tampered["utility"] = "altered while sender and purpose remain valid"
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=target_a, message=tampered, idempotency_key="tampered-utility", send=True)
        assert exc.value.code == "prepared_message_mismatch"

        fake_token = copy.deepcopy(prepared_a["message"])
        fake_token["join"]["distribution_token"] = "aion_dist_" + "z" * 43
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=target_a, message=fake_token, idempotency_key="fake-token", send=True)
        assert exc.value.code == "prepared_message_mismatch"

        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=target_b, message=prepared_a["message"], idempotency_key="cross-target", send=True)
        assert exc.value.code == "prepared_message_mismatch"

        unprepared_campaign, unprepared_target, _ = _target(db)
        ambassador.set_campaign_state(db, unprepared_campaign, "ready")
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=unprepared_target, message=prepared_b["message"], idempotency_key="unprepared", send=True)
        assert exc.value.code == "target_not_prepared"


def test_send_verifies_bound_token_digest_and_active_state_before_network(monkeypatch):
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    monkeypatch.setattr(ambassador.safe_http, "fetch_json", lambda *a, **k: pytest.fail("inactive token reached network"))
    with SessionLocal() as db:
        _, target_id, prepared = _target(db, ready=True)
        target = db.scalar(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id))
        token = db.scalar(select(models.DistributionToken).where(models.DistributionToken.target_id == target.id))

        fake = copy.deepcopy(prepared["message"])
        fake["join"]["distribution_token"] = "aion_dist_" + "q" * 43
        target.prepared_message_digest = ambassador._digest_json(fake)
        db.commit()
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=target_id, message=fake, idempotency_key="digest-mismatch", send=True)
        assert exc.value.code == "prepared_token_mismatch"

        target.prepared_message_digest = ambassador._digest_json(prepared["message"])
        token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="expired-send", send=True)
        assert exc.value.code == "distribution_token_expired"

        token.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        token.use_count = token.maximum_uses
        db.commit()
        with pytest.raises(ambassador.AmbassadorError) as exc:
            ambassador.send_contact(db, target_id=target_id, message=prepared["message"], idempotency_key="exhausted-send", send=True)
        assert exc.value.code == "distribution_token_exhausted"


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
        issued = ambassador.issue_peer_referral(db, referrer_agent_id=referrer_id, idempotency_key="peer-one")
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


def test_referral_packet_uses_configured_canonical_host_not_request_host():
    _, key = _agent()
    response = client.post(
        "/agents/me/referral-packets",
        headers={
            "Authorization": "Bearer " + key,
            "Idempotency-Key": "host-header-referral",
            "Host": "attacker.invalid",
        },
        json={"maximum_uses": 5, "acknowledge_manual_forwarding": True},
    )
    assert response.status_code == 200
    packet = response.json()["packet"]
    assert packet["agent_card"] == "https://aion.example/.well-known/agent-card.json"
    assert packet["first_step"] == "https://aion.example/onboarding"
    assert "attacker.invalid" not in json.dumps(packet)


def test_tokenless_join_cannot_spoof_reserved_trusted_attribution_across_surfaces():
    from app.a2a_official import _join_via_a2a

    before_sources = client.get("/stats").json()["acquisition_source_field_raw_rows"]
    before = {
        source: before_sources.get(source, 0)
        for source in ("aion_ambassador_outbound", "trusted_peer_referral")
    }
    rest_id = "reserved-rest-" + uuid.uuid4().hex
    rest = client.post("/agents", json={
        "external_id": rest_id,
        "name": "Reserved REST",
        "acquisition_source": "aion_ambassador_outbound",
    })
    assert rest.status_code == 422
    assert rest.json()["detail"]["code"] == "reserved_trusted_attribution"

    mcp_id = "reserved-mcp-" + uuid.uuid4().hex
    params = {
        "name": "join_aion",
        "arguments": {
            "external_id": mcp_id,
            "name": "Reserved MCP",
            "acquisition_source": "trusted_peer_referral",
        },
        "_meta": {"io.modelcontextprotocol/protocolVersion": MCP_VERSION, "io.modelcontextprotocol/clientCapabilities": {}},
    }
    mcp = client.post("/mcp", headers={
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": "tools/call",
        "Mcp-Name": "join_aion",
        "Accept": "application/json, text/event-stream",
    }, json={"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": params})
    assert mcp.status_code == 200
    assert mcp.json()["result"]["isError"] is True
    assert mcp.json()["result"]["structuredContent"]["status"] == 422

    a2a_id = "reserved-a2a-" + uuid.uuid4().hex
    a2a = _join_via_a2a({
        "action": "join_aion",
        "external_id": a2a_id,
        "name": "Reserved A2A",
        "referrer": "trusted_ambassador_invite",
    }, "https://aion.example")
    assert a2a["ok"] is False
    assert a2a["status_code"] == 422
    assert a2a["error"]["code"] == "reserved_trusted_attribution"

    rows = client.get("/agents").json()
    assert not {rest_id, mcp_id, a2a_id}.intersection(row["external_id"] for row in rows)
    after_sources = client.get("/stats").json()["acquisition_source_field_raw_rows"]
    after = {
        source: after_sources.get(source, 0)
        for source in ("aion_ambassador_outbound", "trusted_peer_referral")
    }
    assert after == before


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


def test_campaign_return_requires_same_canonical_identity_and_package5_rule(monkeypatch):
    monkeypatch.setenv("AION_PACKAGE5_RETURN_THRESHOLD_SECONDS", "900")
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        campaign_id, _, prepared = _target(db, ready=True)
        referrer, _ = join_agent(schemas.AgentCreate(
            external_id="campaign-referrer-" + uuid.uuid4().hex,
            name="Campaign referrer",
            distribution_token=prepared["distribution_token"],
        ), db)
        packet_a = ambassador.issue_peer_referral(
            db, referrer_agent_id=referrer.id, idempotency_key="return-peer-a-" + uuid.uuid4().hex
        )["packet"]
        packet_b = ambassador.issue_peer_referral(
            db, referrer_agent_id=referrer.id, idempotency_key="return-peer-b-" + uuid.uuid4().hex
        )["packet"]
        agent_a, key_a = join_agent(schemas.AgentCreate(
            external_id="campaign-agent-a-" + uuid.uuid4().hex,
            name="Campaign agent A", distribution_token=packet_a["distribution_token"],
        ), db)
        agent_b, _ = join_agent(schemas.AgentCreate(
            external_id="campaign-agent-b-" + uuid.uuid4().hex,
            name="Campaign agent B", distribution_token=packet_b["distribution_token"],
        ), db)
        for agent in (agent_a, agent_b):
            package5_proof.record_participation_assessment(
                db, agent_id=agent.id, classification="independent_external_countable",
                evidence_reference="operator-reviewed-" + uuid.uuid4().hex,
                evidence_summary="Trusted independent evidence after peer referral review",
                idempotency_key="assessment-" + uuid.uuid4().hex,
            )
        agent_a_id, agent_b_id = agent_a.id, agent_b.id

    action_a = _verified_action(agent_a_id, created_at=now)
    submitted = _submit_vuo(key_a, action_a)
    assert submitted.status_code == 200
    assert submitted.json()["qualifies_as_package5_vuo"] is True
    with SessionLocal() as db:
        proof_created_at = db.scalar(
            select(models.Package5VuoProof.created_at).where(
                models.Package5VuoProof.requester_agent_id == agent_a_id
            )
        )
    later_at = proof_created_at.replace(tzinfo=timezone.utc) if proof_created_at.tzinfo is None else proof_created_at
    later_at += timedelta(seconds=901)

    _verified_action(agent_b_id, created_at=later_at)
    with SessionLocal() as db:
        assert ambassador.campaign_status(db, campaign_id)["funnel"]["returns_attributable"] == 0

    _verified_action(agent_a_id, created_at=later_at)
    with SessionLocal() as db:
        assert ambassador.campaign_status(db, campaign_id)["funnel"]["returns_attributable"] == 1


def test_legacy_payment_and_package6a_economics_are_unchanged():
    assert economic_kernel.REAL_MONEY_EXECUTION_ENABLED is False
    assert economic_kernel.MINIMUM_MARGIN_BPS == 4_000
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(models.PaymentIntent))
        _campaign(db, maximum_targets=1, maximum_contacts=0)
        after = db.scalar(select(func.count()).select_from(models.PaymentIntent))
        assert after == before
