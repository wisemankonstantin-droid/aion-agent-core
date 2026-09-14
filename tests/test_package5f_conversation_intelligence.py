from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import delete, select

from app import models
from app.conversation_models import ConversationEvidence, ConversationIntelligence
from app.db import SessionLocal
from app.services import ambassador, conversation_intelligence
from app.services.safe_http import FetchResult


def _seed_contact(*, suffix: str, response_received: bool = True):
    with SessionLocal() as db:
        now = ambassador._now()
        campaign = models.AmbassadorCampaign(
            campaign_id=str(uuid.uuid4()),
            name=f"5f-{suffix}",
            purpose="Package 5F test",
            state="ready",
            maximum_targets=3,
            maximum_contacts=3,
            created_at=now,
            updated_at=now,
        )
        db.add(campaign)
        db.flush()
        target = models.AmbassadorTarget(
            target_id=str(uuid.uuid4()),
            campaign_id=campaign.id,
            discovery_source="test",
            source_identifier=f"provider-{suffix}",
            agent_card_url=f"https://{suffix}.example/card",
            interaction_url=f"https://{suffix}.example/a2a",
            target_fingerprint=ambassador._digest_json({"target": suffix}),
            metadata_digest=ambassador._digest_json({"metadata": suffix}),
            prepared_message_digest=None,
            manifest_reachable=True,
            declared_a2a_v1_jsonrpc=True,
            interaction_url_validated=True,
            authentication_requirement="none",
            payment_required=False,
            qualification_state="qualified",
            qualification_reasons=["test"],
            contact_state="response_received" if response_received else "contacted",
            suppressed=False,
            suppression_reason=None,
            created_at=now,
            updated_at=now,
        )
        db.add(target)
        db.flush()
        contact = models.AmbassadorContactAttempt(
            contact_id=str(uuid.uuid4()),
            target_id=target.id,
            idempotency_key=f"contact-{suffix}",
            outbound_request_digest=ambassador._digest_json({"request": suffix}),
            result_class="response_received" if response_received else "delivered",
            http_status=200,
            response_digest=ambassador._digest_json({"response": suffix}),
            response_received=response_received,
            created_at=now,
            completed_at=now,
        )
        db.add(contact)
        db.commit()
        return campaign.campaign_id, target.target_id, contact.contact_id


def _cleanup_campaign(campaign_id: str):
    with SessionLocal() as db:
        campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
        if campaign is None:
            return
        target_ids = list(db.scalars(select(models.AmbassadorTarget.id).where(models.AmbassadorTarget.campaign_id == campaign.id)))
        contact_ids = list(db.scalars(select(models.AmbassadorContactAttempt.id).where(models.AmbassadorContactAttempt.target_id.in_(target_ids)))) if target_ids else []
        evidence_ids = list(db.scalars(select(ConversationEvidence.id).where(ConversationEvidence.ambassador_contact_id.in_(contact_ids)))) if contact_ids else []
        if evidence_ids:
            db.execute(delete(ConversationIntelligence).where(ConversationIntelligence.conversation_evidence_id.in_(evidence_ids)))
        if contact_ids:
            db.execute(delete(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id.in_(contact_ids)))
            db.execute(delete(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.id.in_(contact_ids)))
        if target_ids:
            db.execute(delete(models.DistributionToken).where(models.DistributionToken.target_id.in_(target_ids)))
            db.execute(delete(models.AmbassadorTarget).where(models.AmbassadorTarget.id.in_(target_ids)))
        db.delete(campaign)
        db.commit()


