"""Package 3 V1: one bounded external A2A callability action."""

from __future__ import annotations

from collections import deque
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import secrets
import threading
import time
import uuid

from google.protobuf.json_format import MessageToDict, ParseDict
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from a2a.types import (
    Message,
    Part,
    Role,
    SendMessageConfiguration,
    SendMessageRequest,
    SendMessageResponse,
)

from .. import models, schemas
from ..db import SessionLocal
from . import safe_http
from .external_registry import discover_external_agents_with_status


ACTION_TYPE = "a2a_callability_challenge_v1"
VERIFICATION_METHOD = "a2a_nonce_roundtrip_v1"
ACTION_RESPONSE_BYTE_LIMIT = 128 * 1024
ACTION_TIMEOUT_SECONDS = 5.0
ACTION_MAX_POST_ATTEMPTS = 1
ACTION_DISCOVERY_CANDIDATE_LIMIT = 5
ACTION_CONCURRENCY_LIMIT = max(
    1, min(int(os.getenv("AION_ACTION_CONCURRENCY", "4")), 16)
)
ACTION_RATE_LIMIT = max(1, int(os.getenv("AION_ACTION_RATE_PER_MINUTE", "20")))
ACTION_RATE_WINDOW_SECONDS = 60.0
IDEMPOTENCY_KEY_MAX_LENGTH = 128

_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]+$")
_ACTION_RATE_TIMES = deque()
_ACTION_RATE_LOCK = threading.Lock()
_ACTION_SLOTS = threading.BoundedSemaphore(ACTION_CONCURRENCY_LIMIT)
_SQLITE_CLAIM_LOCK = threading.RLock()
_ACTION_CONNECTION_FACTORY = safe_http.PinnedHTTPSConnection


class ActionServiceError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_json(value) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return _digest_bytes(encoded)


def _advisory_key(value: str) -> int:
    return int.from_bytes(
        hashlib.sha256(value.encode("utf-8")).digest()[:8], "big", signed=True
    )


def _normalized_idempotency_key(value: str | None) -> str:
    normalized = str(value or "").strip()
    if (
        not normalized
        or len(normalized) > IDEMPOTENCY_KEY_MAX_LENGTH
        or not _IDEMPOTENCY_PATTERN.fullmatch(normalized)
    ):
        raise ActionServiceError(
            422,
            "invalid_idempotency_key",
            "Idempotency key must be 1-128 characters using letters, digits, '.', '_', ':' or '-'",
        )
    return normalized


