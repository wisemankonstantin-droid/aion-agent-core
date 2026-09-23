from __future__ import annotations

import json

from sqlalchemy import delete, select

from app import models
from app.acquisition import WORKERS
from app.db import SessionLocal
from app.main import app
from app.services import acquisition_agent_mind, acquisition_swarm
from fastapi.testclient import TestClient


client = TestClient(app)


def _clean_minds():
    with SessionLocal() as db:
        db.execute(delete(models.AcquisitionAgentMind))
        db.commit()


def _plan(worker_id: str) -> dict:
    return {
        "decision_summary": f"seek current buyer demand for {worker_id}",
        "hypothesis": "Explicit current spend language will convert better than generic agent listings.",
        "channel_priority": ["federated_a2a", "colony"],
        "search_queries": ["need paid provider now", "looking to hire agent service"],
        "contact_policy": "contact_one_if_qualified",
        "target_preference": "explicit_buyer_demand",
        "expected_signal": "routing_need",
        "learning_goal": "Compare explicit buyer demand with generic discovery.",
        "memory_note": "Prefer current buyer verbs over seller capability language.",
        "confidence": 72,
    }


def test_all_100_workers_have_distinct_cognitive_fingerprints():
    profiles = [acquisition_agent_mind.cognitive_profile(worker) for worker in WORKERS]

    assert len(profiles) == 100
    assert len({row["strategy_fingerprint"] for row in profiles}) == 100
    assert all(row["intent_profile"] for row in profiles)
    assert all(20 <= row["exploration_bias"] <= 80 for row in profiles)
    assert all(20 <= row["verification_bias"] <= 80 for row in profiles)
    assert all(20 <= row["conversion_bias"] <= 80 for row in profiles)


def test_unconfigured_model_fails_open_to_existing_transport_without_fake_thinking(
    monkeypatch,
):
    _clean_minds()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AION_AGENT_MINDS_ENABLED", raising=False)

    plans = acquisition_agent_mind.refresh_all_minds(
        WORKERS[:3],
        channel_health={"federated_a2a": {"public_discovery": True}},
        send_enabled=True,
        fallback_queries_by_worker={
            worker.id: ["provider selection", "paid api"] for worker in WORKERS[:3]
        },
    )

    assert plans == {}
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(models.AcquisitionAgentMind)
                .where(
                    models.AcquisitionAgentMind.worker_id.in_(
                        [worker.id for worker in WORKERS[:3]]
                    )
                )
                .order_by(models.AcquisitionAgentMind.worker_id)
            )
        )
    assert len(rows) == 3
    assert {row.last_state for row in rows} == {"model_unconfigured"}
    assert all(row.total_reasoning_calls == 0 for row in rows)


def test_model_refresh_gives_each_worker_own_plan_and_durable_safe_memory(monkeypatch):
    _clean_minds()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("AION_AGENT_MINDS_ENABLED", "true")
    monkeypatch.setenv("AION_AGENT_MIND_MAX_CALLS_PER_CYCLE", "100")
    monkeypatch.setattr(
        acquisition_agent_mind,
        "_call_model",
        lambda worker_id, observation: _plan(worker_id),
    )
    workers = WORKERS[:4]

    plans = acquisition_agent_mind.refresh_all_minds(
        workers,
        channel_health={
            "moltbook": {"suspended": True},
            "colony": {"public_discovery": True, "authenticated_write": False},
            "federated_a2a": {"public_discovery": True},
        },
        send_enabled=True,
        fallback_queries_by_worker={
            worker.id: ["fallback one", "fallback two"] for worker in workers
        },
    )

    assert set(plans) == {worker.id for worker in workers}
    assert len({plans[worker.id]["decision_summary"] for worker in workers}) == 4
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(models.AcquisitionAgentMind).where(
                    models.AcquisitionAgentMind.worker_id.in_(
                        [worker.id for worker in workers]
                    )
                )
            )
        )
    assert len(rows) == 4
    assert {row.last_state for row in rows} == {"planned"}
    assert all(row.total_reasoning_calls == 1 for row in rows)
    assert all(row.last_plan_digest.startswith("sha256:") for row in rows)
    assert "test-key-never-sent" not in json.dumps(
        [
            {
                "profile": row.cognitive_profile,
                "memory": row.safe_memory,
                "plan": row.last_plan,
                "error": row.last_error,
            }
            for row in rows
        ]
    )


