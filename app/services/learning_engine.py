"""Package 3B V1: bounded one-shot learning, evidence and opportunity services."""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import threading
import time
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app import models, schemas
from app.db import SessionLocal
from app.services.live_utility_engine import LiveUtilityEngine, RefreshResult, RefreshStatus
from app.services.live_utility_sources import configured_tier1_adapters
from app.services import live_utility_store
from app.services.rate_limit import allow_evidence_submission, configured_evidence_limit


WATCHED_SOURCE_IDS = (
    "official-a2a-protocol-release",
    "official-mcp-specification-release",
)
MAX_WATCHED_SOURCES_PER_CYCLE = 2
MAX_CONCURRENT_REFRESHES = 1
MAX_OUTBOUND_ATTEMPTS_PER_CYCLE = 4
MAX_OUTBOUND_ATTEMPTS_PER_SOURCE = 2
MAX_RESPONSE_BYTES_PER_SOURCE = 256_000
MAX_STORED_NORMALIZED_BYTES = 16 * 1024
MAX_CYCLE_SECONDS = 40
MIN_REFRESH_INTERVAL_SECONDS = 5 * 60
FAILURE_RETRY_SECONDS = 60
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 15 * 60
SOURCE_CLAIM_SECONDS = 60
MAX_AGENT_EVIDENCE_PROCESSING = 100
MAX_ACTION_SIGNALS_PROCESSING = 200
MAX_OPPORTUNITIES_RECOMPUTED = 20
MAX_DURABLE_OPPORTUNITIES = 100
MAX_SUPPORTING_REFERENCES = 20
MAX_LEARNING_SUMMARY_BYTES = 64 * 1024
MAX_PAID_EXTERNAL_SPEND = 0
IDEMPOTENCY_KEY_MAX_LENGTH = 128

GENUINE_DEMAND_FAILURE_CLASSES = frozenset(
    {"no_result", "capability_not_found", "incompatible"}
)
OPERATIONAL_FAILURE_CLASSES = frozenset(
    {
        "rate_limited",
        "unavailable",
        "endpoint_unreachable",
        "transient_transport_failure",
        "protocol_failure",
        "invocation_failed",
        "verification_failed",
        "unknown_delivery_state",
    }
)

_TRIGGERS = frozenset({"scheduled", "operator", "demand", "usage", "impact", "test"})
_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_NORMALIZE_PATTERN = re.compile(r"[^a-z0-9._:-]+")
_SQLITE_EVIDENCE_LOCK = threading.RLock()
_SQLITE_WATCH_LOCK = threading.RLock()
_SQLITE_OPPORTUNITY_LOCK = threading.RLock()


class LearningServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _digest(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _advisory_key(value: str) -> int:
    return int.from_bytes(
        hashlib.sha256(value.encode("utf-8")).digest()[:8], "big", signed=True
    )


def _idempotency_key(value: str | None) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > IDEMPOTENCY_KEY_MAX_LENGTH
        or not _IDEMPOTENCY_PATTERN.fullmatch(normalized)
    ):
        raise LearningServiceError(
            422,
            "invalid_idempotency_key",
            "Idempotency key must be 1-128 characters using letters, digits, '.', '_', ':' or '-'",
        )
    return normalized


def _evidence_values(payload: schemas.AgentEvidenceSubmission) -> tuple[dict, dict]:
    request = payload.model_dump(mode="json")
    material = dict(request)
    material.pop("observed_at", None)
    return request, material


def _serialize_claim(row: models.AgentEvidenceClaim, *, replayed: bool = False) -> dict:
    return {
        "claim_id": row.claim_id,
        "requester_agent_id": row.requester_agent_id,
        "category": row.category,
        "subject_key": row.subject_key,
        "description": row.description,
        "reference_url": row.reference_url,
        "provider_identifier": row.provider_identifier,
        "protocol": row.protocol,
        "failure_class": row.failure_class,
        "observed_at": _utc(row.observed_at).isoformat() if row.observed_at else None,
        "submitted_at": _utc(row.submitted_at).isoformat(),
        "evidence_digest": row.evidence_digest,
        "evidence_state": row.state,
        "corroborating_agent_count": row.corroborating_agent_count,
        "supporting_references": list(row.supporting_references or []),
        "idempotent_replay": replayed,
        "trust_boundary": "agent_claim_is_untrusted_and_not_verified_truth",
        "reference_url_contacted": False,
        "reputation_updated": False,
        "limits": {
            "description_characters": 2000,
            "reference_url_characters": 1000,
            "per_agent_rate_per_minute": configured_evidence_limit(),
            "outer_request_bytes": 64 * 1024,
        },
    }


