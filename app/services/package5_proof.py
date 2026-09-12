"""Package 5 truth-preserving participation, VUO, and return evidence."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..release_identity import release_identity
from .identity_resolution import logical_groups


MAX_PROOF_RAW_AGENT_ROWS = 500
MAX_PROOF_LOGICAL_IDENTITIES = 500
MAX_PROOF_VUO_CANDIDATES = 5_000
DEFAULT_RETURN_THRESHOLD_SECONDS = 86_400
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CLASSIFICATION_REASONS = {
    "aion_operated_internal": "operator_confirmed_aion_operated_or_internal",
    "synthetic_probe_test": "operator_confirmed_synthetic_probe_or_test",
    "coordinated_design_partner": "operator_confirmed_coordinated_design_partner",
    "operator_invited_coordinated_test": "operator_confirmed_invited_or_coordinated_test",
    "independent_external_candidate": "independence_evidence_incomplete",
    "independent_external_countable": "operator_verified_independent_no_known_coordination",
}


class Package5ProofError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _normalize_idempotency_key(value: str | None) -> str:
    key = str(value or "").strip()
    if not _IDEMPOTENCY_PATTERN.fullmatch(key):
        raise Package5ProofError(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key must be 1 to 128 safe ASCII characters",
        )
    return key


def _return_threshold_seconds() -> int:
    try:
        configured = int(os.getenv("AION_PACKAGE5_RETURN_THRESHOLD_SECONDS", str(DEFAULT_RETURN_THRESHOLD_SECONDS)))
    except ValueError:
        configured = DEFAULT_RETURN_THRESHOLD_SECONDS
    return max(900, min(configured, 30 * 24 * 60 * 60))


def _group_for_agent(groups: list[dict], agent_id: int) -> dict | None:
    return next((group for group in groups if agent_id in group["row_ids"]), None)


def _bounded_logical_groups(db: Session) -> list[dict]:
    raw_agents = db.scalar(select(func.count()).select_from(models.Agent)) or 0
    if raw_agents > MAX_PROOF_RAW_AGENT_ROWS:
        raise Package5ProofError(
            503,
            "proof_resource_limit",
            "Package 5 logical-identity input exceeds the single-instance V1 bound",
        )
    groups = logical_groups(db)
    if len(groups) > MAX_PROOF_LOGICAL_IDENTITIES:
        raise Package5ProofError(
            503,
            "proof_resource_limit",
            "Package 5 logical-identity result exceeds the single-instance V1 bound",
        )
    return groups


def _forced_exclusion(db: Session, group: dict, agents_by_id: dict[int, models.Agent]) -> dict | None:
    trusted_ambassador = db.scalar(
        select(models.DistributionJoinAttribution.id).where(
            models.DistributionJoinAttribution.agent_id.in_(group["row_ids"]),
            models.DistributionJoinAttribution.kind == "ambassador_invite",
        ).limit(1)
    )
    if trusted_ambassador is not None:
        return {
            "classification": "operator_invited_coordinated_test",
            "reason_code": "trusted_aion_ambassador_outbound_attribution",
            "countable": False,
            "evidence_authority": "server_verified_distribution_token",
            "assessment_id": None,
        }
    configured = {
        value.strip().lower()
        for value in os.getenv("AION_OPERATED_EXTERNAL_IDS", "").split(",")
        if value.strip()
    }
    synthetic_markers = ("internal-test", "synthetic-test", "probe-test", "staging-test")
    for agent_id in group["row_ids"]:
        agent = agents_by_id[agent_id]
        if (agent.external_id or "").lower() in configured:
            return {
                "classification": "aion_operated_internal",
                "reason_code": "configured_aion_operated_identity",
                "countable": False,
                "evidence_authority": "configured_server_exclusion",
                "assessment_id": None,
            }
        attribution = f"{agent.acquisition_source or ''} {agent.referrer or ''}".lower()
        if "aion-operated" in attribution:
            return {
                "classification": "aion_operated_internal",
                "reason_code": "aion_operated_marker_in_logical_group",
                "countable": False,
                "evidence_authority": "server_exclusion_rule",
                "assessment_id": None,
            }
        if any(marker in attribution for marker in synthetic_markers):
            return {
                "classification": "synthetic_probe_test",
                "reason_code": "test_or_probe_marker_in_logical_group",
                "countable": False,
                "evidence_authority": "server_exclusion_rule",
                "assessment_id": None,
            }
    return None


def _classification_for_group(
    db: Session,
    group: dict,
    agents_by_id: dict[int, models.Agent],
) -> dict:
    forced = _forced_exclusion(db, group, agents_by_id)
    if forced is not None:
        return forced
    assessment = db.scalar(
        select(models.Package5ParticipationAssessment)
        .where(models.Package5ParticipationAssessment.canonical_agent_id.in_(group["row_ids"]))
        .order_by(
            models.Package5ParticipationAssessment.assessed_at.desc(),
            models.Package5ParticipationAssessment.id.desc(),
        )
        .limit(1)
    )
    if assessment is None:
        trusted_peer_referral = db.scalar(
            select(models.DistributionJoinAttribution.id).where(
                models.DistributionJoinAttribution.agent_id.in_(group["row_ids"]),
                models.DistributionJoinAttribution.kind == "peer_referral",
            ).limit(1)
        )
        if trusted_peer_referral is not None:
            return {
                "classification": "independent_external_candidate",
                "reason_code": "trusted_peer_referral_requires_operator_review",
                "countable": False,
                "evidence_authority": "server_verified_distribution_token",
                "assessment_id": None,
            }
        return {
            "classification": "unknown_not_proven",
            "reason_code": "no_trusted_package5_participation_assessment",
            "countable": False,
            "evidence_authority": "none",
            "assessment_id": None,
        }
    countable = (
        assessment.classification == "independent_external_countable"
        and assessment.reason_code == _CLASSIFICATION_REASONS["independent_external_countable"]
        and assessment.evidence_authority == "operator_reviewed_evidence"
    )
    return {
        "classification": assessment.classification,
        "reason_code": assessment.reason_code,
        "countable": countable,
        "evidence_authority": assessment.evidence_authority,
        "assessment_id": assessment.id,
    }


def participation_readiness(db: Session, requester_agent_id: int) -> dict:
    """Self-scoped read model; no assessment, lifecycle touch or other writes."""
    groups = _bounded_logical_groups(db)
    group = _group_for_agent(groups, requester_agent_id)
    if group is None:
        raise Package5ProofError(404, "agent_not_found", "Agent not found")
    agents = {agent.id: agent for agent in db.scalars(
        select(models.Agent).where(models.Agent.id.in_(group["row_ids"]))
    )}
    classification = _classification_for_group(db, group, agents)
    ready = classification["countable"]
    excluded = classification["classification"] in {
        "aion_operated_internal", "synthetic_probe_test", "coordinated_design_partner",
        "operator_invited_coordinated_test",
    }
    state = "participation_ready" if ready else "excluded" if excluded else "review_incomplete"
    instruction = (
        "Participation gate satisfied now, not a VUO guarantee. Run an explicitly authorized "
        "verified action, inspect durable evidence, and only if genuinely useful submit the "
        "separate authenticated requester acknowledgement. Classification must still be "
        "countable at submission and proof read."
        if ready else
        "This identity is excluded from Package 5 independent proof. Do not submit a VUO "
        "for qualification. Public utility remains available; do not create another identity "
        "to bypass exclusion."
        if excluded else
        "Preserve your credential and evidence and wait for operator review; do not submit "
        "a VUO for qualification yet. Candidate status is not countable. This read does not "
        "request or guarantee a review; public utility and optional join do not require review."
    )
    return {
        "canonical_agent_id": group["canonical_agent_id"],
        **classification,
        "vuo_submission_ready": ready,
        "readiness_scope": "participation_only_at_read_time",
        "operator_review_incomplete": not ready and not excluded,
        "excluded": excluded,
        "state": state,
        "next_action": instruction,
        "read_only": True,
        "records_activity_or_commercial_evidence": False,
        "late_reclassification_upgrades_prior_candidate": False,
    }


def record_participation_assessment(
    db: Session,
    *,
    agent_id: int,
    classification: str,
    evidence_reference: str,
    evidence_summary: str,
    idempotency_key: str,
) -> dict:
    """Record an operator-reviewed assessment; this is intentionally not an HTTP API."""

    if classification not in _CLASSIFICATION_REASONS:
        raise Package5ProofError(422, "invalid_classification", "Unsupported participation classification")
    reference = str(evidence_reference or "").strip()
    summary = str(evidence_summary or "").strip()
    if not reference or len(reference) > 1_000 or not summary or len(summary) > 500:
        raise Package5ProofError(422, "invalid_evidence", "Bounded evidence reference and summary are required")
    key = _normalize_idempotency_key(idempotency_key)
    groups = _bounded_logical_groups(db)
    group = _group_for_agent(groups, agent_id)
    if group is None:
        raise Package5ProofError(404, "agent_not_found", "Agent not found")
    canonical_id = group["canonical_agent_id"]
    reason = _CLASSIFICATION_REASONS[classification]
    material = {
        "canonical_agent_id": canonical_id,
        "classification": classification,
        "reason_code": reason,
        "evidence_reference_digest": _digest(reference),
        "evidence_summary_digest": _digest(summary),
    }
    digest = _digest(material)
    existing = db.scalar(
        select(models.Package5ParticipationAssessment).where(
            models.Package5ParticipationAssessment.canonical_agent_id == canonical_id,
            models.Package5ParticipationAssessment.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.assessment_digest != digest:
            raise Package5ProofError(409, "idempotency_conflict", "Idempotency-Key was used for different assessment evidence")
        return _serialize_assessment(existing, replayed=True)
    identity = release_identity()
    row = models.Package5ParticipationAssessment(
        assessment_id=str(uuid.uuid4()),
        canonical_agent_id=canonical_id,
        idempotency_key=key,
        assessment_digest=digest,
        classification=classification,
        reason_code=reason,
        evidence_authority="operator_reviewed_evidence",
        evidence_reference_digest=material["evidence_reference_digest"],
        evidence_summary_digest=material["evidence_summary_digest"],
        release_sha=identity["release_sha"],
        assessed_at=_utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(models.Package5ParticipationAssessment).where(
                models.Package5ParticipationAssessment.canonical_agent_id == canonical_id,
                models.Package5ParticipationAssessment.idempotency_key == key,
            )
        )
        if existing is None or existing.assessment_digest != digest:
            raise Package5ProofError(409, "assessment_conflict", "Concurrent assessment conflict")
        return _serialize_assessment(existing, replayed=True)
    db.refresh(row)
    return _serialize_assessment(row)


def _serialize_assessment(row: models.Package5ParticipationAssessment, *, replayed: bool = False) -> dict:
    return {
        "assessment_id": row.assessment_id,
        "canonical_agent_id": row.canonical_agent_id,
        "classification": row.classification,
        "reason_code": row.reason_code,
        "evidence_authority": row.evidence_authority,
        "evidence_reference_digest": row.evidence_reference_digest,
        "evidence_summary_digest": row.evidence_summary_digest,
        "assessed_at": row.assessed_at.isoformat(),
        "idempotent_replay": replayed,
    }


def _semantic_action_evidence(db: Session, run: models.ActionRun) -> tuple[bool, str, str, str]:
    outcome = db.scalar(select(models.ActionOutcome).where(models.ActionOutcome.action_run_id == run.id))
    verification = db.scalar(select(models.ActionVerification).where(models.ActionVerification.action_run_id == run.id))
    method = verification.verification_method if verification is not None else "none"
    state = verification.state if verification is not None else "missing"
    if run.state != "completed":
        return False, "underlying_action_not_completed", state, method
    if outcome is None or not outcome.verified_outcome:
        return False, "underlying_outcome_not_verified", state, method
    if not outcome.callability_verified or not outcome.proof_present:
        return False, "underlying_callability_proof_missing", state, method
    if verification is None or verification.state != "verified":
        return False, "underlying_verification_not_verified", state, method
    return True, "requester_confirmed_verified_callability_goal", state, method


def _cost_evidence(run: models.ActionRun) -> tuple[str, str | None, str | None]:
    if run.cost_amount is None or run.cost_currency is None:
        return "unknown", None, None
    try:
        amount = Decimal(run.cost_amount)
    except (InvalidOperation, ValueError):
        return "unknown", None, None
    currency = str(run.cost_currency).strip().upper()
    if not amount.is_finite() or amount < 0 or not re.fullmatch(r"[A-Z]{3,8}", currency):
        return "unknown", None, None
    return ("known_zero" if amount == 0 else "known_nonzero", str(amount), currency)


def submit_vuo_candidate(
    db: Session,
    *,
    requester_agent_id: int,
    payload: schemas.Package5VuoSubmission,
    idempotency_key: str | None,
) -> dict:
    key = _normalize_idempotency_key(idempotency_key)
    groups = _bounded_logical_groups(db)
    group = _group_for_agent(groups, requester_agent_id)
    if group is None:
        raise Package5ProofError(404, "agent_not_found", "Agent not found")
    try:
        normalized_action_id = str(uuid.UUID(payload.action_id))
    except (TypeError, ValueError, AttributeError):
        raise Package5ProofError(404, "action_not_found", "Action run not found")
    run = db.scalar(select(models.ActionRun).where(models.ActionRun.action_id == normalized_action_id))
    if run is None or run.requester_agent_id not in group["row_ids"]:
        raise Package5ProofError(404, "action_not_found", "Action run not found")
    material = payload.model_dump(mode="json")
    digest = _digest(material)
    canonical_id = group["canonical_agent_id"]
    existing = db.scalar(
        select(models.Package5VuoProof).where(
            models.Package5VuoProof.canonical_requester_agent_id == canonical_id,
            models.Package5VuoProof.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.request_digest != digest:
            raise Package5ProofError(409, "idempotency_conflict", "Idempotency-Key was used for a different VUO candidate")
        return _serialize_vuo(db, existing, groups, replayed=True)
    action_existing = db.scalar(
        select(models.Package5VuoProof).where(models.Package5VuoProof.action_run_id == run.id)
    )
    if action_existing is not None:
        if action_existing.request_digest == digest:
            return _serialize_vuo(db, action_existing, groups, replayed=True)
        raise Package5ProofError(409, "action_already_acknowledged", "This action already has a different VUO candidate")

    agents_by_id = {agent.id: agent for agent in db.scalars(select(models.Agent)).all()}
    participation = _classification_for_group(db, group, agents_by_id)
    semantic, eligibility_reason, verification_state, verification_method = _semantic_action_evidence(db, run)
    cost_state, cost_amount, cost_currency = _cost_evidence(run)
    identity = release_identity()
    row = models.Package5VuoProof(
        vuo_id=str(uuid.uuid4()),
        canonical_requester_agent_id=canonical_id,
        requester_agent_id=requester_agent_id,
        action_run_id=run.id,
        idempotency_key=key,
        request_digest=digest,
        goal_kind=payload.goal_kind,
        product_goal=payload.product_goal,
        delivered_outcome=payload.delivered_outcome,
        outcome_verification_state=verification_state,
        outcome_verification_method=verification_method,
        usefulness_state="requester_confirmed",
        usefulness_method="authenticated_requester_attestation",
        usefulness_evidence=payload.usefulness_evidence,
        semantic_eligible=semantic,
        eligibility_reason_code=eligibility_reason,
        participation_assessment_id=participation["assessment_id"],
        participation_classification_at_submission=participation["classification"],
        participation_reason_at_submission=participation["reason_code"],
        cost_state=cost_state,
        cost_amount=cost_amount,
        cost_currency=cost_currency,
        release_sha=identity["release_sha"],
        created_at=_utcnow(),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(models.Package5VuoProof).where(
                (models.Package5VuoProof.action_run_id == run.id)
                | (
                    (models.Package5VuoProof.canonical_requester_agent_id == canonical_id)
                    & (models.Package5VuoProof.idempotency_key == key)
                )
            )
        )
        if existing is None or existing.request_digest != digest:
            raise Package5ProofError(409, "vuo_candidate_conflict", "Concurrent VUO candidate conflict")
        return _serialize_vuo(db, existing, groups, replayed=True)
    db.refresh(row)
    return _serialize_vuo(db, row, groups)


def _serialize_vuo(db: Session, row: models.Package5VuoProof, groups: list[dict], *, replayed: bool = False) -> dict:
    group = _group_for_agent(groups, row.requester_agent_id)
    agents_by_id = {agent.id: agent for agent in db.scalars(select(models.Agent)).all()}
    participation = _classification_for_group(db, group, agents_by_id) if group else {
        "classification": "unknown_not_proven",
        "reason_code": "logical_identity_unavailable",
        "countable": False,
        "evidence_authority": "none",
        "assessment_id": None,
    }
    submission_participation_eligible = (
        row.participation_classification_at_submission == "independent_external_countable"
        and row.participation_assessment_id is not None
        and row.participation_reason_at_submission
        == _CLASSIFICATION_REASONS["independent_external_countable"]
    )
    qualifies = bool(
        row.semantic_eligible
        and submission_participation_eligible
        and participation["countable"]
    )
    return {
        "vuo_id": row.vuo_id,
        "canonical_requester_agent_id": group["canonical_agent_id"] if group else row.canonical_requester_agent_id,
        "goal_kind": row.goal_kind,
        "outcome_verification": {
            "state": row.outcome_verification_state,
            "method": row.outcome_verification_method,
        },
        "usefulness_evidence": {
            "state": row.usefulness_state,
            "method": row.usefulness_method,
        },
        "participation": participation,
        "semantic_eligible": row.semantic_eligible,
        "eligibility_reason_code": row.eligibility_reason_code,
        "participation_countable_at_submission": submission_participation_eligible,
        "participation_assessment_id": row.participation_assessment_id,
        "qualifies_as_package5_vuo": qualifies,
        "cost": {"state": row.cost_state, "amount": row.cost_amount, "currency": row.cost_currency},
        "created_at": row.created_at.isoformat(),
        "release_sha": row.release_sha,
        "idempotent_replay": replayed,
        "limitations": [
            "Usefulness is authenticated-requester-confirmed, not independent third-party verification.",
            "A Package 3 callability result is not a VUO without this separate semantic acknowledgement and countable participation evidence.",
        ],
    }


def _qualifying_vuo_return_state(
    db: Session,
    *,
    groups: list[dict],
    classifications: dict[int, dict],
    proofs: list[models.Package5VuoProof],
) -> dict:
    """Derive Package 5 qualifying VUO and same-identity return truth once."""

    group_by_raw = {row_id: group for group in groups for row_id in group["row_ids"]}
    qualifying = []
    vuo_reasons = Counter()
    for proof in proofs:
        group = group_by_raw.get(proof.requester_agent_id)
        participation = classifications.get(group["canonical_agent_id"]) if group else None
        if not proof.semantic_eligible:
            vuo_reasons[proof.eligibility_reason_code] += 1
        elif not (
            proof.participation_classification_at_submission == "independent_external_countable"
            and proof.participation_assessment_id is not None
            and proof.participation_reason_at_submission
            == _CLASSIFICATION_REASONS["independent_external_countable"]
        ):
            vuo_reasons["participation_not_countable_at_vuo_submission"] += 1
        elif not participation or not participation["countable"]:
            vuo_reasons[(participation or {}).get("reason_code", "logical_identity_unavailable")] += 1
        else:
            qualifying.append((proof, group["canonical_agent_id"]))
            vuo_reasons["qualifying_package5_vuo"] += 1

    qualifying_by_identity: dict[int, list[models.Package5VuoProof]] = {}
    for proof, canonical_id in qualifying:
        qualifying_by_identity.setdefault(canonical_id, []).append(proof)
    action_runs = list(db.scalars(select(models.ActionRun).order_by(models.ActionRun.created_at, models.ActionRun.id)).all())
    actions_by_identity: dict[int, list[models.ActionRun]] = {}
    for action in action_runs:
        group = group_by_raw.get(action.requester_agent_id)
        if group is not None:
            actions_by_identity.setdefault(group["canonical_agent_id"], []).append(action)
    threshold = _return_threshold_seconds()
    returning = set()
    return_reasons = Counter()
    for canonical_id, identity_proofs in qualifying_by_identity.items():
        earliest = min(identity_proofs, key=lambda item: _aware(item.created_at))
        eligible_after = _aware(earliest.created_at) + timedelta(seconds=threshold)
        later = [
            action for action in actions_by_identity.get(canonical_id, [])
            if action.id != earliest.action_run_id and _aware(action.created_at) >= eligible_after
        ]
        if later:
            returning.add(canonical_id)
            return_reasons["later_authenticated_action_after_threshold_no_known_exclusion"] += 1
        else:
            return_reasons["no_later_meaningful_use_after_threshold"] += 1
    return {
        "qualifying": qualifying,
        "vuo_reasons": vuo_reasons,
        "qualifying_by_identity": qualifying_by_identity,
        "action_runs": action_runs,
        "returning": returning,
        "return_reasons": return_reasons,
        "threshold": threshold,
    }


def qualifying_return_identity_ids(db: Session) -> set[int]:
    """Return canonical identities satisfying the canonical Package 5 rule."""

    proofs_count = db.scalar(select(func.count()).select_from(models.Package5VuoProof)) or 0
    if proofs_count > MAX_PROOF_VUO_CANDIDATES:
        raise Package5ProofError(503, "proof_resource_limit", "Package 5 VUO input exceeds the single-instance V1 bound")
    groups = _bounded_logical_groups(db)
    agents_by_id = {agent.id: agent for agent in db.scalars(select(models.Agent)).all()}
    classifications = {
        group["canonical_agent_id"]: _classification_for_group(db, group, agents_by_id)
        for group in groups
    }
    proofs = list(db.scalars(select(models.Package5VuoProof).order_by(models.Package5VuoProof.id)).all())
    return _qualifying_vuo_return_state(
        db, groups=groups, classifications=classifications, proofs=proofs
    )["returning"]


def package5_proof_snapshot(db: Session) -> dict:
    raw_agents = db.scalar(select(func.count()).select_from(models.Agent)) or 0
    vuo_candidates = db.scalar(select(func.count()).select_from(models.Package5VuoProof)) or 0
    limits = {
        "maximum_raw_agent_rows": MAX_PROOF_RAW_AGENT_ROWS,
        "maximum_logical_identities": MAX_PROOF_LOGICAL_IDENTITIES,
        "maximum_vuo_candidates": MAX_PROOF_VUO_CANDIDATES,
    }
    if raw_agents > MAX_PROOF_RAW_AGENT_ROWS or vuo_candidates > MAX_PROOF_VUO_CANDIDATES:
        return {
            "package": 5,
            "status": "proof_unavailable_resource_limit",
            "commercial_proof_established": False,
            "limits": limits,
            "reason_code": "proof_dataset_exceeds_single_instance_v1_bound",
        }

    groups = logical_groups(db)
    if len(groups) > MAX_PROOF_LOGICAL_IDENTITIES:
        return {
            "package": 5,
            "status": "proof_unavailable_resource_limit",
            "commercial_proof_established": False,
            "limits": limits,
            "reason_code": "proof_dataset_exceeds_single_instance_v1_bound",
        }
    agents_by_id = {agent.id: agent for agent in db.scalars(select(models.Agent)).all()}
    classifications = {
        group["canonical_agent_id"]: _classification_for_group(db, group, agents_by_id)
        for group in groups
    }
    class_breakdown = Counter(item["classification"] for item in classifications.values())
    reason_breakdown = Counter(item["reason_code"] for item in classifications.values())
    proofs = list(db.scalars(select(models.Package5VuoProof).order_by(models.Package5VuoProof.id)).all())
    evidence = _qualifying_vuo_return_state(
        db, groups=groups, classifications=classifications, proofs=proofs
    )
    qualifying = evidence["qualifying"]
    vuo_reasons = evidence["vuo_reasons"]
    qualifying_by_identity = evidence["qualifying_by_identity"]
    action_runs = evidence["action_runs"]
    returning = evidence["returning"]
    return_reasons = evidence["return_reasons"]
    threshold = evidence["threshold"]

    total_vuos = len(qualifying)
    cost_breakdown = Counter(proof.cost_state for proof, _ in qualifying)
    known_costs = [
        (Decimal(proof.cost_amount), proof.cost_currency)
        for proof, _ in qualifying
        if proof.cost_state in {"known_zero", "known_nonzero"}
        and proof.cost_amount is not None
        and proof.cost_currency is not None
    ]
    currencies = {currency for _, currency in known_costs}
    if total_vuos == 0:
        cost_per_vuo = {"state": "no_qualifying_vuos", "amount": None, "currency": None}
    elif len(known_costs) != total_vuos:
        cost_per_vuo = {"state": "unknown", "amount": None, "currency": None}
    elif len(currencies) != 1:
        cost_per_vuo = {"state": "mixed_currencies", "amount": None, "currency": None}
    else:
        total_cost = sum((amount for amount, _ in known_costs), Decimal("0"))
        cost_per_vuo = {
            "state": "known",
            "amount": str(total_cost / Decimal(total_vuos)),
            "currency": next(iter(currencies)),
        }
    repeat_identities = sum(1 for rows in qualifying_by_identity.values() if len(rows) >= 2)
    repeat_vuos = sum(max(0, len(rows) - 1) for rows in qualifying_by_identity.values())
    independent_count = sum(1 for item in classifications.values() if item["countable"])
    counts = {
        "independent_logical_identities": independent_count,
        "identities_with_qualifying_vuo": len(qualifying_by_identity),
        "qualifying_vuos": total_vuos,
        "identities_with_qualifying_return": len(returning),
        "repeat_vuo_identities": repeat_identities,
        "repeat_vuos": repeat_vuos,
        "stored_vuo_candidates": len(proofs),
    }
    action_ids = {
        run.id: run.action_id
        for run in action_runs
    }
    qualifying_records = [
        {
            "vuo_id": proof.vuo_id,
            "canonical_requester_agent_id": canonical_id,
            "action_id": action_ids.get(proof.action_run_id),
            "goal_kind": proof.goal_kind,
            "participation_assessment_id": proof.participation_assessment_id,
            "product_goal": proof.product_goal,
            "delivered_outcome": proof.delivered_outcome,
            "outcome_verification": {
                "state": proof.outcome_verification_state,
                "method": proof.outcome_verification_method,
            },
            "usefulness_evidence": {
                "state": proof.usefulness_state,
                "method": proof.usefulness_method,
            },
            "cost": {
                "state": proof.cost_state,
                "amount": proof.cost_amount,
                "currency": proof.cost_currency,
            },
            "created_at": proof.created_at.isoformat(),
            "release_sha": proof.release_sha,
        }
        for proof, canonical_id in qualifying
    ]
    return {
        "package": 5,
        "status": "evidence_snapshot",
        "commercial_proof_established": len(returning) >= 10,
        "counts": counts,
        "progress": {
            "one_independent_agent": {"target": 1, "current": independent_count, "achieved": independent_count >= 1},
            "one_qualifying_vuo": {"target": 1, "current": total_vuos, "achieved": total_vuos >= 1},
            "one_qualifying_return": {"target": 1, "current": len(returning), "achieved": len(returning) >= 1},
            "ten_independent_returning_agents": {"target": 10, "current": len(returning), "achieved": len(returning) >= 10},
        },
        "participation_evidence": {
            "classification_breakdown": dict(sorted(class_breakdown.items())),
            "reason_code_breakdown": dict(sorted(reason_breakdown.items())),
            "logical_identity_count": len(groups),
            "duplicate_raw_rows": sum(max(0, group["raw_rows"] - 1) for group in groups),
        },
        "vuo_evidence": {
            "reason_code_breakdown": dict(sorted(vuo_reasons.items())),
            "usefulness_method": "authenticated_requester_attestation",
            "automatic_callability_conversion": False,
            "qualifying_records": qualifying_records,
        },
        "return_evidence": {
            "threshold_seconds": threshold,
            "meaningful_event": "new_authenticated_idempotent_action_run",
            "reason_code_breakdown": dict(sorted(return_reasons.items())),
            "last_seen_at_used": False,
            "client_timestamp_used": False,
        },
        "cost_evidence": {
            "known_zero_vuos": cost_breakdown["known_zero"],
            "known_nonzero_vuos": cost_breakdown["known_nonzero"],
            "unknown_vuos": cost_breakdown["unknown"],
            "cost_per_vuo": cost_per_vuo,
        },
        "definitions": {
            "independent": "operator-reviewed external evidence with no known AION-operated, synthetic, probe, design-partner, invited, or coordinated marker",
            "vuo": "countable independent identity plus a concrete callability product goal, server-verified underlying outcome, and separate authenticated requester confirmation of usefulness",
            "voluntary_return": "later meaningful authenticated requester action after a qualifying VUO and threshold, with no known internal, synthetic, probe, or coordinated marker",
        },
        "limits": limits,
        "limitations": [
            "Engineering tests, fixtures, historical rows, and coordinated activity are not commercial proof.",
            "Requester-confirmed usefulness is not independent third-party verification.",
            "The V1 meaningful-return event is a new durable ActionRun; health, readiness, status, telemetry, and last_seen_at never qualify.",
            "No owner, model vendor, KYC, payment settlement, revenue, or production outreach is inferred.",
        ],
    }
