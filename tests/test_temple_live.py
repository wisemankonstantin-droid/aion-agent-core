from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.acquisition import WORKER_COUNT, WORKER_SHARDS, WORKERS, WORKERS_PER_CYCLE
from app.main import app
from app.services import acquisition_swarm


client = TestClient(app)


def test_network_roster_has_100_unique_transparent_workers():
    assert WORKER_COUNT == 100
    assert len(WORKERS) == 100
    assert len({worker.id for worker in WORKERS}) == 100
    assert WORKER_SHARDS == 4
    assert WORKERS_PER_CYCLE == 25
    assert {worker.lane for worker in WORKERS} == set(acquisition_swarm.INTENT_WORKERS)
    assert {worker.preferred_channel for worker in WORKERS} == {
        "federated_a2a",
        "moltbook",
        "hybrid",
    }


def test_worker_shards_rotate_all_100_without_parallel_api_burst():
    slots = [
        acquisition_swarm._active_workers_for_cycle(
            now_seconds=index * acquisition_swarm.DEFAULT_INTERVAL_SECONDS
        )
        for index in range(WORKER_SHARDS)
    ]
    assert all(len(slot) == 25 for slot in slots)
    ids = [{worker.id for worker in slot} for slot in slots]
    assert len(set().union(*ids)) == 100
    for index, left in enumerate(ids):
        for right in ids[index + 1 :]:
            assert left.isdisjoint(right)


def test_temple_live_page_is_browser_native_and_contains_no_operator_data():
    response = client.get("/temple/live")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "AION TEMPLE LIVE" in response.text
    assert "<canvas" in response.text
    assert "/temple/live/state" in response.text
    assert "AION_AMBASSADOR_CONTROL_TOKEN" not in response.text


def test_temple_live_state_requires_existing_operator_gate(monkeypatch):
    token = "t" * 48
    monkeypatch.setenv("AION_AMBASSADOR_CONTROL_TOKEN", token)

    denied = client.get("/temple/live/state")
    assert denied.status_code == 401

    response = client.get(
        "/temple/live/state",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["core"]["worker_count"] == 100
    assert data["core"]["active_worker_count"] == 25
    assert len(data["workers"]) == 100
    assert data["north_star"] == "FIRST_REAL_SETTLED_AGENT_TRANSACTION"
    assert data["privacy"]["raw_secrets_exposed"] is False
    assert token not in json.dumps(data)