def submit_agent_evidence(
    requester_agent_id: int,
    payload: schemas.AgentEvidenceSubmission,
    idempotency_key: str | None,
) -> dict:
    """Store bounded untrusted evidence without retrieving any supplied URL."""

    normalized_key = _idempotency_key(idempotency_key)
    request, material = _evidence_values(payload)
    request_digest = _digest(request)
    evidence_digest = _digest(material)

    def claim_once() -> tuple[models.AgentEvidenceClaim, bool]:
        with SessionLocal() as db:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": _advisory_key(f"evidence:{requester_agent_id}:{normalized_key}")},
                )
            existing = db.scalar(
                select(models.AgentEvidenceClaim).where(
                    models.AgentEvidenceClaim.requester_agent_id == requester_agent_id,
                    models.AgentEvidenceClaim.idempotency_key == normalized_key,
                )
            )
            if existing is not None:
                if existing.request_digest != request_digest:
                    raise LearningServiceError(
                        409,
                        "idempotency_conflict",
                        "The idempotency key is already bound to different evidence",
                    )
                return existing, False
            duplicate = db.scalar(
                select(models.AgentEvidenceClaim).where(
                    models.AgentEvidenceClaim.requester_agent_id == requester_agent_id,
                    models.AgentEvidenceClaim.evidence_digest == evidence_digest,
                )
            )
            if duplicate is not None:
                raise LearningServiceError(
                    409,
                    "duplicate_material_claim",
                    "This agent already submitted the same material claim",
                )
            if not allow_evidence_submission(requester_agent_id):
                raise LearningServiceError(
                    429,
                    "evidence_rate_limited",
                    f"Evidence intake rate limit exceeded ({configured_evidence_limit()}/minute)",
                )
            now = datetime.now(timezone.utc)
            row = models.AgentEvidenceClaim(
                claim_id=str(uuid.uuid4()),
                requester_agent_id=requester_agent_id,
                idempotency_key=normalized_key,
                request_digest=request_digest,
                evidence_digest=evidence_digest,
                category=payload.category,
                subject_key=payload.subject_key.strip().lower(),
                description=payload.description,
                reference_url=payload.reference_url,
                provider_identifier=payload.provider_identifier,
                protocol=payload.protocol,
                failure_class=payload.failure_class,
                observed_at=payload.observed_at,
                submitted_at=now,
                state="unverified",
                corroborating_agent_count=1,
                supporting_references=[],
            )
            db.add(row)
            db.flush()
            peers = list(
                db.scalars(
                    select(models.AgentEvidenceClaim).where(
                        models.AgentEvidenceClaim.evidence_digest == evidence_digest,
                        models.AgentEvidenceClaim.state.in_(("unverified", "corroborated")),
                    )
                )
            )
            distinct_agents = sorted({peer.requester_agent_id for peer in peers})
            references = sorted(peer.claim_id for peer in peers)[:MAX_SUPPORTING_REFERENCES]
            if len(distinct_agents) >= 2:
                for peer in peers:
                    peer.state = "corroborated"
                    peer.corroborating_agent_count = len(distinct_agents)
                    peer.supporting_references = references
                    db.add(peer)
            db.commit()
            db.refresh(row)
            return row, True

    with SessionLocal() as probe:
        guard = _SQLITE_EVIDENCE_LOCK if probe.get_bind().dialect.name == "sqlite" else nullcontext()
    try:
        with guard:
            row, created = claim_once()
    except IntegrityError:
        with SessionLocal() as db:
            row = db.scalar(
                select(models.AgentEvidenceClaim).where(
                    models.AgentEvidenceClaim.requester_agent_id == requester_agent_id,
                    models.AgentEvidenceClaim.idempotency_key == normalized_key,
                )
            )
            if row is None:
                duplicate = db.scalar(
                    select(models.AgentEvidenceClaim).where(
                        models.AgentEvidenceClaim.requester_agent_id == requester_agent_id,
                        models.AgentEvidenceClaim.evidence_digest == evidence_digest,
                    )
                )
                if duplicate is not None:
                    raise LearningServiceError(
                        409,
                        "duplicate_material_claim",
                        "This agent already submitted the same material claim",
                    )
                raise
            if row.request_digest != request_digest:
                raise LearningServiceError(409, "idempotency_conflict", "The idempotency key is already bound to different evidence")
            return _serialize_claim(row, replayed=True)
    return _serialize_claim(row, replayed=not created)


