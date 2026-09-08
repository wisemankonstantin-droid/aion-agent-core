import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.live_utility import (
    FreshnessState,
    RefreshPolicy,
    RefreshStrategy,
    SourceDefinition,
    SourceObservation,
    SourceRegistry,
    SourceTier,
    evaluate_freshness,
    materialize_refresh_window,
)


BASE_TIME = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "live_utility.py"


def _policy() -> RefreshPolicy:
    return RefreshPolicy(
        strategies=frozenset({RefreshStrategy.TTL, RefreshStrategy.DEMAND_DRIVEN}),
        stale_after_seconds=60,
        expires_after_seconds=120,
    )


def _tier1_protocol_source(*, enabled: bool = True) -> SourceDefinition:
    return SourceDefinition(
        source_id="fixture-tier1-protocol-spec",
        display_name="Protocol specification fixture",
        tier=SourceTier.TIER_1,
        source_kind="fixture",
        canonical_locator="fixture:tier1:protocol-spec",
        refresh_policy=_policy(),
        enabled=enabled,
    )


def _tier1_release_source() -> SourceDefinition:
    return SourceDefinition(
        source_id="fixture-tier1-official-release",
        display_name="Official release fixture",
        tier=SourceTier.TIER_1,
        source_kind="fixture",
        canonical_locator="fixture:tier1:official-release",
        refresh_policy=_policy(),
    )


def _observation(
    *,
    observed_at: datetime = BASE_TIME,
    verified_at: datetime | None = BASE_TIME,
    valid_from: datetime = BASE_TIME,
    stale_after: datetime = BASE_TIME + timedelta(seconds=60),
    expires_at: datetime = BASE_TIME + timedelta(seconds=120),
    previous_observation_id: str | None = None,
    observation_id: str = "observation-2",
) -> SourceObservation:
    return SourceObservation(
        observation_id=observation_id,
        source_id="fixture-tier1-protocol-spec",
        subject_key="a2a.protocol",
        source_revision="1.0.0",
        previous_observation_id=previous_observation_id,
        observed_at=observed_at,
        verified_at=verified_at,
        valid_from=valid_from,
        stale_after=stale_after,
        expires_at=expires_at,
        verification_method="fixture-review" if verified_at else None,
        content_digest="sha256:fixture-content",
    )


def test_registry_accepts_unique_sources_and_lookup_works():
    registry = SourceRegistry([_tier1_protocol_source(), _tier1_release_source()])

    assert registry.get("fixture-tier1-protocol-spec") == _tier1_protocol_source()
    assert registry.list() == (_tier1_protocol_source(), _tier1_release_source())


def test_registry_rejects_duplicate_source_id():
    registry = SourceRegistry([_tier1_protocol_source()])

    with pytest.raises(ValueError, match="duplicate source_id"):
        registry.register(_tier1_protocol_source())


def test_registry_filters_by_tier_and_preserves_disabled_sources():
    disabled = _tier1_protocol_source(enabled=False)
    tier2 = SourceDefinition(
        source_id="ecosystem-registry",
        display_name="Ecosystem registry",
        tier=SourceTier.TIER_2,
        source_kind="fixture",
        canonical_locator="fixture:tier2:registry",
        refresh_policy=_policy(),
    )
    registry = SourceRegistry([disabled, tier2])

    assert registry.list(tier=SourceTier.TIER_1) == (disabled,)
    assert registry.get(disabled.source_id).enabled is False


def test_tier1_fixtures_do_not_imply_verified_observations():
    registry = SourceRegistry([_tier1_protocol_source(), _tier1_release_source()])
    observation = _observation(verified_at=None)

    assert registry.get(observation.source_id).tier is SourceTier.TIER_1
    assessment = evaluate_freshness(observation, BASE_TIME + timedelta(seconds=1))
    assert assessment.state is FreshnessState.UNVERIFIED
    assert assessment.eligible_for_consequential_use is False


def test_observation_preserves_explicit_version_lineage():
    first = _observation(observation_id="observation-1")
    second = _observation(previous_observation_id=first.observation_id)

    assert second.previous_observation_id == "observation-1"
    assert second.source_revision == "1.0.0"
    assert second.content_digest == "sha256:fixture-content"


