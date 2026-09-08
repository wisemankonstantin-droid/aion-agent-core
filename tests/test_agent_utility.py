from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import Base
from app.services import live_utility_store
from app.services.agent_utility import assess_compatibility, select_current_utility
from app.services.live_utility_engine import LiveUtilityEngine, RefreshStatus
from app.services.live_utility import FreshnessState, SourceObservation
from app.services.live_utility_sources import (
    AdapterResponse,
    VERIFICATION_METHOD,
    configured_tier1_adapters,
)
from app.services.safe_http import FetchPolicy, FetchResult


NOW = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _seed(
    db,
    subject="a2a",
    *,
    state=FreshnessState.FRESH,
    version="v1.0.1",
    now=NOW,
    previous=None,
):
    adapter = {
        item.subject_key.split(".", 1)[0]: item
        for item in configured_tier1_adapters()
    }[subject]
    if live_utility_store.get_source(db, adapter.source.source_id) is None:
        live_utility_store.register_source(db, adapter.source)

    observed_at = now - timedelta(hours=2)
    valid_from = observed_at
    stale_after = now + timedelta(days=1)
    expires_at = now + timedelta(days=2)
    verified_at = now - timedelta(hours=1)
    if state is FreshnessState.STALE:
        stale_after = now
    elif state is FreshnessState.EXPIRED:
        stale_after = now - timedelta(hours=1)
        expires_at = now
    elif state is FreshnessState.UNVERIFIED:
        verified_at = None
    elif state is FreshnessState.NOT_YET_VALID:
        valid_from = now + timedelta(hours=1)
        stale_after = now + timedelta(hours=2)
        expires_at = now + timedelta(hours=3)

    observation_id = "obs-test-" + uuid.uuid4().hex
    observation = SourceObservation(
        observation_id=observation_id,
        source_id=adapter.source.source_id,
        subject_key=adapter.subject_key,
        source_revision=version,
        previous_observation_id=previous,
        observed_at=observed_at,
        verified_at=verified_at,
        valid_from=valid_from,
        stale_after=stale_after,
        expires_at=expires_at,
        verification_method=VERIFICATION_METHOD if verified_at else None,
        content_digest="sha256:" + uuid.uuid4().hex,
    )
    normalized = {
        "protocol": subject,
        "version": version,
        "release_name": f"{subject.upper()} {version}",
        "published_at": observed_at.isoformat(),
        "official_url": f"https://github.com/example/{subject}/releases/tag/{version}",
        "prerelease": False,
        "draft": False,
        "release_id": 1,
    }
    live_utility_store.append_observation(db, observation, normalized_data=normalized)
    if verified_at is not None:
        live_utility_store.append_verification(
            db,
            live_utility_store.VerificationRecord(
                verification_id="verify-test-" + uuid.uuid4().hex,
                source_id=observation.source_id,
                subject_key=observation.subject_key,
                observation_id=observation.observation_id,
                verified_at=verified_at,
                valid_from=valid_from,
                stale_after=stale_after,
                expires_at=expires_at,
                verification_method=VERIFICATION_METHOD,
                content_digest=observation.content_digest,
            ),
        )
    db.commit()
    return observation


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ({}, "unknown"),
        ({"supported_protocols": ["mcp"]}, "incompatible"),
        ({"supported_protocols": ["a2a"]}, "partially_compatible"),
        (
            {
                "supported_protocols": ["a2a"],
                "supported_protocol_versions": {"a2a": ["1.0.1"]},
            },
            "compatible",
        ),
        (
            {
                "supported_protocols": ["a2a"],
                "supported_protocol_versions": {"a2a": ["0.3"]},
            },
            "incompatible",
        ),
    ],
)
def test_compatibility_v1_is_explainable(context, expected):
    parsed = schemas.UtilityCompatibilityContext.model_validate(context)
    decision = assess_compatibility("a2a", "v1.0.1", parsed)
    assert decision.decision == expected
    assert decision.reasons


@pytest.mark.parametrize(
    ("freshness", "eligible", "result_present"),
    [
        (FreshnessState.FRESH, True, True),
        (FreshnessState.STALE, False, False),
        (FreshnessState.EXPIRED, False, False),
        (FreshnessState.UNVERIFIED, False, False),
        (FreshnessState.NOT_YET_VALID, False, False),
    ],
)
def test_freshness_states_never_masquerade_as_current(
    db, freshness, eligible, result_present
):
    _seed(db, state=freshness)
    response = select_current_utility(
        db,
        schemas.UtilityQuery(subject="a2a"),
        now=NOW,
    )
    result = response["results"][0]
    assert result["freshness"]["state"] == freshness.value
    assert result["current_eligibility"] is eligible
    assert (result["result"] is not None) is result_present
    if not eligible:
        assert result["last_known_value"] is not None
        assert result["warnings"]