def _normalize_demand_key(value: str) -> str:
    normalized = _NORMALIZE_PATTERN.sub("-", str(value).strip().lower()).strip("-")
    return normalized[:120] or "unknown"


def _serialize_candidate(row: models.LearningOpportunityCandidate) -> dict:
    return {
        "candidate_key": row.candidate_key,
        "normalized_demand_key": row.normalized_demand_key,
        "first_seen_at": _utc(row.first_seen_at).isoformat(),
        "last_seen_at": _utc(row.last_seen_at).isoformat(),
        "total_meaningful_signals": row.total_meaningful_signals,
        "distinct_requester_count": row.distinct_requester_count,
        "repeat_requester_count": row.repeat_requester_count,
        "anonymous_signal_count": row.anonymous_signal_count,
        "failure_class_breakdown": dict(row.failure_class_breakdown),
        "operational_failure_breakdown": dict(row.operational_failure_breakdown),
        "supporting_evidence_references": list(row.supporting_evidence_references),
        "evidence_state": row.evidence_state,
        "status": row.status,
        "priority_score": row.priority_score,
        "known_provider_availability": row.known_provider_availability or "unknown",
        "payment_potential": row.payment_potential or "unknown",
        "known_cost": row.known_cost or "unknown",
        "margin_feasibility": row.margin_feasibility or "unknown",
        "last_evaluated_at": _utc(row.last_evaluated_at).isoformat(),
        "decision_support_only": True,
    }


