import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models
from app.db import engine
from app.services import live_utility_store
from app.services.live_utility import (
    FreshnessState,
    RefreshPolicy,
    RefreshStrategy,
    SourceDefinition,
    SourceObservation,
    SourceTier,
    evaluate_freshness,
)


BASE_TIME = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "services" / "live_utility_store.py"
)


@pytest.fixture
def db():
    session = Session(bind=engine, autoflush=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _source(
    source_id: str = "official-protocol",
    *,
    tier: SourceTier = SourceTier.TIER_1,
    enabled: bool = True,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=f"Source {source_id}",
        tier=tier,
        source_kind="fixture",
        canonical_locator=f"fixture:{source_id}",
        refresh_policy=RefreshPolicy(
            strategies=frozenset(
                {RefreshStrategy.DEMAND_DRIVEN, RefreshStrategy.TTL}
            ),
            stale_after_seconds=60,
            expires_after_seconds=120,
        ),
        enabled=enabled,
    )


def _observation(
    observation_id: str = "observation-1",
    *,
    source_id: str = "official-protocol",
    subject_key: str = "protocol.version",
    source_revision: str | None = "1.0",
    previous_observation_id: str | None = None,
    observed_at: datetime = BASE_TIME,
    verified_at: datetime | None = BASE_TIME,
    valid_from: datetime = BASE_TIME,
    stale_after: datetime = BASE_TIME + timedelta(seconds=60),
    expires_at: datetime = BASE_TIME + timedelta(seconds=120),
    content_digest: str = "sha256:one",
) -> SourceObservation:
    return SourceObservation(
        observation_id=observation_id,
        source_id=source_id,
        subject_key=subject_key,
        source_revision=source_revision,
        previous_observation_id=previous_observation_id,
        observed_at=observed_at,
        verified_at=verified_at,
        valid_from=valid_from,
        stale_after=stale_after,
        expires_at=expires_at,
        verification_method="fixture-review" if verified_at is not None else None,
        content_digest=content_digest,
    )


def test_source_persists_and_rehydrates_semantically_equal(db):
    source = _source()

    assert live_utility_store.register_source(db, source) == source
    db.expunge_all()

    assert live_utility_store.get_source(db, source.source_id) == source


def test_refresh_strategies_round_trip_deterministically(db):
    source = _source()
    live_utility_store.register_source(db, source)

    row = db.query(models.LiveUtilitySource).one()
    assert row.refresh_strategies == ["demand_driven", "ttl"]
    assert live_utility_store.get_source(db, source.source_id).refresh_policy == source.refresh_policy


def test_tier_one_source_remains_provenance_only(db):
    live_utility_store.register_source(db, _source())
    restored = live_utility_store.get_source(db, "official-protocol")

    assert restored.tier is SourceTier.TIER_1
    assert not hasattr(restored, "verified")


def test_duplicate_source_id_is_rejected_without_overwrite(db):
    original = _source()
    live_utility_store.register_source(db, original)

    with pytest.raises(ValueError, match="duplicate source_id"):
        live_utility_store.register_source(db, _source(enabled=False))

    assert live_utility_store.get_source(db, original.source_id) == original


def test_disabled_source_round_trip_and_tier_listing(db):
    disabled = _source(enabled=False)
    tier2 = _source("ecosystem", tier=SourceTier.TIER_2)
    live_utility_store.register_source(db, disabled)
    live_utility_store.register_source(db, tier2)

    assert live_utility_store.get_source(db, disabled.source_id).enabled is False
    assert live_utility_store.list_sources(db, tier=SourceTier.TIER_2) == (tier2,)


def test_observation_persists_and_rehydrates_with_aware_timestamps(db):
    source = _source()
    observation = _observation()
    live_utility_store.register_source(db, source)

    assert live_utility_store.append_observation(db, observation) == observation
    db.expunge_all()
    restored = live_utility_store.get_observation(db, observation.observation_id)

    assert restored == observation
    assert restored.observed_at.utcoffset() == timedelta(0)
    assert restored.verified_at.utcoffset() == timedelta(0)


def test_unknown_source_is_rejected_and_source_fk_is_declared(db):
    with pytest.raises(ValueError, match="unknown source_id"):
        live_utility_store.append_observation(db, _observation())

    foreign_keys = {foreign_key.target_fullname for foreign_key in models.LiveUtilityObservation.__table__.foreign_keys}
    assert "live_utility_sources.source_id" in foreign_keys


def test_duplicate_observation_id_is_rejected_without_overwrite(db):
    live_utility_store.register_source(db, _source())
    original = _observation(content_digest="sha256:original")
    live_utility_store.append_observation(db, original)

    with pytest.raises(ValueError, match="duplicate observation_id"):
        live_utility_store.append_observation(
            db, _observation(content_digest="sha256:replacement")
        )

    assert live_utility_store.get_observation(db, original.observation_id) == original


def test_previous_observation_lineage_round_trip(db):
    live_utility_store.register_source(db, _source())
    first = _observation()
    second = _observation(
        "observation-2",
        previous_observation_id=first.observation_id,
        observed_at=BASE_TIME + timedelta(seconds=10),
        verified_at=BASE_TIME + timedelta(seconds=10),
        content_digest="sha256:two",
    )
    live_utility_store.append_observation(db, first)
    live_utility_store.append_observation(db, second)
    db.expunge_all()

    assert live_utility_store.get_observation(db, second.observation_id) == second
    assert live_utility_store.list_observations(
        db, source_id=first.source_id, subject_key=first.subject_key
    ) == (first, second)


def test_missing_previous_observation_is_rejected(db):
    live_utility_store.register_source(db, _source())

    with pytest.raises(ValueError, match="unknown previous_observation_id"):
        live_utility_store.append_observation(
            db, _observation(previous_observation_id="missing")
        )


def test_previous_observation_from_different_source_is_rejected(db):
    live_utility_store.register_source(db, _source())
    live_utility_store.register_source(db, _source("official-release"))
    live_utility_store.append_observation(db, _observation())

    with pytest.raises(ValueError, match="different source"):
        live_utility_store.append_observation(
            db,
            _observation(
                "observation-2",
                source_id="official-release",
                previous_observation_id="observation-1",
            ),
        )


def test_previous_observation_from_different_subject_is_rejected(db):
    live_utility_store.register_source(db, _source())
    live_utility_store.append_observation(db, _observation())

    with pytest.raises(ValueError, match="different subject"):
        live_utility_store.append_observation(
            db,
            _observation(
                "observation-2",
                subject_key="protocol.authentication",
                previous_observation_id="observation-1",
            ),
        )


def test_chronologically_newer_previous_observation_is_rejected(db):
    live_utility_store.register_source(db, _source())
    live_utility_store.append_observation(
        db,
        _observation(
            observed_at=BASE_TIME + timedelta(seconds=10),
            verified_at=BASE_TIME + timedelta(seconds=10),
        ),
    )

    with pytest.raises(ValueError, match="chronologically newer"):
        live_utility_store.append_observation(
            db,
            _observation(
                "observation-2",
                previous_observation_id="observation-1",
            ),
        )


def test_self_reference_is_rejected(db):
    live_utility_store.register_source(db, _source())

    with pytest.raises(ValueError, match="cannot reference itself"):
        live_utility_store.append_observation(
            db,
            _observation(
                observation_id="observation-self",
                previous_observation_id="observation-self",
            ),
        )


def test_nullable_source_revision_and_unverified_state_survive_round_trip(db):
    live_utility_store.register_source(db, _source())
    observation = _observation(source_revision=None, verified_at=None)
    live_utility_store.append_observation(db, observation)
    db.expunge_all()

    restored = live_utility_store.get_observation(db, observation.observation_id)
    assert restored.source_revision is None
    assert restored.content_digest == "sha256:one"
    assert evaluate_freshness(restored, BASE_TIME).state is FreshnessState.UNVERIFIED


def test_future_verification_remains_unverified_after_round_trip(db):
    live_utility_store.register_source(db, _source())
    observation = _observation(verified_at=BASE_TIME + timedelta(seconds=30))
    live_utility_store.append_observation(db, observation)
    db.expunge_all()

    restored = live_utility_store.get_observation(db, observation.observation_id)
    assessment = evaluate_freshness(restored, BASE_TIME)
    assert assessment.state is FreshnessState.UNVERIFIED
    assert assessment.eligible_for_consequential_use is False


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (BASE_TIME + timedelta(seconds=59), FreshnessState.FRESH),
        (BASE_TIME + timedelta(seconds=60), FreshnessState.STALE),
        (BASE_TIME + timedelta(seconds=120), FreshnessState.EXPIRED),
    ],
)
def test_freshness_boundaries_survive_round_trip(db, now, expected):
    live_utility_store.register_source(db, _source())
    live_utility_store.append_observation(db, _observation())
    db.expunge_all()

    restored = live_utility_store.get_observation(db, "observation-1")
    assert evaluate_freshness(restored, now).state is expected