def test_evidence_provenance_and_trust_are_distinct(db):
    observation = _seed(db)
    result = select_current_utility(
        db,
        schemas.UtilityQuery(subject="a2a"),
        now=NOW,
    )["results"][0]

    assert result["source"]["tier"] == "tier_1"
    assert result["source"]["source_revision"] == "v1.0.1"
    assert result["evidence"]["observation_id"] == observation.observation_id
    assert result["evidence"]["verification_level"] == "source_observation_verified"
    assert result["evidence"]["source_tier_is_not_verification"] is True
    assert result["trust"]["declared_endpoint_used"] is False
    assert result["latest_material_change"]["changes"]


def test_no_result_is_explicit_and_bounded(db):
    response = select_current_utility(
        db,
        schemas.UtilityQuery(subject="mcp"),
        now=NOW,
    )
    assert response["status"] == "no_result"
    assert response["results"] == []
    assert response["missing_subjects"] == ["mcp.protocol_release"]


def test_failed_refresh_cannot_relabel_stale_last_known_evidence(db):
    _seed(db, state=FreshnessState.STALE)
    configured = configured_tier1_adapters()[0]

    class FailedAdapter:
        source = configured.source
        subject_key = configured.subject_key
        fetch_policy = FetchPolicy(max_attempts=1)

        def retrieve(self):
            return AdapterResponse(
                FetchResult(None, None, "connection_failed", 1),
                None,
            )

    refresh = LiveUtilityEngine((FailedAdapter(),))
    outcome = refresh.refresh_source(
        db,
        source_id=configured.source.source_id,
        now=NOW,
        demand=True,
    )
    response = select_current_utility(
        db,
        schemas.UtilityQuery(subject="a2a"),
        now=NOW,
    )
    result = response["results"][0]
    assert outcome.status is RefreshStatus.FETCH_FAILED
    assert result["freshness"]["state"] == "stale"
    assert result["current_eligibility"] is False
    assert result["result"] is None


def test_request_context_cannot_select_a_url_or_trigger_fetch(db, monkeypatch):
    _seed(db)

    def forbidden(*args, **kwargs):
        raise AssertionError("network retrieval must not be called")

    for adapter in configured_tier1_adapters():
        monkeypatch.setattr(type(adapter), "retrieve", forbidden)
    response = select_current_utility(
        db,
        schemas.UtilityQuery.model_validate(
            {
                "subject": "a2a",
                "context": {"constraints": ["https://127.0.0.1/private"]},
            }
        ),
        now=NOW,
    )
    assert response["network_fetch_performed"] is False


def test_personalized_delta_is_durable_and_subject_scoped(db):
    first = _seed(db)
    agent = models.Agent(
        external_id="delta-agent",
        name="Delta Agent",
        api_key_hash="delta-hash",
    )
    db.add(agent)
    db.commit()
    agent_id = agent.id
    query = schemas.UtilityQuery(subject="a2a")

    baseline = select_current_utility(
        db, query, now=NOW, agent_id=agent_id
    )["results"][0]["personalized_delta"]
    db.commit()
    db.expunge_all()
    unchanged = select_current_utility(
        db, query, now=NOW + timedelta(minutes=1), agent_id=agent_id
    )["results"][0]["personalized_delta"]
    db.commit()
    assert baseline["status"] == "baseline_created"
    assert unchanged["status"] == "unchanged"

    _seed(
        db,
        version="v1.1.0",
        now=NOW + timedelta(minutes=2),
        previous=first.observation_id,
    )
    changed = select_current_utility(
        db, query, now=NOW + timedelta(minutes=2), agent_id=agent_id
    )["results"][0]["personalized_delta"]
    assert changed["status"] == "changed"
    assert changed["changed"] is True
    assert db.scalar(
        select(func.count()).select_from(models.AgentUtilityCheckpoint)
    ) == 1

    missing = select_current_utility(
        db,
        schemas.UtilityQuery(subject="mcp"),
        now=NOW + timedelta(minutes=3),
        agent_id=agent_id,
    )
    assert missing["status"] == "no_result"
    assert db.scalar(
        select(func.count()).select_from(models.AgentUtilityCheckpoint)
    ) == 1


def test_context_bounds_are_enforced():
    with pytest.raises(ValueError):
        schemas.UtilityQuery.model_validate(
            {"context": {"supported_protocols": ["a2a"] * 9}}
        )
    with pytest.raises(ValueError):
        schemas.UtilityQuery.model_validate(
            {"context": {"supported_protocol_versions": {"a2a": ["1"] * 17}}}
        )