def recompute_opportunity_candidates(now: datetime) -> list[dict]:
    """Aggregate bounded durable evidence; raw volume never drives priority."""

    grouped = defaultdict(lambda: {"meaningful": [], "operational": [], "agents": Counter(), "times": []})
    with SessionLocal() as db:
        actions = list(
            db.scalars(
                select(models.ActionRun)
                .where(models.ActionRun.completed_at.is_not(None))
                .order_by(models.ActionRun.completed_at.desc(), models.ActionRun.id.desc())
                .limit(MAX_ACTION_SIGNALS_PROCESSING)
            )
        )
        claims = list(
            db.scalars(
                select(models.AgentEvidenceClaim)
                .where(models.AgentEvidenceClaim.state.in_(("unverified", "corroborated", "verified")))
                .order_by(models.AgentEvidenceClaim.submitted_at.desc(), models.AgentEvidenceClaim.id.desc())
                .limit(MAX_AGENT_EVIDENCE_PROCESSING)
            )
        )
    for action in actions:
        key = _normalize_demand_key(action.requested_query)
        when = _utc(action.completed_at) or _utc(action.created_at)
        if action.failure_class in GENUINE_DEMAND_FAILURE_CLASSES:
            grouped[key]["meaningful"].append((f"action:{action.action_id}", action.failure_class))
            grouped[key]["agents"][action.requester_agent_id] += 1
            grouped[key]["times"].append(when)
        elif action.failure_class in OPERATIONAL_FAILURE_CLASSES:
            grouped[key]["operational"].append((f"action:{action.action_id}", action.failure_class))
    for claim in claims:
        key = _normalize_demand_key(claim.subject_key)
        if claim.category == "missing_capability":
            grouped[key]["meaningful"].append((f"claim:{claim.claim_id}", "missing_capability"))
            grouped[key]["agents"][claim.requester_agent_id] += 1
            grouped[key]["times"].append(_utc(claim.observed_at) or _utc(claim.submitted_at))
        elif claim.category == "provider_failure" and claim.failure_class in OPERATIONAL_FAILURE_CLASSES:
            grouped[key]["operational"].append((f"claim:{claim.claim_id}", claim.failure_class))

    candidates = []
    for key, evidence in grouped.items():
        if not evidence["meaningful"]:
            continue
        distinct = len(evidence["agents"])
        repeat = sum(1 for count in evidence["agents"].values() if count >= 2)
        first_seen = min(evidence["times"])
        last_seen = max(evidence["times"])
        age = max(0, int((now - last_seen).total_seconds()))
        recency = 20 if age <= 7 * 86400 else 10 if age <= 30 * 86400 else 0
        confidence = "corroborated" if distinct >= 2 else "limited"
        priority = distinct * 100 + repeat * 20 + recency + (20 if distinct >= 2 else 0)
        candidates.append(
            {
                "candidate_key": _digest({"demand_key": key}),
                "key": key,
                "first_seen": first_seen,
                "last_seen": last_seen,
                "total": len(evidence["meaningful"]),
                "distinct": distinct,
                "repeat": repeat,
                "failures": dict(Counter(kind for _, kind in evidence["meaningful"])),
                "operational": dict(Counter(kind for _, kind in evidence["operational"])),
                "references": sorted(ref for ref, _ in evidence["meaningful"])[:MAX_SUPPORTING_REFERENCES],
                "confidence": confidence,
                "priority": priority,
            }
        )
    candidates.sort(key=lambda item: (-item["priority"], item["candidate_key"]))
    selected = candidates[:MAX_OPPORTUNITIES_RECOMPUTED]

    def persist() -> list[dict]:
        with SessionLocal() as db:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _advisory_key("learning:opportunity-recompute")})
            count = db.scalar(select(func.count()).select_from(models.LearningOpportunityCandidate)) or 0
            rows = []
            for item in selected:
                row = db.scalar(
                    select(models.LearningOpportunityCandidate).where(
                        models.LearningOpportunityCandidate.candidate_key == item["candidate_key"]
                    )
                )
                if row is None:
                    if count >= MAX_DURABLE_OPPORTUNITIES:
                        continue
                    row = models.LearningOpportunityCandidate(
                        candidate_key=item["candidate_key"],
                        normalized_demand_key=item["key"],
                        first_seen_at=item["first_seen"],
                        known_provider_availability=None,
                        payment_potential=None,
                        known_cost=None,
                        margin_feasibility=None,
                        anonymous_signal_count=0,
                    )
                    count += 1
                row.last_seen_at = item["last_seen"]
                row.total_meaningful_signals = item["total"]
                row.distinct_requester_count = item["distinct"]
                row.repeat_requester_count = item["repeat"]
                row.anonymous_signal_count = 0
                row.failure_class_breakdown = item["failures"]
                row.operational_failure_breakdown = item["operational"]
                row.supporting_evidence_references = item["references"]
                row.evidence_state = item["confidence"]
                row.status = "candidate"
                row.priority_score = item["priority"]
                row.last_evaluated_at = now
                row.updated_at = now
                db.add(row)
                rows.append(row)
            db.commit()
            for row in rows:
                db.refresh(row)
            return [_serialize_candidate(row) for row in rows]

    with SessionLocal() as probe:
        guard = _SQLITE_OPPORTUNITY_LOCK if probe.get_bind().dialect.name == "sqlite" else nullcontext()
    with guard:
        return persist()


def _failure_class(result: RefreshResult) -> str:
    if result.error == "http_429":
        return "rate_limited"
    if result.status == RefreshStatus.VALIDATION_FAILED:
        return "validation_failed"
    if result.status == RefreshStatus.DISABLED:
        return "disabled"
    if result.error == "request_budget_exceeded":
        return "budget_exhausted"
    return "unavailable"