def test_digest_only_capture_separates_evidence_from_interpretation():
    campaign_id, _, contact_id = _seed_contact(suffix="digest")
    raw_text = "We need an MCP integration and pricing for this workflow. reference-phrase-5f"
    response = {
        "jsonrpc": "2.0",
        "id": "rpc-raw-id",
        "result": {
            "contextId": "raw-context-id",
            "message": {
                "messageId": "raw-message-id",
                "parts": [{"text": raw_text}],
            },
        },
    }
    try:
        assert conversation_intelligence.capture_ambassador_response(contact_id=contact_id, response=response) == "captured"
        with SessionLocal() as db:
            contact = db.scalar(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.contact_id == contact_id))
            evidence = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
            intelligence = db.scalar(select(ConversationIntelligence).where(ConversationIntelligence.conversation_evidence_id == evidence.id))
            assert evidence.capture_class == "digest_only"
            assert evidence.safe_evidence is None
            assert evidence.evidence_bytes == 0
            assert evidence.redaction_summary["message_text_persisted"] is False
            assert evidence.redaction_summary["raw_response_persisted"] is False
            assert evidence.redaction_summary["semantic_material_digest"].startswith("sha256:")
            assert evidence.protocol_context_digest.startswith("sha256:")
            assert evidence.protocol_message_digest.startswith("sha256:")
            persisted = json.dumps({
                "evidence": evidence.redaction_summary,
                "summary": intelligence.summary,
                "explicit": intelligence.explicit_signals,
                "inferred": intelligence.inferred_signals,
                "context": evidence.protocol_context_digest,
                "message": evidence.protocol_message_digest,
            })
            assert raw_text not in persisted
            assert "reference-phrase-5f" not in persisted
            assert "raw-context-id" not in persisted
            assert "raw-message-id" not in persisted
            assert "integration_request" in intelligence.inferred_signals
            assert "pricing_commercial_interest" in intelligence.inferred_signals
            assert intelligence.explicit_signals == []
    finally:
        _cleanup_campaign(campaign_id)


def test_structured_opt_out_is_explicit_not_inferred():
    campaign_id, _, contact_id = _seed_contact(suffix="optout")
    try:
        response = {
            "jsonrpc": "2.0",
            "id": "x",
            "result": {"message": {"messageId": "opt-out", "role": "ROLE_AGENT", "parts": [{"data": {"opt_out": True}}]}},
        }
        assert conversation_intelligence.capture_ambassador_response(contact_id=contact_id, response=response) == "captured"
        with SessionLocal() as db:
            contact = db.scalar(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.contact_id == contact_id))
            evidence = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
            intelligence = db.scalar(select(ConversationIntelligence).where(ConversationIntelligence.conversation_evidence_id == evidence.id))
            assert evidence.capture_class == "structured_only"
            assert intelligence.explicit_signals == ["opt_out"]
            assert "positive_interest" not in intelligence.inferred_signals
            assert intelligence.summary == "Counterparty explicitly requested opt-out."
    finally:
        _cleanup_campaign(campaign_id)


def test_safe_structured_routing_feedback_is_normalized_and_reported_without_raw_text():
    campaign_id, _, contact_id = _seed_contact(suffix="routing-feedback")
    response = {
        "jsonrpc": "2.0",
        "id": "routing",
        "result": {
            "message": {
                "messageId": "routing-reply",
                "role": "ROLE_AGENT",
                "parts": [
                    {
                        "data": {
                            "aion_feedback": {
                                "routing_need": "  verify an external A2A provider  ",
                                "currency": "USD",
                                "requester_max_price": "0.050",
                                "candidate_identifier": "registry.provider-1",
                            }
                        }
                    }
                ],
            }
        },
    }
    try:
        assert conversation_intelligence.capture_ambassador_response(contact_id=contact_id, response=response) == "captured"
        with SessionLocal() as db:
            contact = db.scalar(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.contact_id == contact_id))
            evidence = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
            assert evidence.safe_evidence == [{
                "kind": "routing_feedback_v1",
                "routing_need": "verify an external A2A provider",
                "currency": "USD",
                "requester_max_price": "0.05",
                "candidate_identifier": "registry.provider-1",
            }]
            report = conversation_intelligence.campaign_intelligence_report(db, campaign_id)
            assert report["conversations"][0]["safe_evidence"] == evidence.safe_evidence
            assert report["truth_boundaries"]["response_is_not_payment_or_revenue"] is True
            evidence.evidence_expires_at = evidence.captured_at
            db.add(evidence)
            db.commit()
            expired = conversation_intelligence.campaign_intelligence_report(db, campaign_id)
            assert expired["conversations"][0]["capture_state"] == "expired"
            assert expired["conversations"][0]["safe_evidence"] == []
    finally:
        _cleanup_campaign(campaign_id)