def test_database_rejects_invalid_source_refresh_window(db):
    db.add(
        models.LiveUtilitySource(
            source_id="invalid-source",
            display_name="Invalid",
            tier="tier_1",
            source_kind="fixture",
            canonical_locator="fixture:invalid",
            refresh_strategies=["ttl"],
            stale_after_seconds=120,
            expires_after_seconds=60,
            enabled=True,
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


def test_database_rejects_invalid_observation_temporal_order(db):
    live_utility_store.register_source(db, _source())
    db.add(
        models.LiveUtilityObservation(
            observation_id="invalid-observation",
            source_id="official-protocol",
            subject_key="protocol.version",
            source_revision=None,
            previous_observation_id=None,
            observed_at=BASE_TIME,
            verified_at=BASE_TIME - timedelta(seconds=1),
            valid_from=BASE_TIME,
            stale_after=BASE_TIME + timedelta(seconds=60),
            expires_at=BASE_TIME + timedelta(seconds=120),
            verification_method="invalid",
            content_digest="sha256:invalid",
        )
    )

    with pytest.raises(IntegrityError):
        db.flush()


def test_persistence_surface_is_append_only_and_source_deletion_is_restricted():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    public_functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    source_fk = next(
        foreign_key
        for foreign_key in models.LiveUtilityObservation.__table__.foreign_keys
        if foreign_key.target_fullname == "live_utility_sources.source_id"
    )

    assert not any(name.startswith(("update", "delete")) for name in public_functions)
    assert source_fk.ondelete == "RESTRICT"


def test_persistence_module_has_no_network_retrieval_behavior():
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert imports.isdisjoint({"httpx", "requests", "urllib", "socket", "aiohttp"})