def _claim_source(engine: LiveUtilityEngine, adapter, now: datetime, demand: bool, token: str) -> tuple[str, models.LearningSourceWatchState | None]:
    source_id = adapter.source.source_id

    def claim():
        with SessionLocal() as db:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _advisory_key(f"learning-watch:{source_id}")})
            row = db.scalar(select(models.LearningSourceWatchState).where(models.LearningSourceWatchState.source_id == source_id))
            if row is None:
                row = models.LearningSourceWatchState(
                    source_id=source_id,
                    consecutive_failures=0,
                    outbound_attempts_total=0,
                    response_bytes_total=0,
                    updated_at=now,
                )
                db.add(row)
                db.flush()
            durable_source = db.scalar(
                select(models.LiveUtilitySource).where(
                    models.LiveUtilitySource.source_id == source_id
                )
            )
            if durable_source is None or not durable_source.enabled:
                row.last_failure_class = "disabled"
                row.updated_at = now
                db.commit()
                return "disabled", None
            circuit_until = _utc(row.circuit_open_until)
            if circuit_until is not None and circuit_until > now:
                db.commit()
                return "circuit_open", None
            claim_until = _utc(row.claim_expires_at)
            if row.claim_token and claim_until is not None and claim_until > now:
                db.commit()
                return "source_busy", None
            next_at = _utc(row.next_eligible_refresh_at)
            if next_at is not None and next_at > now:
                db.commit()
                return "not_due", None
            current = engine.get_current_state(db, source_id=source_id, subject_key=adapter.subject_key, now=now)
            if current is not None and not current.freshness.refresh_required and not demand:
                row.next_eligible_refresh_at = max(now + timedelta(seconds=MIN_REFRESH_INTERVAL_SECONDS), current.observation.stale_after)
                row.updated_at = now
                db.commit()
                return "not_due", None
            row.claim_token = token
            row.claim_expires_at = now + timedelta(seconds=SOURCE_CLAIM_SECONDS)
            row.updated_at = now
            db.commit()
            return "claimed", None

    with SessionLocal() as probe:
        guard = _SQLITE_WATCH_LOCK if probe.get_bind().dialect.name == "sqlite" else nullcontext()
    with guard:
        return claim()


def _finish_source(source_id: str, token: str, now: datetime, result: RefreshResult, response_bytes: int) -> None:
    with SessionLocal() as db:
        row = db.scalar(select(models.LearningSourceWatchState).where(models.LearningSourceWatchState.source_id == source_id))
        if row is None or row.claim_token != token:
            return
        row.last_checked_at = now
        row.outbound_attempts_total += max(0, result.attempts)
        row.response_bytes_total += max(0, response_bytes)
        row.claim_token = None
        row.claim_expires_at = None
        if result.status in {RefreshStatus.REFRESHED_CHANGED, RefreshStatus.REFRESHED_UNCHANGED}:
            row.last_success_at = now
            row.consecutive_failures = 0
            row.circuit_open_until = None
            row.last_failure_class = None
            if result.current_state is not None:
                row.last_observation_id = result.current_state.observation.observation_id
                row.next_eligible_refresh_at = max(
                    now + timedelta(seconds=MIN_REFRESH_INTERVAL_SECONDS),
                    result.current_state.observation.stale_after,
                )
            if result.status == RefreshStatus.REFRESHED_CHANGED and result.change is not None:
                row.last_material_change_observation_id = result.change.observation_id
        else:
            row.consecutive_failures += 1
            row.last_failure_class = _failure_class(result)
            row.next_eligible_refresh_at = now + timedelta(seconds=FAILURE_RETRY_SECONDS)
            if row.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
                row.circuit_open_until = now + timedelta(seconds=CIRCUIT_COOLDOWN_SECONDS)
        row.updated_at = now
        db.add(row)
        db.commit()


