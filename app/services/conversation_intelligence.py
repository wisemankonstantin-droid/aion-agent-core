"""Package 5F deterministic conversation intelligence.

Only bounded digests, protocol-id digests, explicit signals, inferred tags and
non-quoting summaries are persisted. Counterparty message text is never stored.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..conversation_models import ConversationEvidence, ConversationIntelligence
from ..db import SessionLocal


ANALYSIS_METHOD = "deterministic_rules_v1"
ANALYSIS_VERSION = "package5f_v1"
EVIDENCE_RETENTION_DAYS = 30
MAX_FRAGMENTS = 16
MAX_FRAGMENT_CHARS = 512
MAX_ANALYSIS_CHARS = 4096
MAX_CAMPAIGN_TARGETS = 30

_PATTERNS = {
    "need": ("need ", "looking for", "require ", "want "),
    "objection": ("not interested", "too expensive", "cannot ", "can't ", "does not work"),
    "feature_request": ("feature", "please add", "support for", "would be useful"),
    "integration_request": ("integrat", " api", "mcp", "a2a", "webhook"),
    "trust_security_requirement": ("security", "privacy", "trust", "credential", "compliance"),
    "pricing_commercial_interest": ("price", "pricing", "cost", "budget", " pay", "payment"),
    "positive_interest": ("interested", "sounds useful", "would try", "let's try"),
    "negative_interest": ("no thanks", "not interested", "do not contact", "stop contacting"),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _digest(value: object) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _parts(parts: object) -> list[str]:
    if not isinstance(parts, list):
        return []
    values = []
    for part in parts[:MAX_FRAGMENTS]:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str):
            values.append(text[:MAX_FRAGMENT_CHARS])
        root = part.get("root")
        if isinstance(root, dict) and isinstance(root.get("text"), str):
            values.append(root["text"][:MAX_FRAGMENT_CHARS])
    return values


def _known_text(response: dict) -> list[str]:
    values: list[str] = []
    error = response.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        values.append(error["message"][:MAX_FRAGMENT_CHARS])
    result = response.get("result")
    if not isinstance(result, dict):
        return values[:MAX_FRAGMENTS]
    values.extend(_parts(result.get("parts")))
    message = result.get("message")
    if isinstance(message, dict):
        values.extend(_parts(message.get("parts")))
    status = result.get("status")
    if isinstance(status, dict) and isinstance(status.get("message"), dict):
        values.extend(_parts(status["message"].get("parts")))
    task = result.get("task")
    if isinstance(task, dict):
        task_status = task.get("status")
        if isinstance(task_status, dict) and isinstance(task_status.get("message"), dict):
            values.extend(_parts(task_status["message"].get("parts")))
        for artifact in (task.get("artifacts") if isinstance(task.get("artifacts"), list) else [])[:4]:
            if isinstance(artifact, dict):
                values.extend(_parts(artifact.get("parts")))
    for artifact in (result.get("artifacts") if isinstance(result.get("artifacts"), list) else [])[:4]:
        if isinstance(artifact, dict):
            values.extend(_parts(artifact.get("parts")))
    return values[:MAX_FRAGMENTS]


def _protocol_digests(response: dict) -> dict[str, str | None]:
    result = response.get("result") if isinstance(response, dict) else None
    context_id = task_id = message_id = None
    if isinstance(result, dict):
        context_id = result.get("contextId") or result.get("context_id")
        message = result.get("message") if isinstance(result.get("message"), dict) else result
        if isinstance(message, dict):
            context_id = context_id or message.get("contextId") or message.get("context_id")
            message_id = message.get("messageId") or message.get("message_id")
        task = result.get("task") if isinstance(result.get("task"), dict) else None
        if task is not None:
            context_id = context_id or task.get("contextId") or task.get("context_id")
            task_id = task.get("id") or task.get("taskId") or task.get("task_id")
    return {
        "context": _digest(str(context_id)) if context_id not in (None, "") else None,
        "task": _digest(str(task_id)) if task_id not in (None, "") else None,
        "message": _digest(str(message_id)) if message_id not in (None, "") else None,
    }


def _signals(response: dict, fragments: list[str]) -> tuple[list[str], list[str]]:
    explicit = set()
    result = response.get("result") if isinstance(response, dict) else None
    if isinstance(result, dict) and result.get("opt_out") is True:
        explicit.add("opt_out")
    combined = " ".join(fragments)[:MAX_ANALYSIS_CHARS].lower()
    inferred = {
        signal for signal, needles in _PATTERNS.items()
        if any(needle in combined for needle in needles)
    }
    if "opt_out" in explicit:
        inferred.discard("positive_interest")
    return sorted(explicit), sorted(inferred)


def _summary(explicit: list[str], inferred: list[str], had_text: bool) -> str:
    if "opt_out" in explicit:
        return "Counterparty explicitly requested opt-out."
    tags = explicit + inferred
    if tags:
        return "Deterministic V1 detected supported signals: " + ", ".join(tags) + "."
    if had_text:
        return "Response contained semantic material but no supported deterministic V1 signal."
    return "Response contained no supported semantic text; no semantic signal was inferred."


def capture_ambassador_response(*, contact_id: str, response: object) -> str:
    """Persist digest-only evidence after the sender has committed transport truth."""
    if not isinstance(response, dict):
        return "unsupported_response_shape"
    try:
        with SessionLocal() as db:
            contact = db.scalar(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.contact_id == contact_id))
            if contact is None:
                return "contact_missing"
            existing = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
            if existing is not None:
                return "captured"
            fragments = _known_text(response)
            explicit, inferred = _signals(response, fragments)
            digests = _protocol_digests(response)
            combined = "\n".join(fragments)[:MAX_ANALYSIS_CHARS]
            now = _now()
            evidence = ConversationEvidence(
                conversation_id=str(uuid.uuid5(uuid.NAMESPACE_URL, "aion:conversation:" + contact.contact_id)),
                ambassador_contact_id=contact.id,
                source_kind="ambassador_contact",
                source_class="coordinated_ambassador",
                capture_class="digest_only" if fragments else "structured_only",
                protocol="a2a_jsonrpc",
                protocol_context_digest=digests["context"],
                protocol_task_digest=digests["task"],
                protocol_message_digest=digests["message"],
                safe_evidence=None,
                redaction_summary={
                    "message_text_persisted": False,
                    "raw_response_persisted": False,
                    "semantic_fragment_count": len(fragments),
                    "semantic_material_digest": _digest(combined) if fragments else None,
                    "semantic_chars_analyzed": len(combined),
                },
                evidence_bytes=0,
                evidence_expires_at=now + timedelta(days=EVIDENCE_RETENTION_DAYS),
                evidence_purged_at=None,
                captured_at=now,
            )
            db.add(evidence)
            db.flush()
            db.add(ConversationIntelligence(
                intelligence_id=str(uuid.uuid4()),
                conversation_evidence_id=evidence.id,
                analysis_method=ANALYSIS_METHOD,
                analysis_version=ANALYSIS_VERSION,
                summary=_summary(explicit, inferred, bool(fragments)),
                explicit_signals=explicit,
                inferred_signals=inferred,
                created_at=now,
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
                return "captured" if existing is not None else "capture_failed"
            return "captured"
    except Exception:
        return "capture_failed"


def contact_capture_state(db: Session, contact: models.AmbassadorContactAttempt) -> str:
    if not contact.response_received:
        return "no_response"
    evidence = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
    if evidence is None:
        return "capture_missing"
    if evidence.evidence_purged_at is not None:
        return "purged"
    if _aware(evidence.evidence_expires_at) <= _now():
        return "expired"
    return "captured"


def purge_campaign_evidence(db: Session, campaign_id: str) -> int:
    campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
    if campaign is None:
        return 0
    target_ids = list(db.scalars(select(models.AmbassadorTarget.id).where(models.AmbassadorTarget.campaign_id == campaign.id)))
    if not target_ids:
        return 0
    contact_ids = list(db.scalars(select(models.AmbassadorContactAttempt.id).where(models.AmbassadorContactAttempt.target_id.in_(target_ids))))
    if not contact_ids:
        return 0
    rows = list(db.scalars(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id.in_(contact_ids))))
    now = _now()
    changed = 0
    for row in rows:
        if row.evidence_purged_at is None:
            row.safe_evidence = None
            row.evidence_bytes = 0
            row.evidence_purged_at = now
            db.add(row)
            changed += 1
    db.flush()
    return changed


def campaign_intelligence_report(db: Session, campaign_id: str) -> dict:
    campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
    if campaign is None:
        return {"campaign_id": campaign_id, "state": "campaign_missing", "conversations": [], "read_only": True}
    targets = list(db.scalars(
        select(models.AmbassadorTarget).where(models.AmbassadorTarget.campaign_id == campaign.id)
        .order_by(models.AmbassadorTarget.id).limit(MAX_CAMPAIGN_TARGETS)
    ))
    target_by_pk = {row.id: row for row in targets}
    contacts = list(db.scalars(
        select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.target_id.in_(target_by_pk))
        .order_by(models.AmbassadorContactAttempt.created_at, models.AmbassadorContactAttempt.id)
    )) if target_by_pk else []
    conversations = []
    explicit_by_target: dict[int, set[str]] = defaultdict(set)
    inferred_by_target: dict[int, set[str]] = defaultdict(set)
    for contact in contacts:
        target = target_by_pk.get(contact.target_id)
        evidence = db.scalar(select(ConversationEvidence).where(ConversationEvidence.ambassador_contact_id == contact.id))
        intelligence = None
        if evidence is not None:
            intelligence = db.scalar(
                select(ConversationIntelligence).where(ConversationIntelligence.conversation_evidence_id == evidence.id)
                .order_by(ConversationIntelligence.created_at.desc()).limit(1)
            )
        explicit = list(intelligence.explicit_signals or []) if intelligence else []
        inferred = list(intelligence.inferred_signals or []) if intelligence else []
        explicit_by_target[contact.target_id].update(explicit)
        inferred_by_target[contact.target_id].update(inferred)
        state = contact_capture_state(db, contact)
        conversations.append({
            "contact_id": contact.contact_id,
            "target_id": target.target_id if target else None,
            "contact_result_class": contact.result_class,
            "http_status": contact.http_status,
            "response_received": contact.response_received,
            "capture_state": state,
            "capture_reason": "pre_package_5f_or_capture_failure" if state == "capture_missing" else None,
            "conversation_id": evidence.conversation_id if evidence else None,
            "protocol_context_digest": evidence.protocol_context_digest if evidence else None,
            "protocol_task_digest": evidence.protocol_task_digest if evidence else None,
            "protocol_message_digest": evidence.protocol_message_digest if evidence else None,
            "safe_evidence": [],
            "summary": intelligence.summary if intelligence else None,
            "explicit_signals": explicit,
            "inferred_signals": inferred,
            "analysis_method": intelligence.analysis_method if intelligence else None,
            "analysis_version": intelligence.analysis_version if intelligence else None,
        })
    explicit_counts = Counter()
    inferred_counts = Counter()
    for values in explicit_by_target.values():
        explicit_counts.update(values)
    for values in inferred_by_target.values():
        inferred_counts.update(values)
    recurring = [
        {"signal": signal, "distinct_targets": count, "classification": "repeated_coordinated_pilot_signal"}
        for signal, count in sorted((explicit_counts + inferred_counts).items()) if count >= 2
    ]
    return {
        "campaign_id": campaign_id,
        "source_class": "coordinated_ambassador",
        "conversations": conversations,
        "aggregate": {
            "contacts": len(contacts),
            "responses": sum(1 for row in contacts if row.response_received),
            "captured_conversations": sum(1 for row in conversations if row["capture_state"] in {"captured", "expired", "purged"}),
            "capture_missing": sum(1 for row in conversations if row["capture_state"] == "capture_missing"),
            "explicit_signal_distinct_target_counts": dict(sorted(explicit_counts.items())),
            "inferred_signal_distinct_target_counts": dict(sorted(inferred_counts.items())),
            "recurring_signals": recurring,
        },
        "truth_boundaries": {
            "message_text_persisted": False,
            "raw_response_persisted": False,
            "counterparty_evidence_separate_from_aion_interpretation": True,
            "coordinated_feedback_is_not_independent_adoption": True,
            "coordinated_feedback_is_not_package5_vuo": True,
            "response_is_not_payment_or_revenue": True,
            "automatic_product_change": False,
            "paid_inference_used": False,
        },
        "retention": {
            "evidence_expiry_marker_days": EVIDENCE_RETENTION_DAYS,
            "expired_rows_physically_deleted_automatically": False,
            "campaign_close_automatically_marks_evidence_purged": False,
            "message_text_persisted": False,
        },
        "read_only": True,
    }