def test_plan_validation_and_executor_policy_fail_closed():
    plan = acquisition_agent_mind._validate_plan(
        {
            "decision_summary": "x",
            "hypothesis": "y",
            "channel_priority": [
                "federated_a2a",
                "invalid-channel",
                "colony",
                "moltbook",
            ],
            "search_queries": ["one", "two", "three"],
            "contact_policy": "invalid-policy",
            "target_preference": "invalid-target-preference",
            "expected_signal": "need",
            "learning_goal": "learn",
            "memory_note": "remember",
            "confidence": 999,
        },
        ["fallback"],
    )
    assert plan["channel_priority"] == [
        "federated_a2a",
        "colony",
        "moltbook",
    ]
    assert plan["search_queries"] == ["one", "two"]
    assert plan["contact_policy"] == "discover_only"
    assert plan["target_preference"] == "current_external_spend_intent"
    assert plan["confidence"] == 100

    discover = acquisition_swarm._mind_transport_policy(
        {
            **plan,
            "channel_priority": ["colony"],
            "contact_policy": "discover_only",
        },
        ("fallback",),
    )
    assert discover["discover_allowed"] is True
    assert discover["contact_allowed"] is False
    assert discover["channels"] == {"colony"}

    hold = acquisition_swarm._mind_transport_policy(
        {
            **plan,
            "channel_priority": ["hold", "federated_a2a"],
            "contact_policy": "contact_one_if_qualified",
        },
        ("fallback",),
    )
    assert hold["discover_allowed"] is False
    assert hold["contact_allowed"] is False
    assert hold["channels"] == set()
    assert hold["queries"] == ()

    fallback = acquisition_swarm._mind_transport_policy(
        None,
        ("fallback-one", "fallback-two"),
    )
    assert fallback["model_controls_transport"] is False
    assert fallback["contact_allowed"] is True
    assert fallback["channels"] == {"moltbook", "colony", "federated_a2a"}


def test_worker_outcome_memory_is_bounded_and_drops_unapproved_fields(monkeypatch):
    _clean_minds()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    worker = WORKERS[0]
    acquisition_agent_mind.refresh_all_minds(
        [worker],
        channel_health={},
        send_enabled=True,
        fallback_queries_by_worker={worker.id: ["fallback"]},
    )

    for index in range(12):
        acquisition_agent_mind.record_worker_outcome(
            worker.id,
            {
                "new_targets": index,
                "qualified_targets": index // 2,
                "contact_attempted": True,
                "channel": "federated_a2a",
                "result_class": "response_received",
                "response_received": True,
                "routing_feedback_count": 1,
                "raw_response": "PRIVATE-MATERIAL-MUST-NOT-PERSIST",
                "api_key": "SECRET-MUST-NOT-PERSIST",
            },
        )

    with SessionLocal() as db:
        row = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id == worker.id
            )
        )
        assert row is not None
        serialized = json.dumps(row.safe_memory)
        assert "PRIVATE-MATERIAL-MUST-NOT-PERSIST" not in serialized
        assert "SECRET-MUST-NOT-PERSIST" not in serialized
        assert len(row.safe_memory["recent_outcomes"]) == (
            acquisition_agent_mind.MAX_MEMORY_OUTCOMES
        )
        assert row.safe_memory["channel_performance"]["federated_a2a"][
            "responses"
        ] == 12


def test_live_temple_exposes_safe_separate_mind_and_transport_state(monkeypatch):
    _clean_minds()
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-appear-in-live-temple")
    worker = WORKERS[0]
    now = acquisition_agent_mind._now()
    with SessionLocal() as db:
        db.add(
            models.AcquisitionAgentMind(
                worker_id=worker.id,
                mind_version="1",
                model="gpt-6-luna",
                cognitive_profile=acquisition_agent_mind.cognitive_profile(worker),
                safe_memory={
                    "recent_outcomes": [],
                    "channel_performance": {},
                    "lessons": ["avoid generic seller listings"],
                },
                last_plan=_plan(worker.id),
                last_observation_digest="sha256:" + "a" * 64,
                last_plan_digest="sha256:" + "b" * 64,
                last_state="planned",
                total_reasoning_calls=7,
                reasoning_failures=1,
                last_reasoned_at=now,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    response = client.get("/temple/live/state")
    assert response.status_code == 200
    data = response.json()
    found = next(row for row in data["fleet"]["workers"] if row["id"] == worker.id)
    assert found["mind"]["state"] == "planned"
    assert found["mind"]["model"] == "gpt-6-luna"
    assert found["mind"]["profile"]["strategy_fingerprint"]
    assert found["mind"]["plan"]["hypothesis"]
    assert found["mind"]["total_reasoning_calls"] == 7
    assert data["fleet"]["mind_runtime"]["initialized_minds"] >= 1
    assert data["privacy"]["model_credentials_exposed"] is False
    assert data["privacy"]["model_raw_prompts_exposed"] is False
    assert data["privacy"]["model_chain_of_thought_exposed"] is False
    serialized = json.dumps(data)
    assert "must-never-appear-in-live-temple" not in serialized
    assert "OPENAI_API_KEY" not in serialized