@pytest.mark.parametrize(
    "feedback",
    [
        {"routing_need": "research", "currency": "EUR"},
        {"routing_need": "research", "currency": "USD", "requester_max_price": "01.00"},
        {"routing_need": "https://secret.example/work", "currency": "USD"},
        {"routing_need": "research", "currency": "USD", "unknown": "field"},
        {"routing_need": "api_key=do-not-store", "currency": "USD"},
        {"routing_need": "token=do-not-store", "currency": "USD"},
        {"routing_need": "A" * 40, "currency": "USD"},
        {"routing_need": "research", "currency": "USD", "candidate_identifier": "https://provider.example"},
    ],
)
def test_malformed_or_secret_structured_routing_feedback_is_rejected_entirely(feedback):
    campaign_id, _, contact_id = _seed_contact(suffix="rejected-" + uuid.uuid4().hex[:8])
    response = {
        "jsonrpc": "2.0",
        "id": "routing",
        "result": {"message": {"messageId": "reply", "role": "ROLE_AGENT", "parts": [{"data": {"aion_feedback": feedback}}]}},
    }
    try:
        assert conversation_intelligence.capture_ambassador_response(contact_id=contact_id, response=response) == "captured"
        with SessionLocal() as db:
            contact = db.scalar(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.contact_id == contact_id))
            evidence = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
            assert evidence.safe_evidence is None
            assert evidence.redaction_summary["structured_routing_candidate_rejected"] is True
            assert "do-not-store" not in json.dumps(evidence.redaction_summary)
    finally:
        _cleanup_campaign(campaign_id)


def test_opt_out_suppresses_structured_routing_feedback():
    campaign_id, _, contact_id = _seed_contact(suffix="routing-optout")
    response = {
        "jsonrpc": "2.0",
        "id": "routing",
        "result": {
            "message": {
                "messageId": "reply",
                "role": "ROLE_AGENT",
                "parts": [
                    {"data": {"aion_feedback": {"routing_need": "research", "currency": "USD"}}},
                    {"data": {"opt_out": True}},
                ],
            }
        },
    }
    try:
        assert conversation_intelligence.capture_ambassador_response(contact_id=contact_id, response=response) == "captured"
        with SessionLocal() as db:
            contact = db.scalar(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.contact_id == contact_id))
            evidence = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
            intelligence = db.scalar(select(ConversationIntelligence).where(ConversationIntelligence.conversation_evidence_id == evidence.id))
            assert evidence.safe_evidence is None
            assert evidence.redaction_summary["structured_routing_suppressed_by_opt_out"] is True
            assert intelligence.explicit_signals == ["opt_out"]
    finally:
        _cleanup_campaign(campaign_id)


