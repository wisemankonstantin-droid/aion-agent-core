"""Bounded refresh and current-state services for Live Utility Package 1."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
import hashlib
import json
import threading
from typing import Mapping

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.live_utility import (
    FreshnessAssessment,
    FreshnessState,
    RefreshStrategy,
    SourceDefinition,
    SourceObservation,
    evaluate_freshness,
    materialize_refresh_window,
)
from app.services import live_utility_store
from app.services.live_utility_sources import (
    AdapterResponse,
    GitHubReleaseAdapter,
    SourceValidationError,
    VERIFICATION_METHOD,
)


class RefreshStatus(str, Enum):
    REFRESHED_CHANGED = "refreshed_changed"
    REFRESHED_UNCHANGED = "refreshed_unchanged"
    SKIPPED_NOT_DUE = "skipped_not_due"
    DISABLED = "disabled"
    CIRCUIT_OPEN = "circuit_open"
    FETCH_FAILED = "fetch_failed"
    VALIDATION_FAILED = "validation_failed"
    PERSISTENCE_FAILED = "persistence_failed"


@dataclass(frozen=True, slots=True)
class EnginePolicy:
    max_concurrency: int = 2
    request_budget: int = 2
    circuit_failure_threshold: int = 3
    circuit_cooldown_seconds: int = 15 * 60

    def __post_init__(self) -> None:
        if not 0 < self.max_concurrency <= 8:
            raise ValueError("max_concurrency must be in [1, 8]")
        if not 0 < self.request_budget <= 4:
            raise ValueError("request_budget must be in [1, 4]")
        if not 0 < self.circuit_failure_threshold <= 10:
            raise ValueError("circuit_failure_threshold must be in [1, 10]")
        if not 0 < self.circuit_cooldown_seconds <= 24 * 60 * 60:
            raise ValueError("circuit_cooldown_seconds must be in (0, 86400]")


@dataclass(frozen=True, slots=True)
class FieldChange:
    field: str
    before: object
    after: object


@dataclass(frozen=True, slots=True)
class MaterialChange:
    previous_observation_id: str | None
    observation_id: str
    changes: tuple[FieldChange, ...]


@dataclass(frozen=True, slots=True)
class CurrentState:
    source: SourceDefinition
    observation: SourceObservation
    normalized_data: Mapping[str, object] | None
    freshness: FreshnessAssessment
    verified: bool
    latest_change: MaterialChange | None


@dataclass(frozen=True, slots=True)
class RefreshResult:
    status: RefreshStatus
    source_id: str
    subject_key: str
    attempts: int
    current_state: CurrentState | None
    change: MaterialChange | None = None
    error: str | None = None


@dataclass(slots=True)
class _FailureState:
    count: int = 0
    opened_at: datetime | None = None


def canonical_digest(normalized_data: Mapping[str, object]) -> str:
    encoded = json.dumps(
        dict(normalized_data),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _require_aware_now(now: datetime) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")


def structured_change(
    before: Mapping[str, object] | None,
    after: Mapping[str, object],
    *,
    previous_observation_id: str | None,
    observation_id: str,
) -> MaterialChange:
    before_values = dict(before or {})
    after_values = dict(after)
    fields = sorted(set(before_values) | set(after_values))
    changes = tuple(
        FieldChange(field, before_values.get(field), after_values.get(field))
        for field in fields
        if before_values.get(field) != after_values.get(field)
    )
    return MaterialChange(previous_observation_id, observation_id, changes)


class LiveUtilityEngine:
    def __init__(
        self,
        adapters: tuple[GitHubReleaseAdapter, ...],
        *,
        policy: EnginePolicy = EnginePolicy(),
    ) -> None:
        self._adapters = {adapter.source.source_id: adapter for adapter in adapters}
        if len(self._adapters) != len(adapters):
            raise ValueError("adapter source IDs must be unique")
        self.policy = policy
        self._semaphore = threading.BoundedSemaphore(policy.max_concurrency)
        self._failure_states: dict[str, _FailureState] = {}
        self._failure_lock = threading.Lock()
        self._subject_locks: dict[str, threading.Lock] = {}

    def ensure_sources(self, db: Session) -> tuple[SourceDefinition, ...]:
        configured = []
        for adapter in self._adapters.values():
            existing = live_utility_store.get_source(db, adapter.source.source_id)
            if existing is None:
                existing = live_utility_store.register_source(db, adapter.source)
            elif existing != adapter.source:
                raise ValueError(
                    f"durable source configuration mismatch: {adapter.source.source_id}"
                )
            configured.append(existing)
        return tuple(configured)

    def _failure_state(self, source_id: str) -> _FailureState:
        with self._failure_lock:
            return self._failure_states.setdefault(source_id, _FailureState())

    def _circuit_open(self, source_id: str, now: datetime) -> bool:
        state = self._failure_state(source_id)
        if state.opened_at is None:
            return False
        if now >= state.opened_at + timedelta(seconds=self.policy.circuit_cooldown_seconds):
            with self._failure_lock:
                state.count = 0
                state.opened_at = None
            return False
        return True

    def _record_failure(self, source_id: str, now: datetime) -> None:
        state = self._failure_state(source_id)
        with self._failure_lock:
            state.count += 1
            if state.count >= self.policy.circuit_failure_threshold:
                state.opened_at = now

    def _record_success(self, source_id: str) -> None:
        state = self._failure_state(source_id)
        with self._failure_lock:
            state.count = 0
            state.opened_at = None

    def _effective_observation(
        self,
        db: Session,
        observation: SourceObservation,
    ) -> SourceObservation:
        verification = live_utility_store.get_latest_verification(
            db,
            source_id=observation.source_id,
            subject_key=observation.subject_key,
        )
        if verification is None or verification.observation_id != observation.observation_id:
            return observation
        return replace(
            observation,
            verified_at=verification.verified_at,
            valid_from=verification.valid_from,
            stale_after=verification.stale_after,
            expires_at=verification.expires_at,
            verification_method=verification.verification_method,
        )

    def get_current_state(
        self,
        db: Session,
        *,
        source_id: str,
        subject_key: str,
        now: datetime,
    ) -> CurrentState | None:
        _require_aware_now(now)
        source = live_utility_store.get_source(db, source_id)
        latest = live_utility_store.get_latest_normalized_observation(
            db,
            source_id=source_id,
            subject_key=subject_key,
        )
        if source is None or latest is None:
            return None
        observation, normalized = latest
        effective = self._effective_observation(db, observation)
        change = self._latest_change(db, effective, normalized)
        freshness = evaluate_freshness(effective, now)
        return CurrentState(
            source=source,
            observation=effective,
            normalized_data=normalized,
            freshness=freshness,
            verified=(
                effective.verified_at is not None
                and effective.verified_at <= now
            ),
            latest_change=change,
        )

    def _latest_change(
        self,
        db: Session,
        observation: SourceObservation,
        normalized: Mapping[str, object] | None,
    ) -> MaterialChange | None:
        if normalized is None:
            return None
        before = None
        if observation.previous_observation_id is not None:
            previous = live_utility_store.get_normalized_observation(
                db,
                observation.previous_observation_id,
            )
            if previous is not None:
                _, before = previous
        return structured_change(
            before,
            normalized,
            previous_observation_id=observation.previous_observation_id,
            observation_id=observation.observation_id,
        )

    def _advisory_lock(self, db: Session, source_id: str, subject_key: str) -> None:
        if db.get_bind().dialect.name != "postgresql":
            return
        raw = hashlib.sha256(f"{source_id}\0{subject_key}".encode()).digest()[:8]
        lock_key = int.from_bytes(raw, "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

    def _subject_lock(self, source_id: str, subject_key: str) -> threading.Lock:
        key = f"{source_id}\0{subject_key}"
        with self._failure_lock:
            return self._subject_locks.setdefault(key, threading.Lock())

    def _is_due(
        self,
        current: CurrentState | None,
        *,
        demand: bool,
    ) -> bool:
        if current is None:
            return True
        if demand and RefreshStrategy.DEMAND_DRIVEN in current.source.refresh_policy.strategies:
            return True
        return current.freshness.refresh_required

    def refresh_source(
        self,
        db: Session,
        *,
        source_id: str,
        now: datetime,
        demand: bool = False,
        retrieved_response: AdapterResponse | None = None,
    ) -> RefreshResult:
        _require_aware_now(now)
        adapter = self._adapters.get(source_id)
        source = live_utility_store.get_source(db, source_id)
        subject_key = adapter.subject_key if adapter else "unknown"
        if source is None or adapter is None:
            return RefreshResult(
                RefreshStatus.VALIDATION_FAILED,
                source_id,
                subject_key,
                0,
                None,
                error="source_or_adapter_not_configured",
            )
        if not source.enabled:
            return RefreshResult(
                RefreshStatus.DISABLED,
                source_id,
                subject_key,
                0,
                self.get_current_state(
                    db,
                    source_id=source_id,
                    subject_key=subject_key,
                    now=now,
                ),
            )

        current = self.get_current_state(
            db,
            source_id=source_id,
            subject_key=subject_key,
            now=now,
        )
        if not self._is_due(current, demand=demand):
            return RefreshResult(
                RefreshStatus.SKIPPED_NOT_DUE,
                source_id,
                subject_key,
                0,
                current,
            )
        if self._circuit_open(source_id, now):
            return RefreshResult(
                RefreshStatus.CIRCUIT_OPEN,
                source_id,
                subject_key,
                0,
                current,
                error="failure_circuit_open",
            )
        if adapter.fetch_policy.max_attempts > self.policy.request_budget:
            return RefreshResult(
                RefreshStatus.FETCH_FAILED,
                source_id,
                subject_key,
                0,
                current,
                error="request_budget_exceeded",
            )

        if retrieved_response is None:
            wait_seconds = adapter.fetch_policy.timeout_seconds * self.policy.request_budget
            if not self._semaphore.acquire(timeout=wait_seconds):
                return RefreshResult(
                    RefreshStatus.FETCH_FAILED,
                    source_id,
                    subject_key,
                    0,
                    current,
                    error="concurrency_limit_timeout",
                )
            try:
                try:
                    response = adapter.retrieve()
                except Exception as exc:
                    self._record_failure(source_id, now)
                    return RefreshResult(
                        RefreshStatus.FETCH_FAILED,
                        source_id,
                        subject_key,
                        0,
                        current,
                        error=f"fetch_exception:{type(exc).__name__}",
                    )
            finally:
                self._semaphore.release()
        else:
            # Package 3B retrieves outside any database transaction, then uses
            # this existing normalization/deduplication path for persistence.
            response = retrieved_response

        if response.transport.error is not None:
            self._record_failure(source_id, now)
            return RefreshResult(
                RefreshStatus.FETCH_FAILED,
                source_id,
                subject_key,
                response.transport.attempts,
                current,
                error=response.transport.error,
            )
        try:
            normalized = adapter.normalize(response.payload)
        except SourceValidationError as exc:
            self._record_failure(source_id, now)
            return RefreshResult(
                RefreshStatus.VALIDATION_FAILED,
                source_id,
                subject_key,
                response.transport.attempts,
                current,
                error=str(exc),
            )

        digest = canonical_digest(normalized)
        stale_after, expires_at = materialize_refresh_window(
            now,
            source.refresh_policy,
        )
        lock = self._subject_lock(source_id, subject_key)
        try:
            with lock, db.begin_nested():
                self._advisory_lock(db, source_id, subject_key)
                latest = live_utility_store.get_latest_normalized_observation(
                    db,
                    source_id=source_id,
                    subject_key=subject_key,
                )
                previous = None if latest is None else latest[0]
                previous_data = None if latest is None else latest[1]
                unchanged = previous is not None and previous.content_digest == digest
                if unchanged:
                    observation = previous
                else:
                    seed = "\0".join(
                        (
                            source_id,
                            subject_key,
                            previous.observation_id if previous else "",
                            digest,
                        )
                    )
                    observation_id = "obs-" + hashlib.sha256(seed.encode()).hexdigest()
                    observation = SourceObservation(
                        observation_id=observation_id,
                        source_id=source_id,
                        subject_key=subject_key,
                        source_revision=adapter.source_revision(normalized),
                        previous_observation_id=(
                            previous.observation_id if previous else None
                        ),
                        observed_at=now,
                        verified_at=now,
                        valid_from=now,
                        stale_after=stale_after,
                        expires_at=expires_at,
                        verification_method=VERIFICATION_METHOD,
                        content_digest=digest,
                    )
                    live_utility_store.append_observation(
                        db,
                        observation,
                        normalized_data=normalized,
                    )

                latest_verification = live_utility_store.get_latest_verification(
                    db,
                    source_id=source_id,
                    subject_key=subject_key,
                )
                verification_seed = "\0".join(
                    (source_id, subject_key, observation.observation_id, now.isoformat())
                )
                verification_id = "verify-" + hashlib.sha256(
                    verification_seed.encode()
                ).hexdigest()
                if (
                    latest_verification is None
                    or latest_verification.verification_id != verification_id
                ):
                    live_utility_store.append_verification(
                        db,
                        live_utility_store.VerificationRecord(
                            verification_id=verification_id,
                            source_id=source_id,
                            subject_key=subject_key,
                            observation_id=observation.observation_id,
                            verified_at=now,
                            valid_from=now,
                            stale_after=stale_after,
                            expires_at=expires_at,
                            verification_method=VERIFICATION_METHOD,
                            content_digest=digest,
                        ),
                    )
                change = None
                if not unchanged:
                    change = structured_change(
                        previous_data,
                        normalized,
                        previous_observation_id=(
                            previous.observation_id if previous else None
                        ),
                        observation_id=observation.observation_id,
                    )
        except (SQLAlchemyError, ValueError) as exc:
            self._record_failure(source_id, now)
            return RefreshResult(
                RefreshStatus.PERSISTENCE_FAILED,
                source_id,
                subject_key,
                response.transport.attempts,
                current,
                error=f"{type(exc).__name__}:{str(exc)[:240]}",
            )

        self._record_success(source_id)
        refreshed = self.get_current_state(
            db,
            source_id=source_id,
            subject_key=subject_key,
            now=now,
        )
        return RefreshResult(
            (
                RefreshStatus.REFRESHED_UNCHANGED
                if unchanged
                else RefreshStatus.REFRESHED_CHANGED
            ),
            source_id,
            subject_key,
            response.transport.attempts,
            refreshed,
            change=change,
        )
