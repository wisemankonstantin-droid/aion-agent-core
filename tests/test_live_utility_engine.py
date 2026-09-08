from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models
from app.db import engine as database_engine
from app.services.live_utility import (
    FreshnessState,
    RefreshPolicy,
    RefreshStrategy,
    SourceDefinition,
    SourceTier,
)
from app.services.live_utility_engine import (
    EnginePolicy,
    LiveUtilityEngine,
    RefreshStatus,
    canonical_digest,
)
from app.services.live_utility_sources import (
    AdapterResponse,
    SourceValidationError,
)
from app.services.safe_http import FetchPolicy, FetchResult


NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
PAYLOAD = {
    "tag_name": "v1.0.0",
    "name": "A2A 1.0.0",
    "published_at": "2026-03-12T16:34:00Z",
    "html_url": "https://github.com/a2aproject/A2A/releases/tag/v1.0.0",
    "prerelease": False,
    "draft": False,
    "id": 100,
}


@pytest.fixture
def db():
    session = Session(bind=database_engine, autoflush=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _source(*, enabled=True):
    return SourceDefinition(
        source_id="official-a2a-protocol-release",
        display_name="Official A2A protocol release",
        tier=SourceTier.TIER_1,
        source_kind="official_github_release_api",
        canonical_locator="https://api.github.com/repos/a2aproject/A2A/releases/latest",
        refresh_policy=RefreshPolicy(
            strategies=frozenset(
                {RefreshStrategy.TTL, RefreshStrategy.DEMAND_DRIVEN}
            ),
            stale_after_seconds=60,
            expires_after_seconds=120,
        ),
        enabled=enabled,
    )


@dataclass
class FakeAdapter:
    source: SourceDefinition
    responses: list[AdapterResponse]
    subject_key: str = "a2a.protocol_release"
    fetch_policy: FetchPolicy = FetchPolicy(max_attempts=2)
    calls: int = 0

    def retrieve(self):
        self.calls += 1
        return self.responses.pop(0)

    def normalize(self, payload):
        if not isinstance(payload, dict) or "tag_name" not in payload:
            raise SourceValidationError("tag_name is missing")
        return {
            "protocol": "a2a",
            "version": payload["tag_name"],
            "release_name": payload["name"],
            "published_at": payload["published_at"],
            "official_url": payload["html_url"],
            "prerelease": payload["prerelease"],
            "draft": payload["draft"],
            "release_id": payload["id"],
        }

    def source_revision(self, normalized):
        return normalized["version"]


def _ok(payload=PAYLOAD):
    return AdapterResponse(FetchResult(200, b"fixture", None, 1), payload)


def _engine(db, responses, *, source=None, policy=EnginePolicy()):
    adapter = FakeAdapter(source or _source(), list(responses))
    engine = LiveUtilityEngine((adapter,), policy=policy)
    engine.ensure_sources(db)
    return engine, adapter


def test_success_normalizes_verifies_stores_and_returns_fresh_current_state(db):
    engine, _ = _engine(db, [_ok()])

    result = engine.refresh_source(
        db,
        source_id=_source().source_id,
        now=NOW,
    )

    assert result.status is RefreshStatus.REFRESHED_CHANGED
    assert result.current_state.freshness.state is FreshnessState.FRESH
    assert result.current_state.verified is True
    assert result.current_state.normalized_data["version"] == "v1.0.0"
    assert result.current_state.observation.verification_method is not None
    assert result.change.previous_observation_id is None


def test_network_failure_preserves_last_known_good_observation(db):
    engine, _ = _engine(
        db,
        [
            _ok(),
            AdapterResponse(FetchResult(None, None, "TimeoutError:timed out", 2), None),
        ],
    )
    first = engine.refresh_source(db, source_id=_source().source_id, now=NOW)

    failed = engine.refresh_source(
        db,
        source_id=_source().source_id,
        now=NOW + timedelta(seconds=10),
        demand=True,
    )

    assert failed.status is RefreshStatus.FETCH_FAILED
    assert failed.error.startswith("TimeoutError")
    assert failed.current_state.observation.observation_id == first.current_state.observation.observation_id
    assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 1


def test_malformed_payload_is_not_stored_or_verified(db):
    engine, _ = _engine(db, [_ok({"unexpected": True})])

    result = engine.refresh_source(db, source_id=_source().source_id, now=NOW)

    assert result.status is RefreshStatus.VALIDATION_FAILED
    assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 0
    assert db.scalar(select(func.count()).select_from(models.LiveUtilityVerification)) == 0


def test_identical_refresh_adds_verification_but_not_material_version(db):
    engine, _ = _engine(db, [_ok(), _ok()])
    first = engine.refresh_source(db, source_id=_source().source_id, now=NOW)
    second = engine.refresh_source(
        db,
        source_id=_source().source_id,
        now=NOW + timedelta(seconds=30),
        demand=True,
    )

    assert first.status is RefreshStatus.REFRESHED_CHANGED
    assert second.status is RefreshStatus.REFRESHED_UNCHANGED
    assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 1
    assert db.scalar(select(func.count()).select_from(models.LiveUtilityVerification)) == 2
    assert second.current_state.freshness.state is FreshnessState.FRESH
    assert second.current_state.observation.stale_after == NOW + timedelta(seconds=90)


def test_changed_refresh_appends_lineage_and_structured_diff(db):
    changed = dict(PAYLOAD, tag_name="v1.1.0", name="A2A 1.1.0", id=101)
    engine, _ = _engine(db, [_ok(), _ok(changed)])
    first = engine.refresh_source(db, source_id=_source().source_id, now=NOW)
    second = engine.refresh_source(
        db,
        source_id=_source().source_id,
        now=NOW + timedelta(seconds=30),
        demand=True,
    )

    assert second.status is RefreshStatus.REFRESHED_CHANGED
    assert second.current_state.observation.previous_observation_id == first.current_state.observation.observation_id
    changes = {change.field: (change.before, change.after) for change in second.change.changes}
    assert changes["version"] == ("v1.0.0", "v1.1.0")
    assert changes["release_name"] == ("A2A 1.0.0", "A2A 1.1.0")
    assert "official_url" not in changes


def test_digest_is_stable_across_mapping_order():
    assert canonical_digest({"a": 1, "b": 2}) == canonical_digest({"b": 2, "a": 1})


def test_fresh_source_is_skipped_without_fetch(db):
    engine, adapter = _engine(db, [_ok()])
    engine.refresh_source(db, source_id=_source().source_id, now=NOW)

    result = engine.refresh_source(
        db,
        source_id=_source().source_id,
        now=NOW + timedelta(seconds=1),
    )

    assert result.status is RefreshStatus.SKIPPED_NOT_DUE
    assert adapter.calls == 1


def test_disabled_source_never_fetches(db):
    engine, adapter = _engine(db, [_ok()], source=_source(enabled=False))

    result = engine.refresh_source(db, source_id=_source().source_id, now=NOW)

    assert result.status is RefreshStatus.DISABLED
    assert adapter.calls == 0


def test_request_budget_prevents_fetch_amplification(db):
    engine, adapter = _engine(
        db,
        [_ok()],
        policy=EnginePolicy(request_budget=1),
    )

    result = engine.refresh_source(db, source_id=_source().source_id, now=NOW)

    assert result.status is RefreshStatus.FETCH_FAILED
    assert result.error == "request_budget_exceeded"
    assert adapter.calls == 0


def test_circuit_opens_after_bounded_failures_and_suppresses_fetch(db):
    failed = AdapterResponse(FetchResult(None, None, "connection_failed", 2), None)
    engine, adapter = _engine(
        db,
        [failed, failed, _ok()],
        policy=EnginePolicy(circuit_failure_threshold=2),
    )
    assert engine.refresh_source(db, source_id=_source().source_id, now=NOW).status is RefreshStatus.FETCH_FAILED
    assert engine.refresh_source(db, source_id=_source().source_id, now=NOW).status is RefreshStatus.FETCH_FAILED

    result = engine.refresh_source(db, source_id=_source().source_id, now=NOW)

    assert result.status is RefreshStatus.CIRCUIT_OPEN
    assert adapter.calls == 2


def test_current_state_freshness_transitions_are_deterministic(db):
    engine, _ = _engine(db, [_ok()])
    engine.refresh_source(db, source_id=_source().source_id, now=NOW)

    assert engine.get_current_state(db, source_id=_source().source_id, subject_key="a2a.protocol_release", now=NOW + timedelta(seconds=59)).freshness.state is FreshnessState.FRESH
    assert engine.get_current_state(db, source_id=_source().source_id, subject_key="a2a.protocol_release", now=NOW + timedelta(seconds=60)).freshness.state is FreshnessState.STALE
    assert engine.get_current_state(db, source_id=_source().source_id, subject_key="a2a.protocol_release", now=NOW + timedelta(seconds=120)).freshness.state is FreshnessState.EXPIRED


def test_restart_reconstructs_current_state_and_change_from_database(db):
    changed = dict(PAYLOAD, tag_name="v1.1.0", name="A2A 1.1.0", id=101)
    engine, _ = _engine(db, [_ok(), _ok(changed)])
    engine.refresh_source(db, source_id=_source().source_id, now=NOW)
    engine.refresh_source(
        db,
        source_id=_source().source_id,
        now=NOW + timedelta(seconds=5),
        demand=True,
    )
    db.expunge_all()

    restarted = LiveUtilityEngine((FakeAdapter(_source(), []),))
    state = restarted.get_current_state(
        db,
        source_id=_source().source_id,
        subject_key="a2a.protocol_release",
        now=NOW + timedelta(seconds=6),
    )

    assert state.normalized_data["version"] == "v1.1.0"
    assert state.freshness.state is FreshnessState.FRESH
    assert {change.field for change in state.latest_change.changes} >= {
        "version",
        "release_name",
        "release_id",
    }