def test_campaign_report_aggregates_distinct_targets_without_promoting_proof():
    campaign_id, _, first_contact = _seed_contact(suffix="aggregate-a")
    second_campaign_id, _, second_contact = _seed_contact(suffix="aggregate-b")
    try:
        with SessionLocal() as db:
            first_campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
            second_campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == second_campaign_id))
            second_target = db.scalar(select(models.AmbassadorTarget).where(models.AmbassadorTarget.campaign_id == second_campaign.id))
            second_target.campaign_id = first_campaign.id
            db.add(second_target)
            db.commit()
        response = {"jsonrpc": "2.0", "id": "x", "result": {"parts": [{"text": "We need integration support."}]}}
        assert conversation_intelligence.capture_ambassador_response(contact_id=first_contact, response=response) == "captured"
        assert conversation_intelligence.capture_ambassador_response(contact_id=second_contact, response=response) == "captured"
        with SessionLocal() as db:
            report = conversation_intelligence.campaign_intelligence_report(db, campaign_id)
            assert report["aggregate"]["inferred_signal_distinct_target_counts"]["integration_request"] == 2
            assert report["aggregate"]["inferred_signal_distinct_target_counts"]["need"] == 2
            assert report["aggregate"]["recurring_signals"] == [
                {
                    "signal": "integration_request",
                    "distinct_targets": 2,
                    "classification": "repeated_coordinated_pilot_signal",
                },
                {
                    "signal": "need",
                    "distinct_targets": 2,
                    "classification": "repeated_coordinated_pilot_signal",
                },
            ]
            assert report["truth_boundaries"]["coordinated_feedback_is_not_independent_adoption"] is True
            assert report["truth_boundaries"]["coordinated_feedback_is_not_package5_vuo"] is True
            assert report["truth_boundaries"]["response_is_not_payment_or_revenue"] is True
            assert report["truth_boundaries"]["message_text_persisted"] is False
            assert report["retention"]["evidence_expiry_marker_days"] == 30
            assert report["retention"]["expired_rows_physically_deleted_automatically"] is False
            assert report["retention"]["campaign_close_automatically_marks_evidence_purged"] is False
            assert report["read_only"] is True
    finally:
        _cleanup_campaign(campaign_id)
        _cleanup_campaign(second_campaign_id)


def test_semantic_capture_failure_does_not_retry_or_rollback_contact(monkeypatch):
    with SessionLocal() as db:
        now = ambassador._now()
        campaign = models.AmbassadorCampaign(
            campaign_id=str(uuid.uuid4()), name="capture-failure", purpose="5F", state="ready",
            maximum_targets=1, maximum_contacts=1, created_at=now, updated_at=now,
        )
        db.add(campaign)
        db.flush()
        target = models.AmbassadorTarget(
            target_id=str(uuid.uuid4()), campaign_id=campaign.id, discovery_source="test",
            source_identifier="capture-failure", agent_card_url="https://capture.example/card",
            interaction_url="https://capture.example/a2a",
            target_fingerprint=ambassador._digest_json({"target": "capture-failure"}),
            metadata_digest=ambassador._digest_json({"metadata": "capture-failure"}),
            prepared_message_digest=None, manifest_reachable=True, declared_a2a_v1_jsonrpc=True,
            interaction_url_validated=True, authentication_requirement="none", payment_required=False,
            qualification_state="qualified", qualification_reasons=["test"], contact_state="not_ready",
            suppressed=False, suppression_reason=None, created_at=now, updated_at=now,
        )
        db.add(target)
        db.commit()
        campaign_id = campaign.campaign_id
        prepared = ambassador.prepare_target(db, target_id=target.target_id, public_base_url="https://aion.example")

        calls = []
        def fake_fetch(*args, **kwargs):
            calls.append(1)
            return FetchResult(200, b"{}", None, 1), {
                "jsonrpc": "2.0",
                "id": kwargs["payload"]["id"],
                "result": {"message": {"messageId": "capture", "role": "ROLE_AGENT", "parts": [{"text": "need integration"}]}},
            }

        monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
        monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
        monkeypatch.setattr(ambassador.safe_http, "fetch_json", fake_fetch)
        monkeypatch.setattr(conversation_intelligence, "capture_ambassador_response", lambda **kwargs: "capture_failed")
        result = ambassador.send_contact(
            db,
            target_id=target.target_id,
            message=prepared["message"],
            idempotency_key="capture-failure-once",
            send=True,
        )
        assert result["result_class"] == "response_received"
        assert result["conversation_capture_state"] == "capture_failed"
        assert len(calls) == 1
        contact = db.scalar(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.contact_id == result["contact_id"]))
        assert contact.result_class == "response_received"
        assert contact.response_received is True
    _cleanup_campaign(campaign_id)