def run_learning_cycle(
    now: datetime,
    trigger_context: dict | None = None,
    *,
    adapters=None,
    monotonic=time.monotonic,
) -> dict:
    """Run one deterministic bounded cycle; it never schedules itself."""

    now = _utc(now)
    if now is None:
        raise ValueError("now is required")
    context = dict(trigger_context or {})
    if set(context) - {"trigger", "source_ids"}:
        raise ValueError("trigger_context permits only trigger and source_ids")
    trigger = str(context.get("trigger") or "scheduled")
    if trigger not in _TRIGGERS:
        raise ValueError("unsupported learning trigger")
    requested_sources = context.get("source_ids") or []
    if not isinstance(requested_sources, list) or len(requested_sources) > MAX_WATCHED_SOURCES_PER_CYCLE:
        raise ValueError("source_ids must be a list bounded to the configured watch set")
    if any(source_id not in WATCHED_SOURCE_IDS for source_id in requested_sources):
        raise ValueError("only configured Tier-1 watched sources may be selected")

    configured = tuple(adapters or configured_tier1_adapters())
    selected = tuple(
        adapter for adapter in configured
        if adapter.source.source_id in WATCHED_SOURCE_IDS
        and (not requested_sources or adapter.source.source_id in requested_sources)
    )[:MAX_WATCHED_SOURCES_PER_CYCLE]
    engine = LiveUtilityEngine(selected)
    with SessionLocal.begin() as db:
        for adapter in selected:
            existing = live_utility_store.get_source(db, adapter.source.source_id)
            if existing is None:
                live_utility_store.register_source(db, adapter.source)
            elif replace(existing, enabled=adapter.source.enabled) != adapter.source:
                raise ValueError(
                    f"durable source configuration mismatch: {adapter.source.source_id}"
                )

    run_id = str(uuid.uuid4())
    with SessionLocal.begin() as db:
        db.add(models.LearningRun(
            run_id=run_id,
            trigger=trigger,
            state="running",
            started_at=now,
            sources_considered=len(selected),
            outbound_attempts=0,
            response_bytes=0,
            paid_external_spend_permitted=False,
            summary=None,
        ))

    start = monotonic()
    statuses = []
    total_attempts = 0
    total_bytes = 0
    for adapter in selected:
        source_id = adapter.source.source_id
        if monotonic() - start >= MAX_CYCLE_SECONDS:
            statuses.append({"source_id": source_id, "status": "budget_exhausted", "reason": "cycle_time"})
            continue
        declared_cost = getattr(adapter, "external_cost_amount", 0)
        if declared_cost not in {0, "0", "0.0"}:
            statuses.append({"source_id": source_id, "status": "disabled", "reason": "paid_external_spend_disabled"})
            continue
        if (
            adapter.fetch_policy.max_attempts > MAX_OUTBOUND_ATTEMPTS_PER_SOURCE
            or total_attempts + adapter.fetch_policy.max_attempts > MAX_OUTBOUND_ATTEMPTS_PER_CYCLE
        ):
            statuses.append({"source_id": source_id, "status": "budget_exhausted", "reason": "outbound_attempt_budget"})
            continue
        token = str(uuid.uuid4())
        demand = trigger in {"demand", "usage", "impact"} and source_id in requested_sources
        claim_status, _ = _claim_source(engine, adapter, now, demand, token)
        if claim_status != "claimed":
            statuses.append({"source_id": source_id, "status": claim_status})
            continue
        try:
            response = adapter.retrieve()
            response_bytes = len(response.transport.body or b"")
            if response_bytes > MAX_RESPONSE_BYTES_PER_SOURCE:
                result = RefreshResult(
                    RefreshStatus.FETCH_FAILED,
                    source_id,
                    adapter.subject_key,
                    response.transport.attempts,
                    None,
                    error="response_too_large",
                )
            else:
                normalized_too_large = False
                if response.transport.error is None:
                    try:
                        normalized_preview = adapter.normalize(response.payload)
                        normalized_too_large = len(json.dumps(
                            normalized_preview, sort_keys=True, separators=(",", ":")
                        ).encode("utf-8")) > MAX_STORED_NORMALIZED_BYTES
                    except Exception:
                        pass
                if normalized_too_large:
                    result = RefreshResult(
                        RefreshStatus.VALIDATION_FAILED,
                        source_id,
                        adapter.subject_key,
                        response.transport.attempts,
                        None,
                        error="normalized_payload_too_large",
                    )
                else:
                    with SessionLocal.begin() as db:
                        result = engine.refresh_source(
                            db,
                            source_id=source_id,
                            now=now,
                            demand=demand,
                            retrieved_response=response,
                        )
        except Exception as exc:
            result = RefreshResult(
                RefreshStatus.FETCH_FAILED,
                source_id,
                adapter.subject_key,
                0,
                None,
                error=f"fetch_exception:{type(exc).__name__}",
            )
            response_bytes = 0
        total_attempts += result.attempts
        total_bytes += response_bytes
        _finish_source(source_id, token, now, result, response_bytes)
        statuses.append({
            "source_id": source_id,
            "status": result.status.value,
            "attempts": result.attempts,
            "response_bytes": response_bytes,
            "observation_id": result.current_state.observation.observation_id if result.current_state else None,
            "material_change_observation_id": result.change.observation_id if result.change else None,
            "material_changes": [] if result.change is None else [
                {"field": change.field, "before": change.before, "after": change.after}
                for change in result.change.changes[:20]
            ],
            "failure_class": None if result.status in {RefreshStatus.REFRESHED_CHANGED, RefreshStatus.REFRESHED_UNCHANGED} else _failure_class(result),
        })

    opportunities = recompute_opportunity_candidates(now)
    counts = Counter(item["status"] for item in statuses)
    with SessionLocal() as db:
        evidence_processed = db.scalar(
            select(func.count()).select_from(models.AgentEvidenceClaim).where(
                models.AgentEvidenceClaim.state.in_(("unverified", "corroborated", "verified"))
            )
        ) or 0
        evidence_processed = min(evidence_processed, MAX_AGENT_EVIDENCE_PROCESSING)
        action_signals_processed = db.scalar(
            select(func.count()).select_from(models.ActionRun).where(
                models.ActionRun.completed_at.is_not(None)
            )
        ) or 0
        action_signals_processed = min(action_signals_processed, MAX_ACTION_SIGNALS_PROCESSING)
    summary = {
        "run_id": run_id,
        "trigger": trigger,
        "started_at": now.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "sources_considered": len(selected),
        "source_results": statuses,
        "refreshes_attempted": sum(1 for item in statuses if "attempts" in item),
        "changed_sources": counts[RefreshStatus.REFRESHED_CHANGED.value],
        "unchanged_sources": counts[RefreshStatus.REFRESHED_UNCHANGED.value],
        "failures": sum(counts[name] for name in ("fetch_failed", "validation_failed", "persistence_failed")),
        "skipped_not_due": counts["not_due"],
        "circuit_open": counts["circuit_open"],
        "disabled": counts["disabled"],
        "budget_exhausted": counts["budget_exhausted"],
        "resource_budget": {
            "watched_sources_limit": MAX_WATCHED_SOURCES_PER_CYCLE,
            "concurrent_refreshes": MAX_CONCURRENT_REFRESHES,
            "outbound_attempt_limit": MAX_OUTBOUND_ATTEMPTS_PER_CYCLE,
            "outbound_attempts_used": total_attempts,
            "response_bytes_per_source": MAX_RESPONSE_BYTES_PER_SOURCE,
            "stored_normalized_bytes_per_source": MAX_STORED_NORMALIZED_BYTES,
            "response_bytes_used": total_bytes,
            "cycle_seconds_limit": MAX_CYCLE_SECONDS,
            "minimum_refresh_interval_seconds": MIN_REFRESH_INTERVAL_SECONDS,
            "stored_summary_bytes_limit": MAX_LEARNING_SUMMARY_BYTES,
        },
        "paid_external_spend": {
            "permitted": False,
            "maximum": MAX_PAID_EXTERNAL_SPEND,
            "currency": None,
            "note": "No paid external variable spend is authorized; internal compute still has cost.",
        },
        "agent_evidence_processed": evidence_processed,
        "demand_signals_processed": action_signals_processed + evidence_processed,
        "demand_signals_processed_limit": MAX_ACTION_SIGNALS_PROCESSING + MAX_AGENT_EVIDENCE_PROCESSING,
        "opportunity_candidates_created_or_updated": len(opportunities),
        "opportunity_candidates": opportunities,
        "warnings": [
            "Agent claims remain untrusted unless separately verified.",
            "Opportunity candidates are decision support, not authorization to code, spend, merge or deploy.",
            "A2A evidence intake is deferred in V1.",
        ],
        "self_update_boundary": "bounded knowledge refresh and recomputation only; no autonomous code modification, merge or deployment",
    }
    while len(json.dumps(summary, sort_keys=True, separators=(",", ":")).encode("utf-8")) > MAX_LEARNING_SUMMARY_BYTES and summary["opportunity_candidates"]:
        summary["opportunity_candidates"].pop()
    with SessionLocal.begin() as db:
        row = db.scalar(select(models.LearningRun).where(models.LearningRun.run_id == run_id))
        row.state = "completed"
        row.completed_at = datetime.now(timezone.utc)
        row.outbound_attempts = total_attempts
        row.response_bytes = total_bytes
        row.summary = summary
        db.add(row)
    return summary
