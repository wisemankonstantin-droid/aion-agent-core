"""Pure Live Utility Phase 1 domain contracts.

This module intentionally has no persistence, endpoint, scheduler, retrieval or
network concerns. Source registration records provenance metadata only; it never
establishes verification or endpoint callability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable


class SourceTier(str, Enum):
    """Provenance strength, not a verification or trust result."""

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class RefreshStrategy(str, Enum):
    """Metadata describing allowed ways an adapter may request refresh."""

    EVENT_DRIVEN = "event_driven"
    SCHEDULED = "scheduled"
    TTL = "ttl"
    DEMAND_DRIVEN = "demand_driven"
    RISK_DRIVEN = "risk_driven"
    USAGE_DRIVEN = "usage_driven"


class FreshnessState(str, Enum):
    NOT_YET_VALID = "not_yet_valid"
    UNVERIFIED = "unverified"
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


def _require_non_empty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """A bounded, source-specific refresh policy; it does not schedule work."""

    strategies: frozenset[RefreshStrategy]
    stale_after_seconds: int
    expires_after_seconds: int

    def __post_init__(self) -> None:
        strategies = frozenset(self.strategies)
        if not strategies:
            raise ValueError("at least one refresh strategy is required")
        if not all(isinstance(strategy, RefreshStrategy) for strategy in strategies):
            raise ValueError("strategies must contain RefreshStrategy values")
        if (
            isinstance(self.stale_after_seconds, bool)
            or not isinstance(self.stale_after_seconds, int)
            or self.stale_after_seconds <= 0
        ):
            raise ValueError("stale_after_seconds must be positive")
        if (
            isinstance(self.expires_after_seconds, bool)
            or not isinstance(self.expires_after_seconds, int)
            or self.expires_after_seconds <= 0
        ):
            raise ValueError("expires_after_seconds must be positive")
        if self.expires_after_seconds < self.stale_after_seconds:
            raise ValueError("expires_after_seconds must not be less than stale_after_seconds")
        object.__setattr__(self, "strategies", strategies)


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    """Registered source metadata; registration never verifies source content."""

    source_id: str
    display_name: str
    tier: SourceTier
    source_kind: str
    canonical_locator: str
    refresh_policy: RefreshPolicy
    enabled: bool = True

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.display_name, "display_name")
        _require_non_empty(self.source_kind, "source_kind")
        _require_non_empty(self.canonical_locator, "canonical_locator")
        if not isinstance(self.tier, SourceTier):
            raise ValueError("tier must be a SourceTier")
        if not isinstance(self.refresh_policy, RefreshPolicy):
            raise ValueError("refresh_policy must be a RefreshPolicy")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")


class SourceRegistry:
    """Bounded in-process source metadata registry with no adapter execution."""

    def __init__(self, sources: Iterable[SourceDefinition] = ()) -> None:
        self._sources: dict[str, SourceDefinition] = {}
        for source in sources:
            self.register(source)

    def register(self, source: SourceDefinition) -> None:
        if not isinstance(source, SourceDefinition):
            raise ValueError("source must be a SourceDefinition")
        if source.source_id in self._sources:
            raise ValueError(f"duplicate source_id: {source.source_id}")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> SourceDefinition:
        return self._sources[source_id]

    def list(self, *, tier: SourceTier | None = None) -> tuple[SourceDefinition, ...]:
        if tier is not None and not isinstance(tier, SourceTier):
            raise ValueError("tier must be a SourceTier")
        sources = tuple(self._sources.values())
        if tier is None:
            return sources
        return tuple(source for source in sources if source.tier is tier)


@dataclass(frozen=True, slots=True)
class SourceObservation:
    """Versioned observation metadata without raw payload storage or persistence."""

    observation_id: str
    source_id: str
    subject_key: str
    source_revision: str | None
    previous_observation_id: str | None
    observed_at: datetime
    verified_at: datetime | None
    valid_from: datetime
    stale_after: datetime
    expires_at: datetime
    verification_method: str | None
    content_digest: str

    def __post_init__(self) -> None:
        _require_non_empty(self.observation_id, "observation_id")
        _require_non_empty(self.source_id, "source_id")
        _require_non_empty(self.subject_key, "subject_key")
        _require_non_empty(self.content_digest, "content_digest")
        if self.source_revision is not None:
            _require_non_empty(self.source_revision, "source_revision")
        if self.previous_observation_id is not None:
            _require_non_empty(self.previous_observation_id, "previous_observation_id")
        for field_name, timestamp in (
            ("observed_at", self.observed_at),
            ("valid_from", self.valid_from),
            ("stale_after", self.stale_after),
            ("expires_at", self.expires_at),
        ):
            _require_aware(timestamp, field_name)
        if self.verified_at is not None:
            _require_aware(self.verified_at, "verified_at")
            if self.verified_at < self.observed_at:
                raise ValueError("verified_at must not be before observed_at")
            _require_non_empty(self.verification_method or "", "verification_method")
        elif self.verification_method is not None:
            _require_non_empty(self.verification_method, "verification_method")
        if self.valid_from > self.stale_after:
            raise ValueError("valid_from must not be after stale_after")
        if self.stale_after > self.expires_at:
            raise ValueError("stale_after must not be after expires_at")


@dataclass(frozen=True, slots=True)
class FreshnessAssessment:
    state: FreshnessState
    refresh_required: bool
    eligible_for_consequential_use: bool
    reason: str


def materialize_refresh_window(anchor_at: datetime, policy: RefreshPolicy) -> tuple[datetime, datetime]:
    """Derive and return the policy window for storage on an observation.

    The caller chooses the anchor (normally observed or verified time), making
    the function deterministic and preserving the policy window that applied.
    """

    _require_aware(anchor_at, "anchor_at")
    if not isinstance(policy, RefreshPolicy):
        raise ValueError("policy must be a RefreshPolicy")
    return (
        anchor_at + timedelta(seconds=policy.stale_after_seconds),
        anchor_at + timedelta(seconds=policy.expires_after_seconds),
    )


def evaluate_freshness(observation: SourceObservation, now: datetime) -> FreshnessAssessment:
    """Evaluate freshness with caller-supplied time and no hidden clock.

    Precedence is NOT_YET_VALID, EXPIRED, UNVERIFIED, STALE, then FRESH. Only a
    verified observation within its stored validity and freshness windows can be
    consequentially eligible in this Phase 1 contract slice.
    """

    if not isinstance(observation, SourceObservation):
        raise ValueError("observation must be a SourceObservation")
    _require_aware(now, "now")

    if now < observation.valid_from:
        return FreshnessAssessment(
            FreshnessState.NOT_YET_VALID,
            refresh_required=False,
            eligible_for_consequential_use=False,
            reason="observation validity has not started",
        )
    if now >= observation.expires_at:
        return FreshnessAssessment(
            FreshnessState.EXPIRED,
            refresh_required=True,
            eligible_for_consequential_use=False,
            reason="observation validity has expired",
        )
    if observation.verified_at is None or observation.verified_at > now:
        return FreshnessAssessment(
            FreshnessState.UNVERIFIED,
            refresh_required=True,
            eligible_for_consequential_use=False,
            reason="verification evidence is missing or not yet effective",
        )
    if now >= observation.stale_after:
        return FreshnessAssessment(
            FreshnessState.STALE,
            refresh_required=True,
            eligible_for_consequential_use=False,
            reason="observation freshness window has elapsed",
        )
    return FreshnessAssessment(
        FreshnessState.FRESH,
        refresh_required=False,
        eligible_for_consequential_use=True,
        reason="observation is verified and within its freshness window",
    )