def _allow_action(now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    cutoff = current - ACTION_RATE_WINDOW_SECONDS
    with _ACTION_RATE_LOCK:
        while _ACTION_RATE_TIMES and _ACTION_RATE_TIMES[0] <= cutoff:
            _ACTION_RATE_TIMES.popleft()
        if len(_ACTION_RATE_TIMES) >= ACTION_RATE_LIMIT:
            return False
        _ACTION_RATE_TIMES.append(current)
        return True


def _request_fingerprint(payload: schemas.VerifyCallabilityRequest) -> tuple[str, bytes]:
    value = {
        "action_type": ACTION_TYPE,
        "query": payload.query,
        "candidate_identifier": payload.candidate_identifier,
        "authorize_external_contact": payload.authorize_external_contact,
    }
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return _digest_bytes(encoded), encoded


def _claim_action(
    requester_agent_id: int,
    payload: schemas.VerifyCallabilityRequest,
    idempotency_key: str,
):
    request_digest, request_bytes = _request_fingerprint(payload)
    action_id = str(uuid.uuid4())

    def claim_once():
        with SessionLocal() as db:
            if db.get_bind().dialect.name == "postgresql":
                lock_token = f"action:{requester_agent_id}:{idempotency_key}"
                db.execute(
                    text("SELECT pg_advisory_xact_lock(:lock_key)"),
                    {"lock_key": _advisory_key(lock_token)},
                )
            existing = db.scalar(
                select(models.ActionRun).where(
                    models.ActionRun.requester_agent_id == requester_agent_id,
                    models.ActionRun.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_digest != request_digest:
                    db.rollback()
                    raise ActionServiceError(
                        409,
                        "idempotency_conflict",
                        "The idempotency key is already bound to a different request",
                    )
                existing_id = existing.action_id
                db.commit()
                return existing_id, False

            now = _utcnow()
            row = models.ActionRun(
                action_id=action_id,
                requester_agent_id=requester_agent_id,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                requested_query=payload.query,
                requested_candidate_identifier=payload.candidate_identifier,
                authorize_external_contact=payload.authorize_external_contact,
                state="claimed",
                failure_class=None,
                created_at=now,
                started_at=now,
                discovery_attempt_count=0,
                action_attempt_count=0,
                request_bytes=len(request_bytes),
                response_bytes=None,
                cost_amount=None,
                cost_currency=None,
            )
            db.add(row)
            db.commit()
            return action_id, True

    with SessionLocal() as probe:
        local_guard = (
            _SQLITE_CLAIM_LOCK
            if probe.get_bind().dialect.name == "sqlite"
            else nullcontext()
        )
    try:
        with local_guard:
            return claim_once()
    except IntegrityError:
        # The unique requester/idempotency constraint is the final backstop for
        # writers that do not participate in the advisory-lock protocol.
        with SessionLocal() as db:
            existing = db.scalar(
                select(models.ActionRun).where(
                    models.ActionRun.requester_agent_id == requester_agent_id,
                    models.ActionRun.idempotency_key == idempotency_key,
                )
            )
            if existing is None:
                raise
            if existing.request_digest != request_digest:
                raise ActionServiceError(
                    409,
                    "idempotency_conflict",
                    "The idempotency key is already bound to a different request",
                )
            return existing.action_id, False


def _bounded_discovery_evidence(candidate: dict) -> dict:
    bounds = candidate.get("resource_bounds") or {}
    return {
        "evidence_state": candidate.get("evidence_state"),
        "manifest_reachable": bool(candidate.get("manifest_reachable")),
        "card_parseable": bool(candidate.get("card_parseable")),
        "declared_a2a_v1_jsonrpc": bool(candidate.get("declared_a2a_v1_jsonrpc")),
        "interaction_url_validated": bool(candidate.get("interaction_url_validated")),
        "authentication_requirement": candidate.get("authentication_requirement", "unknown"),
        "discovery_outbound_attempts": max(
            0, min(int(bounds.get("outbound_attempts_used") or 0), 12)
        ),
        "discovery_candidate_limit": ACTION_DISCOVERY_CANDIDATE_LIMIT,
    }


def _candidate_failure(candidates: list[dict], requested_identifier: str | None) -> str:
    if not candidates:
        return "no_result"
    relevant = candidates
    if requested_identifier is not None:
        relevant = [
            candidate
            for candidate in candidates
            if str(candidate.get("identifier") or "") == requested_identifier
        ]
        if not relevant:
            return "capability_not_found"
    if any(
        str(candidate.get("failure_reason") or "").startswith(
            ("non_public_address", "url_must_be_public_https", "nonstandard_port")
        )
        for candidate in relevant
    ):
        return "unsafe_destination"
    if any(not candidate.get("manifest_reachable") for candidate in relevant):
        return "endpoint_unreachable"
    if any(not candidate.get("declared_a2a_v1_jsonrpc") for candidate in relevant):
        return "incompatible"
    if any(
        candidate.get("authentication_requirement") != "none"
        for candidate in relevant
    ):
        return "permission_missing"
    return "unavailable"


def _select_candidate(candidates: list[dict], requested_identifier: str | None):
    relevant = candidates
    if requested_identifier is not None:
        relevant = [
            candidate
            for candidate in candidates
            if str(candidate.get("identifier") or "") == requested_identifier
        ]
    eligible = [
        candidate
        for candidate in relevant
        if candidate.get("manifest_reachable")
        and candidate.get("card_parseable")
        and candidate.get("declared_a2a_v1_jsonrpc")
        and candidate.get("interaction_url_validated")
        and candidate.get("authentication_requirement") == "none"
        and candidate.get("interaction_url")
    ]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda candidate: (
            str(candidate.get("identifier") or ""),
            str(candidate.get("interaction_url") or ""),
        ),
    )[0]


def _duration_ms(started_at: datetime | None, completed_at: datetime) -> int | None:
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return max(0, int((completed_at - started_at).total_seconds() * 1000))


def _complete_without_post(action_id: str, failure_class: str, discovery=None) -> dict:
    now = _utcnow()
    with SessionLocal() as db:
        run = db.scalar(
            select(models.ActionRun).where(models.ActionRun.action_id == action_id)
        )
        if run is None:
            raise ActionServiceError(404, "action_not_found", "Action run not found")
        run.state = "failed"
        run.failure_class = failure_class
        if discovery is not None:
            bounds = dict(discovery.resource_bounds)
            run.discovery_attempt_count = int(
                bounds.get("outbound_attempts_used") or 0
            )
            run.discovery_evidence = {
                "discovery_status": discovery.status,
                "failure_class": discovery.failure_class,
                "resource_bounds": bounds,
            }
        run.completed_at = now
        run.duration_ms = _duration_ms(run.started_at, now)
        outcome = models.ActionOutcome(
            action_run_id=run.id,
            outcome_type=failure_class,
            protocol_response_received=False,
            callability_verified=False,
            capability_verified=False,
            verified_outcome=False,
            normalized_result_kind=None,
            failure_class=failure_class,
            response_digest=None,
            protocol_task_id=None,
            protocol_message_id=None,
            proof_present=False,
            completed_at=now,
        )
        db.add(run)
        db.add(outcome)
        db.flush()
        db.add(
            models.ActionVerification(
                action_run_id=run.id,
                action_outcome_id=outcome.id,
                verification_method=VERIFICATION_METHOD,
                state="not_performed",
                challenge_digest=None,
                proof_digest=None,
                verified_at=now,
                details={"failure_class": failure_class},
            )
        )
        db.commit()
    return get_action_status_by_id(action_id)


def _store_selection(action_id: str, candidate: dict) -> None:
    with SessionLocal() as db:
        run = db.scalar(
            select(models.ActionRun).where(models.ActionRun.action_id == action_id)
        )
        if run is None:
            raise ActionServiceError(404, "action_not_found", "Action run not found")
        evidence = _bounded_discovery_evidence(candidate)
        run.selected_provider_identifier = str(candidate.get("identifier") or "")[:240]
        run.source_id = str(candidate.get("source") or "")[:160] or None
        run.agent_card_url = str(candidate.get("url") or "")[:1000] or None
        run.interaction_url = str(candidate.get("interaction_url") or "")[:1000]
        run.discovery_evidence = evidence
        run.protocol_binding = str(candidate.get("protocol_binding") or "")[:40] or None
        run.protocol_version = str(candidate.get("protocol_version") or "")[:40] or None
        run.discovery_attempt_count = evidence["discovery_outbound_attempts"]
        run.state = "selected"
        db.add(run)
        db.commit()


def _build_challenge(action_id: str):
    nonce = secrets.token_urlsafe(24)
    challenge = {
        "action": "aion_callability_challenge",
        "version": "1",
        "correlation_id": action_id,
        "nonce": nonce,
        "requested_behavior": "return the correlation_id and nonce without performing another action",
    }
    challenge_text = json.dumps(
        challenge, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    official_request = SendMessageRequest(
        message=Message(
            message_id=str(uuid.uuid4()),
            role=Role.ROLE_USER,
            parts=[Part(text=challenge_text)],
        ),
        configuration=SendMessageConfiguration(
            accepted_output_modes=["application/json", "text/plain"],
            return_immediately=False,
        ),
    )
    rpc = {
        "jsonrpc": "2.0",
        "id": action_id,
        "method": "SendMessage",
        "params": MessageToDict(official_request),
    }
    encoded = json.dumps(rpc, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return rpc, encoded, nonce, _digest_bytes(challenge_text.encode("utf-8"))


def _begin_attempt(action_id: str, request_bytes: int) -> int:
    now = _utcnow()
    with SessionLocal() as db:
        run = db.scalar(
            select(models.ActionRun).where(models.ActionRun.action_id == action_id)
        )
        if run is None:
            raise ActionServiceError(404, "action_not_found", "Action run not found")
        attempt = models.ActionAttempt(
            action_run_id=run.id,
            attempt_number=1,
            method="POST",
            state="dispatching",
            delivery_state="unknown",
            started_at=now,
            completed_at=None,
            request_bytes=request_bytes,
            response_bytes=None,
            http_status=None,
            transport_error=None,
            response_digest=None,
            protocol_response_id=None,
        )
        run.state = "invoking"
        db.add(run)
        db.add(attempt)
        db.commit()
        return attempt.id


def _post_challenge(url: str, encoded: bytes):
    policy = safe_http.FetchPolicy(
        timeout_seconds=ACTION_TIMEOUT_SECONDS,
        max_response_bytes=ACTION_RESPONSE_BYTE_LIMIT,
        max_attempts=ACTION_MAX_POST_ATTEMPTS,
        max_resolved_addresses=4,
        user_agent="AION-Callability-Action/0.7.1",
    )
    return safe_http.fetch_bytes(
        "POST",
        url,
        payload=encoded,
        headers={"Content-Type": "application/json", "A2A-Version": "1.0"},
        policy=policy,
        connection_factory=_ACTION_CONNECTION_FACTORY,
    )


def _contains_exact_proof(value, nonce: str) -> bool:
    if value == nonce:
        return True
    if isinstance(value, dict):
        return any(_contains_exact_proof(item, nonce) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact_proof(item, nonce) for item in value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return False
        return _contains_exact_proof(decoded, nonce)
    return False


def _protocol_evidence(raw: bytes, action_id: str, nonce: str) -> dict:
    base = {
        "protocol_response_received": False,
        "callability_verified": False,
        "capability_verified": False,
        "verified_outcome": False,
        "proof_present": False,
        "outcome_type": "protocol_failure",
        "failure_class": "protocol_failure",
        "normalized_result_kind": None,
        "protocol_task_id": None,
        "protocol_message_id": None,
        "protocol_response_id": None,
    }
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return base
    if (
        not isinstance(document, dict)
        or document.get("jsonrpc") != "2.0"
        or document.get("id") != action_id
    ):
        return base
    base["protocol_response_id"] = str(document.get("id"))[:128]
    if document.get("error") is not None or not isinstance(document.get("result"), dict):
        return base
    try:
        parsed = ParseDict(document["result"], SendMessageResponse())
        normalized = MessageToDict(parsed)
    except Exception:
        return base
    payload_kind = parsed.WhichOneof("payload")
    if payload_kind not in {"message", "task"}:
        return base

    base["protocol_response_received"] = True
    if payload_kind == "message":
        message = normalized.get("message") or {}
        base["normalized_result_kind"] = "message"
        base["protocol_message_id"] = str(message.get("messageId") or "")[:160] or None
        proof_source = message
    else:
        task = normalized.get("task") or {}
        base["normalized_result_kind"] = "task"
        base["protocol_task_id"] = str(task.get("id") or "")[:160] or None
        state = str((task.get("status") or {}).get("state") or "")
        if state == "TASK_STATE_AUTH_REQUIRED":
            base["outcome_type"] = "permission_missing"
            base["failure_class"] = "permission_missing"
            return base
        if state in {
            "TASK_STATE_SUBMITTED",
            "TASK_STATE_WORKING",
            "TASK_STATE_INPUT_REQUIRED",
            "TASK_STATE_UNSPECIFIED",
            "",
        }:
            base["outcome_type"] = "async_result_not_supported_v1"
            base["failure_class"] = "async_result_not_supported_v1"
            return base
        if state != "TASK_STATE_COMPLETED":
            base["outcome_type"] = "invocation_failed"
            base["failure_class"] = "invocation_failed"
            return base
        proof_source = {
            "artifacts": task.get("artifacts") or [],
            "status_message": (task.get("status") or {}).get("message"),
        }

    proof_present = _contains_exact_proof(proof_source, nonce)
    base["proof_present"] = proof_present
    if proof_present:
        base.update(
            {
                "callability_verified": True,
                "verified_outcome": True,
                "outcome_type": "callability_challenge_verified",
                "failure_class": None,
            }
        )
    else:
        base["outcome_type"] = "verification_failed"
        base["failure_class"] = "verification_failed"
    return base


def _transport_failure(result: safe_http.FetchResult) -> str:
    error = str(result.error or "")
    if result.attempts == 0 and error.startswith(
        (
            "url_must_be_public_https",
            "nonstandard_port_rejected",
            "non_public_address",
            "too_many_resolved_addresses",
            "url_validation_error",
        )
    ):
        return "unsafe_destination"
    if error == "response_too_large":
        return "response_too_large"
    if error in {"http_401", "http_403"}:
        return "permission_missing"
    if error == "http_429":
        return "rate_limited"
    if result.status is None and result.attempts > 0:
        return "unknown_delivery_state"
    if result.status is None:
        return "endpoint_unreachable"
    if error in {"redirect_rejected", "content_encoding_rejected"}:
        return "protocol_failure"
    return "invocation_failed"


def _finalize_attempt(
    action_id: str,
    attempt_id: int,
    result: safe_http.FetchResult,
    challenge_digest: str,
    nonce: str,
) -> dict:
    now = _utcnow()
    response_digest = _digest_bytes(result.body) if result.body is not None else None
    evidence = (
        _protocol_evidence(result.body, action_id, nonce)
        if result.error is None and result.body is not None and result.status == 200
        else {
            "protocol_response_received": False,
            "callability_verified": False,
            "capability_verified": False,
            "verified_outcome": False,
            "proof_present": False,
            "outcome_type": _transport_failure(result),
            "failure_class": _transport_failure(result),
            "normalized_result_kind": None,
            "protocol_task_id": None,
            "protocol_message_id": None,
            "protocol_response_id": None,
        }
    )
    failure_class = evidence["failure_class"]
    with SessionLocal() as db:
        run = db.scalar(
            select(models.ActionRun).where(models.ActionRun.action_id == action_id)
        )
        attempt = db.get(models.ActionAttempt, attempt_id)
        if run is None or attempt is None:
            raise ActionServiceError(404, "action_not_found", "Action run not found")
        attempt.completed_at = now
        attempt.state = "completed"
        attempt.delivery_state = (
            "unknown"
            if failure_class == "unknown_delivery_state"
            else "not_sent"
            if result.attempts == 0
            else "response_received"
        )
        attempt.response_bytes = len(result.body) if result.body is not None else None
        attempt.http_status = result.status
        attempt.transport_error = str(result.error or "")[:300] or None
        attempt.response_digest = response_digest
        attempt.protocol_response_id = evidence.get("protocol_response_id")

        run.state = (
            "completed"
            if evidence["verified_outcome"]
            else "ambiguous"
            if failure_class == "unknown_delivery_state"
            else "failed"
        )
        run.failure_class = failure_class
        run.completed_at = now
        run.duration_ms = _duration_ms(run.started_at, now)
        run.action_attempt_count = min(result.attempts, 1)
        run.request_bytes = attempt.request_bytes
        run.response_bytes = attempt.response_bytes

        outcome = models.ActionOutcome(
            action_run_id=run.id,
            outcome_type=evidence["outcome_type"],
            protocol_response_received=evidence["protocol_response_received"],
            callability_verified=evidence["callability_verified"],
            capability_verified=False,
            verified_outcome=evidence["verified_outcome"],
            normalized_result_kind=evidence["normalized_result_kind"],
            failure_class=failure_class,
            response_digest=response_digest,
            protocol_task_id=evidence["protocol_task_id"],
            protocol_message_id=evidence["protocol_message_id"],
            proof_present=evidence["proof_present"],
            completed_at=now,
        )
        db.add(run)
        db.add(attempt)
        db.add(outcome)
        db.flush()
        db.add(
            models.ActionVerification(
                action_run_id=run.id,
                action_outcome_id=outcome.id,
                verification_method=VERIFICATION_METHOD,
                state="verified" if evidence["verified_outcome"] else "failed",
                challenge_digest=challenge_digest,
                proof_digest=_digest_json({"nonce": nonce})
                if evidence["proof_present"]
                else None,
                verified_at=now,
                details={
                    "protocol_response_correlated": bool(
                        evidence.get("protocol_response_id") == action_id
                    ),
                    "proof_present": evidence["proof_present"],
                    "capability_verified": False,
                },
            )
        )
        db.commit()
    return get_action_status_by_id(action_id)


def _serialize_action(db, run: models.ActionRun, *, replayed: bool = False) -> dict:
    attempts = list(
        db.scalars(
            select(models.ActionAttempt)
            .where(models.ActionAttempt.action_run_id == run.id)
            .order_by(models.ActionAttempt.attempt_number)
        ).all()
    )
    outcome = db.scalar(
        select(models.ActionOutcome).where(models.ActionOutcome.action_run_id == run.id)
    )
    verification = db.scalar(
        select(models.ActionVerification).where(
            models.ActionVerification.action_run_id == run.id
        )
    )
    effective_failure = run.failure_class
    if outcome is None and attempts:
        effective_failure = "unknown_delivery_state"
    elif outcome is None and run.state in {"claimed", "selected", "invoking"}:
        effective_failure = "in_progress_no_automatic_resume_v1"
    return {
        "action_id": run.action_id,
        "action_type": ACTION_TYPE,
        "requester_agent_id": run.requester_agent_id,
        "state": run.state,
        "failure_class": effective_failure,
        "idempotent_replay": replayed,
        "request": {
            "query": run.requested_query,
            "candidate_identifier": run.requested_candidate_identifier,
            "request_digest": run.request_digest,
            "authorize_external_contact": run.authorize_external_contact,
        },
        "selection": {
            "provider_identifier": run.selected_provider_identifier,
            "source": run.source_id,
            "agent_card_url": run.agent_card_url,
            "interaction_url": run.interaction_url,
            "protocol_binding": run.protocol_binding,
            "protocol_version": run.protocol_version,
            "discovery_evidence": run.discovery_evidence,
        },
        "telemetry": {
            "discovery_attempts": run.discovery_attempt_count,
            "invocation_attempts": run.action_attempt_count,
            "duration_ms": run.duration_ms,
            "request_bytes": run.request_bytes,
            "response_bytes": run.response_bytes,
            "verification_count": 1 if verification is not None else 0,
            "cost_amount": run.cost_amount,
            "cost_currency": run.cost_currency,
        },
        "attempts": [
            {
                "attempt_number": attempt.attempt_number,
                "method": attempt.method,
                "state": attempt.state,
                "delivery_state": attempt.delivery_state,
                "http_status": attempt.http_status,
                "request_bytes": attempt.request_bytes,
                "response_bytes": attempt.response_bytes,
                "response_digest": attempt.response_digest,
                "transport_error": attempt.transport_error,
            }
            for attempt in attempts
        ],
        "outcome": None
        if outcome is None
        else {
            "outcome_type": outcome.outcome_type,
            "protocol_response_received": outcome.protocol_response_received,
            "callability_verified": outcome.callability_verified,
            "capability_verified": outcome.capability_verified,
            "verified_outcome": outcome.verified_outcome,
            "normalized_result_kind": outcome.normalized_result_kind,
            "failure_class": outcome.failure_class,
            "response_digest": outcome.response_digest,
            "protocol_task_id": outcome.protocol_task_id,
            "protocol_message_id": outcome.protocol_message_id,
        },
        "verification": None
        if verification is None
        else {
            "method": verification.verification_method,
            "state": verification.state,
            "challenge_digest": verification.challenge_digest,
            "proof_digest": verification.proof_digest,
            "details": verification.details,
        },
        "timestamps": {
            "created_at": run.created_at.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        },
        "external_provider_is_aion_member": False,
        "legacy_reputation_updated": False,
        "limits": {
            "remote_post_attempts": ACTION_MAX_POST_ATTEMPTS,
            "response_bytes": ACTION_RESPONSE_BYTE_LIMIT,
            "timeout_seconds": ACTION_TIMEOUT_SECONDS,
            "process_concurrency": ACTION_CONCURRENCY_LIMIT,
            "process_rate_per_minute": ACTION_RATE_LIMIT,
        },
    }


def get_action_status_by_id(action_id: str, requester_agent_id: int | None = None) -> dict:
    try:
        normalized_action_id = str(uuid.UUID(str(action_id)))
    except (ValueError, TypeError, AttributeError):
        raise ActionServiceError(404, "action_not_found", "Action run not found")
    with SessionLocal() as db:
        run = db.scalar(
            select(models.ActionRun).where(models.ActionRun.action_id == normalized_action_id)
        )
        if run is None or (
            requester_agent_id is not None
            and run.requester_agent_id != requester_agent_id
        ):
            raise ActionServiceError(404, "action_not_found", "Action run not found")
        return _serialize_action(db, run)


def verify_external_callability(
    requester_agent_id: int,
    payload: schemas.VerifyCallabilityRequest,
    idempotency_key: str,
) -> dict:
    if not payload.authorize_external_contact:
        raise ActionServiceError(
            422,
            "external_contact_not_authorized",
            "authorize_external_contact=true is required",
        )
    normalized_key = _normalized_idempotency_key(idempotency_key)
    action_id, created = _claim_action(requester_agent_id, payload, normalized_key)
    if not created:
        with SessionLocal() as db:
            run = db.scalar(
                select(models.ActionRun).where(models.ActionRun.action_id == action_id)
            )
            return _serialize_action(db, run, replayed=True)

    if not _allow_action():
        return _complete_without_post(action_id, "rate_limited")
    if not _ACTION_SLOTS.acquire(blocking=False):
        return _complete_without_post(action_id, "rate_limited")
    try:
        discovery = discover_external_agents_with_status(
            payload.query, ACTION_DISCOVERY_CANDIDATE_LIMIT
        )
        if discovery.failure_class is not None:
            return _complete_without_post(
                action_id, discovery.failure_class, discovery
            )
        candidates = list(discovery.results)[:ACTION_DISCOVERY_CANDIDATE_LIMIT]
        candidate = _select_candidate(candidates, payload.candidate_identifier)
        if candidate is None:
            return _complete_without_post(
                action_id,
                _candidate_failure(candidates, payload.candidate_identifier),
            )
        _store_selection(action_id, candidate)
        _, encoded, nonce, challenge_digest = _build_challenge(action_id)
        attempt_id = _begin_attempt(action_id, len(encoded))
        result = _post_challenge(str(candidate["interaction_url"]), encoded)
        return _finalize_attempt(
            action_id, attempt_id, result, challenge_digest, nonce
        )
    finally:
        _ACTION_SLOTS.release()
