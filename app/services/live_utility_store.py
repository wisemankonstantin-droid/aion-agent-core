"""Persistence adapter for the pure Live Utility domain contracts.

The functions in this module add and flush records but never commit. Callers own
the transaction boundary. There are intentionally no update, delete, retrieval,
network or endpoint operations beyond database persistence and lookup.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.services.live_utility import (
    RefreshPolicy,
    RefreshStrategy,
    SourceDefinition,
    SourceObservation,
    SourceTier,
)


def _as_aware_utc(value: datetime | None) -> datetime | None:
    """Normalize SQLite's naive round-trip as UTC without using local time."""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _source_to_domain(row: models.LiveUtilitySource) -> SourceDefinition:
    return SourceDefinition(
        source_id=row.source_id,
        display_name=row.display_name,
        tier=SourceTier(row.tier),
        source_kind=row.source_kind,
        canonical_locator=row.canonical_locator,
        refresh_policy=RefreshPolicy(
            strategies=frozenset(RefreshStrategy(value) for value in row.refresh_strategies),
            stale_after_seconds=row.stale_after_seconds,
            expires_after_seconds=row.expires_after_seconds,
        ),
        enabled=row.enabled,
    )


def _observation_to_domain(row: models.LiveUtilityObservation) -> SourceObservation:
    return SourceObservation(
        observation_id=row.observation_id,
        source_id=row.source_id,
        subject_key=row.subject_key,
        source_revision=row.source_revision,
        previous_observation_id=row.previous_observation_id,
        observed_at=_as_aware_utc(row.observed_at),
        verified_at=_as_aware_utc(row.verified_at),
        valid_from=_as_aware_utc(row.valid_from),
        stale_after=_as_aware_utc(row.stale_after),
        expires_at=_as_aware_utc(row.expires_at),
        verification_method=row.verification_method,
        content_digest=row.content_digest,
    )


def register_source(db: Session, source: SourceDefinition) -> SourceDefinition:
    """Insert one source definition without implying verification or callability."""

    if db.scalar(
        select(models.LiveUtilitySource.id).where(
            models.LiveUtilitySource.source_id == source.source_id
        )
    ) is not None:
        raise ValueError(f"duplicate source_id: {source.source_id}")

    row = models.LiveUtilitySource(
        source_id=source.source_id,
        display_name=source.display_name,
        tier=source.tier.value,
        source_kind=source.source_kind,
        canonical_locator=source.canonical_locator,
        refresh_strategies=sorted(strategy.value for strategy in source.refresh_policy.strategies),
        stale_after_seconds=source.refresh_policy.stale_after_seconds,
        expires_after_seconds=source.refresh_policy.expires_after_seconds,
        enabled=source.enabled,
    )
    db.add(row)
    db.flush()
    return _source_to_domain(row)


def get_source(db: Session, source_id: str) -> SourceDefinition | None:
    row = db.scalar(
        select(models.LiveUtilitySource).where(
            models.LiveUtilitySource.source_id == source_id
        )
    )
    return None if row is None else _source_to_domain(row)


def list_sources(
    db: Session, *, tier: SourceTier | None = None
) -> tuple[SourceDefinition, ...]:
    statement = select(models.LiveUtilitySource).order_by(models.LiveUtilitySource.id)
    if tier is not None:
        statement = statement.where(models.LiveUtilitySource.tier == tier.value)
    return tuple(_source_to_domain(row) for row in db.scalars(statement))


def append_observation(db: Session, observation: SourceObservation) -> SourceObservation:
    """Append one immutable evidence record after bounded lineage validation."""

    if db.scalar(
        select(models.LiveUtilityObservation.id).where(
            models.LiveUtilityObservation.observation_id == observation.observation_id
        )
    ) is not None:
        raise ValueError(f"duplicate observation_id: {observation.observation_id}")

    if observation.previous_observation_id == observation.observation_id:
        raise ValueError("an observation cannot reference itself")

    if db.scalar(
        select(models.LiveUtilitySource.id).where(
            models.LiveUtilitySource.source_id == observation.source_id
        )
    ) is None:
        raise ValueError(f"unknown source_id: {observation.source_id}")

    if observation.previous_observation_id is not None:
        previous = db.scalar(
            select(models.LiveUtilityObservation).where(
                models.LiveUtilityObservation.observation_id
                == observation.previous_observation_id
            )
        )
        if previous is None:
            raise ValueError(
                f"unknown previous_observation_id: {observation.previous_observation_id}"
            )
        if previous.source_id != observation.source_id:
            raise ValueError("previous observation belongs to a different source")
        if previous.subject_key != observation.subject_key:
            raise ValueError("previous observation belongs to a different subject")
        previous_observed_at = _as_aware_utc(previous.observed_at)
        if previous_observed_at > observation.observed_at:
            raise ValueError("previous observation is chronologically newer")

    row = models.LiveUtilityObservation(
        observation_id=observation.observation_id,
        source_id=observation.source_id,
        subject_key=observation.subject_key,
        source_revision=observation.source_revision,
        previous_observation_id=observation.previous_observation_id,
        observed_at=observation.observed_at,
        verified_at=observation.verified_at,
        valid_from=observation.valid_from,
        stale_after=observation.stale_after,
        expires_at=observation.expires_at,
        verification_method=observation.verification_method,
        content_digest=observation.content_digest,
    )
    db.add(row)
    db.flush()
    return _observation_to_domain(row)


def get_observation(db: Session, observation_id: str) -> SourceObservation | None:
    row = db.scalar(
        select(models.LiveUtilityObservation).where(
            models.LiveUtilityObservation.observation_id == observation_id
        )
    )
    return None if row is None else _observation_to_domain(row)


def list_observations(
    db: Session, *, source_id: str, subject_key: str | None = None
) -> tuple[SourceObservation, ...]:
    statement = select(models.LiveUtilityObservation).where(
        models.LiveUtilityObservation.source_id == source_id
    )
    if subject_key is not None:
        statement = statement.where(
            models.LiveUtilityObservation.subject_key == subject_key
        )
    statement = statement.order_by(
        models.LiveUtilityObservation.observed_at,
        models.LiveUtilityObservation.id,
    )
    return tuple(_observation_to_domain(row) for row in db.scalars(statement))