@pytest.mark.parametrize("field_name", ["observed_at", "valid_from", "stale_after", "expires_at"])
def test_observation_rejects_naive_required_timestamps(field_name):
    values = {
        "observed_at": BASE_TIME,
        "valid_from": BASE_TIME,
        "stale_after": BASE_TIME + timedelta(seconds=60),
        "expires_at": BASE_TIME + timedelta(seconds=120),
    }
    values[field_name] = values[field_name].replace(tzinfo=None)

    with pytest.raises(ValueError, match="timezone-aware"):
        _observation(**values)


def test_observation_rejects_naive_verified_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        _observation(verified_at=BASE_TIME.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("valid_from", "stale_after", "expires_at"),
    [
        (BASE_TIME + timedelta(seconds=61), BASE_TIME + timedelta(seconds=60), BASE_TIME + timedelta(seconds=120)),
        (BASE_TIME, BASE_TIME + timedelta(seconds=121), BASE_TIME + timedelta(seconds=120)),
    ],
)
def test_observation_rejects_invalid_timestamp_ordering(valid_from, stale_after, expires_at):
    with pytest.raises(ValueError):
        _observation(valid_from=valid_from, stale_after=stale_after, expires_at=expires_at)


def test_not_yet_valid_precedes_other_states_and_does_not_require_refresh():
    assessment = evaluate_freshness(
        _observation(valid_from=BASE_TIME + timedelta(seconds=10)), BASE_TIME
    )

    assert assessment.state is FreshnessState.NOT_YET_VALID
    assert assessment.refresh_required is False
    assert assessment.eligible_for_consequential_use is False


def test_unverified_observation_requires_refresh_and_is_not_eligible():
    assessment = evaluate_freshness(_observation(verified_at=None), BASE_TIME)

    assert assessment.state is FreshnessState.UNVERIFIED
    assert assessment.refresh_required is True
    assert assessment.eligible_for_consequential_use is False


def test_verified_observation_is_fresh_before_stale_boundary():
    assessment = evaluate_freshness(_observation(), BASE_TIME + timedelta(seconds=59))

    assert assessment.state is FreshnessState.FRESH
    assert assessment.refresh_required is False
    assert assessment.eligible_for_consequential_use is True


def test_stale_boundary_is_inclusive():
    assessment = evaluate_freshness(_observation(), BASE_TIME + timedelta(seconds=60))

    assert assessment.state is FreshnessState.STALE
    assert assessment.refresh_required is True
    assert assessment.eligible_for_consequential_use is False


def test_stale_observation_requires_refresh_and_is_not_eligible():
    assessment = evaluate_freshness(_observation(), BASE_TIME + timedelta(seconds=90))

    assert assessment.state is FreshnessState.STALE
    assert assessment.refresh_required is True
    assert assessment.eligible_for_consequential_use is False


def test_expiry_boundary_is_inclusive_and_overrides_verification():
    assessment = evaluate_freshness(
        _observation(verified_at=None), BASE_TIME + timedelta(seconds=120)
    )

    assert assessment.state is FreshnessState.EXPIRED
    assert assessment.refresh_required is True
    assert assessment.eligible_for_consequential_use is False


def test_freshness_evaluation_is_deterministic_for_explicit_now():
    observation = _observation()
    now = BASE_TIME + timedelta(seconds=30)

    assert evaluate_freshness(observation, now) == evaluate_freshness(observation, now)


@pytest.mark.parametrize(
    "strategies, stale_after_seconds, expires_after_seconds",
    [
        (frozenset(), 60, 120),
        (frozenset({RefreshStrategy.TTL}), 0, 120),
        (frozenset({RefreshStrategy.TTL}), 60, 0),
        (frozenset({RefreshStrategy.TTL}), 120, 60),
    ],
)
def test_refresh_policy_rejects_invalid_relationships(strategies, stale_after_seconds, expires_after_seconds):
    with pytest.raises(ValueError):
        RefreshPolicy(strategies, stale_after_seconds, expires_after_seconds)


def test_policy_materialization_is_deterministic_and_timezone_safe():
    stale_after, expires_at = materialize_refresh_window(BASE_TIME, _policy())

    assert stale_after == BASE_TIME + timedelta(seconds=60)
    assert expires_at == BASE_TIME + timedelta(seconds=120)
    with pytest.raises(ValueError, match="timezone-aware"):
        materialize_refresh_window(BASE_TIME.replace(tzinfo=None), _policy())


def test_module_has_no_network_imports_or_retrieval_calls():
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

    network_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert imports.isdisjoint({"httpx", "requests", "urllib", "socket", "aiohttp"})
    assert network_calls.isdisjoint({"connect", "get", "post", "request", "urlopen"})
