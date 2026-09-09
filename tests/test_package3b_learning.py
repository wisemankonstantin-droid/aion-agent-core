import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import models, schemas
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.services import learning_engine, rate_limit, safe_http
from app.services.live_utility_engine import LiveUtilityEngine
from app.services.live_utility_sources import AdapterResponse, configured_tier1_adapters
from app.services.safe_http import FetchPolicy, FetchResult


client = TestClient(app)
NOW = datetime(2026, 9, 9, 12, tzinfo=timezone.utc)


class FixtureAdapter:
    def __init__(self, *, index=0, version="v1", failure=None, enabled=True, attempts=1, body=b"fixture", cost=0, retrieve_hook=None, payload_extra=None):
        base = configured_tier1_adapters()[index]
        self.source = replace(base.source, enabled=enabled)
        self.subject_key = base.subject_key
        self.fetch_policy = FetchPolicy(
            timeout_seconds=1,
            max_response_bytes=learning_engine.MAX_RESPONSE_BYTES_PER_SOURCE,
            max_attempts=attempts,
            max_resolved_addresses=1,
        )
        self.version = version
        self.failure = failure
        self.body = body
        self.external_cost_amount = cost
        self.retrieve_hook = retrieve_hook
        self.payload_extra = payload_extra
        self.calls = 0

    def retrieve(self):
        self.calls += 1
        if self.retrieve_hook:
            self.retrieve_hook()
        payload = {"version": self.version, "protocol": self.subject_key.split(".", 1)[0]}
        if self.payload_extra is not None:
            payload["extra"] = self.payload_extra
        return AdapterResponse(
            FetchResult(None if self.failure else 200, self.body if not self.failure else None, self.failure, 1),
            payload,
        )

    def normalize(self, payload):
        if self.failure:
            raise AssertionError("failed transport must not be normalized")
        return dict(payload)

    def source_revision(self, normalized):
        return normalized["version"]


@pytest.fixture(autouse=True)
def clean_learning_state():
    def clean():
        with SessionLocal.begin() as db:
            db.execute(delete(models.LearningOpportunityCandidate))
            db.execute(delete(models.LearningRun))
            db.execute(delete(models.AgentEvidenceClaim))
            db.execute(delete(models.LearningSourceWatchState))
            db.execute(delete(models.ActionVerification).where(models.ActionVerification.action_run_id.in_(
                select(models.ActionRun.id).where(models.ActionRun.idempotency_key.like("signal-%"))
            )))
            db.execute(delete(models.ActionOutcome).where(models.ActionOutcome.action_run_id.in_(
                select(models.ActionRun.id).where(models.ActionRun.idempotency_key.like("signal-%"))
            )))
            db.execute(delete(models.ActionAttempt).where(models.ActionAttempt.action_run_id.in_(
                select(models.ActionRun.id).where(models.ActionRun.idempotency_key.like("signal-%"))
            )))
            db.execute(delete(models.ActionRun).where(models.ActionRun.idempotency_key.like("signal-%")))
            db.execute(delete(models.AgentUtilityCheckpoint))
            db.execute(delete(models.LiveUtilityVerification).where(models.LiveUtilityVerification.source_id.in_(learning_engine.WATCHED_SOURCE_IDS)))
            db.execute(delete(models.LiveUtilityObservation).where(models.LiveUtilityObservation.source_id.in_(learning_engine.WATCHED_SOURCE_IDS)))
            db.execute(delete(models.LiveUtilitySource).where(models.LiveUtilitySource.source_id.in_(learning_engine.WATCHED_SOURCE_IDS)))
    clean()
    with rate_limit._evidence_lock:
        rate_limit._evidence_events.clear()
    yield
    clean()


def _join():
    token = "learning-" + uuid.uuid4().hex
    response = client.post("/agents", json={"external_id": token, "name": token})
    assert response.status_code == 200
    data = response.json()
    return data["agent"]["id"], data["agent_key"]


def _evidence(key, *, idem=None, **overrides):
    payload = {
        "category": "missing_capability",
        "subject_key": "document-analysis",
        "description": "Need bounded document analysis",
    }
    payload.update(overrides)
    return client.post(
        "/learning/evidence",
        headers={"Authorization": f"Bearer {key}", "Idempotency-Key": idem or uuid.uuid4().hex},
        json=payload,
    )


def _mcp(key, arguments):
    params = {
        "name": "submit_learning_evidence",
        "arguments": arguments,
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {key}",
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "submit_learning_evidence",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
    )


def _agent(*, name=None, endpoint=None, acquisition_source=None):
    token = uuid.uuid4().hex
    with SessionLocal.begin() as db:
        row = models.Agent(
            external_id="signal-" + token,
            name=name or token,
            endpoint=endpoint,
            acquisition_source=acquisition_source,
            api_key_hash="signal-hash-" + token,
        )
        db.add(row)
        db.flush()
        return row.id


def _action(agent_id, query, failure, number):
    when = NOW + timedelta(seconds=number)
    with SessionLocal.begin() as db:
        db.add(models.ActionRun(
            action_id=str(uuid.uuid4()), requester_agent_id=agent_id,
            idempotency_key=f"signal-{number}-{uuid.uuid4().hex}", request_digest="sha256:" + uuid.uuid4().hex,
            requested_query=query, requested_candidate_identifier=None,
            authorize_external_contact=True, state="failed", failure_class=failure,
            created_at=when, started_at=when, completed_at=when, duration_ms=1,
            discovery_attempt_count=1, action_attempt_count=0, request_bytes=10,
            response_bytes=0, cost_amount=None, cost_currency=None,
        ))


def test_cycle_watches_only_selected_configured_sources_and_rejects_arbitrary_url():
    first, second = FixtureAdapter(index=0), FixtureAdapter(index=1)
    result = learning_engine.run_learning_cycle(NOW, {"trigger": "operator"}, adapters=(first, second))
    assert [row["source_id"] for row in result["source_results"]] == list(learning_engine.WATCHED_SOURCE_IDS)
    assert first.calls == second.calls == 1
    with pytest.raises(ValueError, match="configured Tier-1"):
        learning_engine.run_learning_cycle(NOW, {"trigger": "demand", "source_ids": ["https://attacker.invalid/"]}, adapters=(first,))


def test_fresh_source_is_skipped_then_stale_source_refreshes_without_duplicate_change():
    adapter = FixtureAdapter()
    first = learning_engine.run_learning_cycle(NOW, {"trigger": "operator"}, adapters=(adapter,))
    assert first["changed_sources"] == 1
    second = learning_engine.run_learning_cycle(NOW + timedelta(seconds=1), {"trigger": "scheduled"}, adapters=(adapter,))
    assert second["source_results"][0]["status"] == "not_due"
    third = learning_engine.run_learning_cycle(NOW + timedelta(days=8), {"trigger": "scheduled"}, adapters=(adapter,))
    assert third["source_results"][0]["status"] == "refreshed_unchanged"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 1
        watch = db.scalar(select(models.LearningSourceWatchState))
        assert watch.last_material_change_observation_id == watch.last_observation_id


def test_changed_source_creates_one_new_material_observation_across_restart():
    first = FixtureAdapter(version="v1")
    learning_engine.run_learning_cycle(NOW, {"trigger": "operator"}, adapters=(first,))
    changed = FixtureAdapter(version="v2")
    result = learning_engine.run_learning_cycle(NOW + timedelta(days=8), {"trigger": "scheduled"}, adapters=(changed,))
    assert result["changed_sources"] == 1
    replay = FixtureAdapter(version="v2")
    result = learning_engine.run_learning_cycle(NOW + timedelta(days=16), {"trigger": "scheduled"}, adapters=(replay,))
    assert result["unchanged_sources"] == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 2


def test_durable_failure_circuit_survives_service_reconstruction_and_cooldown():
    for offset in (0, 61, 122):
        result = learning_engine.run_learning_cycle(
            NOW + timedelta(seconds=offset), {"trigger": "operator"}, adapters=(FixtureAdapter(failure="timeout"),)
        )
        assert result["source_results"][0]["status"] == "fetch_failed"
    blocked = FixtureAdapter(failure="timeout")
    result = learning_engine.run_learning_cycle(NOW + timedelta(seconds=183), {"trigger": "operator"}, adapters=(blocked,))
    assert result["source_results"][0]["status"] == "circuit_open"
    assert blocked.calls == 0
    retry = FixtureAdapter(version="v1")
    result = learning_engine.run_learning_cycle(NOW + timedelta(seconds=1100), {"trigger": "operator"}, adapters=(retry,))
    assert result["source_results"][0]["status"] == "refreshed_changed"


@pytest.mark.parametrize(
    "adapter,reason",
    [
        (FixtureAdapter(enabled=False), "disabled"),
        (FixtureAdapter(cost=1), "paid_external_spend_disabled"),
        (FixtureAdapter(attempts=3), "outbound_attempt_budget"),
    ],
)
def test_disabled_paid_or_overbudget_source_performs_no_outbound_call(adapter, reason):
    result = learning_engine.run_learning_cycle(NOW, {"trigger": "operator"}, adapters=(adapter,))
    assert result["source_results"][0]["status"] in {"disabled", "budget_exhausted"}
    assert result["source_results"][0].get("reason") == reason or reason == "disabled"
    assert adapter.calls == 0
    assert result["paid_external_spend"] == {
        "permitted": False,
        "maximum": 0,
        "currency": None,
        "note": "No paid external variable spend is authorized; internal compute still has cost.",
    }


def test_durable_source_disable_performs_no_outbound_call():
    adapter = FixtureAdapter()
    with SessionLocal.begin() as db:
        LiveUtilityEngine((adapter,)).ensure_sources(db)
        row = db.scalar(select(models.LiveUtilitySource).where(models.LiveUtilitySource.source_id == adapter.source.source_id))
        row.enabled = False
        db.add(row)
    result = learning_engine.run_learning_cycle(NOW, {"trigger": "operator"}, adapters=(adapter,))
    assert result["source_results"][0]["status"] == "disabled"
    assert adapter.calls == 0


def test_oversized_source_response_is_not_persisted():
    adapter = FixtureAdapter(body=b"x" * (learning_engine.MAX_RESPONSE_BYTES_PER_SOURCE + 1))
    result = learning_engine.run_learning_cycle(NOW, {"trigger": "operator"}, adapters=(adapter,))
    assert result["source_results"][0]["status"] == "fetch_failed"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 0


def test_oversized_normalized_payload_is_not_persisted():
    adapter = FixtureAdapter(payload_extra="x" * learning_engine.MAX_STORED_NORMALIZED_BYTES)
    result = learning_engine.run_learning_cycle(NOW, {"trigger": "operator"}, adapters=(adapter,))
    assert result["source_results"][0]["status"] == "validation_failed"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 0


def test_concurrent_same_source_cycle_claims_once_without_duplicate_network_work():
    entered, release = threading.Event(), threading.Event()

    def hold():
        entered.set()
        assert release.wait(10)

    adapter = FixtureAdapter(retrieve_hook=hold)
    with SessionLocal.begin() as db:
        LiveUtilityEngine((adapter,)).ensure_sources(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(learning_engine.run_learning_cycle, NOW, {"trigger": "operator"}, adapters=(adapter,))
        assert entered.wait(10)
        second = pool.submit(learning_engine.run_learning_cycle, NOW, {"trigger": "operator"}, adapters=(adapter,))
        second_result = second.result(timeout=10)
        release.set()
        first_result = first.result(timeout=10)
    assert adapter.calls == 1
    assert {first_result["source_results"][0]["status"], second_result["source_results"][0]["status"]} == {"refreshed_changed", "source_busy"}
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.LiveUtilityObservation)) == 1


def test_evidence_requires_authentication_and_forbids_unbounded_or_credential_input():
    assert client.post("/learning/evidence", json={}).status_code == 401
    _, key = _join()
    assert _evidence(key, description="x" * 2001).status_code == 422
    assert _evidence(key, headers={"Authorization": "secret"}).status_code == 422
    credential_url = "https://" + ":".join(("user", "not-a-secret")) + "@example.com/path"
    assert _evidence(key, reference_url=credential_url).status_code == 422
    assert _evidence(key, arbitrary_method="POST").status_code == 422


def test_evidence_is_replay_safe_weak_and_never_contacts_submitted_url(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(safe_http, "fetch_bytes", lambda *a, **k: pytest.fail("submitted URL was contacted"))
    idem = "evidence-" + uuid.uuid4().hex
    first = _evidence(key, idem=idem, reference_url="https://127.0.0.1/private")
    assert first.status_code == 200
    assert first.json()["evidence_state"] == "unverified"
    assert first.json()["reference_url_contacted"] is False
    second = _evidence(key, idem=idem, reference_url="https://127.0.0.1/private")
    assert second.status_code == 200
    assert second.json()["claim_id"] == first.json()["claim_id"]
    assert second.json()["idempotent_replay"] is True
    conflict = _evidence(key, idem=idem, description="different")
    assert conflict.status_code == 409
    duplicate = _evidence(key, idem="different-" + uuid.uuid4().hex, reference_url="https://127.0.0.1/private")
    assert duplicate.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.AgentEvidenceClaim)) == 1


def test_distinct_agents_corroborate_but_same_agent_repetition_never_verifies():
    _, first_key = _join()
    _, second_key = _join()
    first = _evidence(first_key)
    assert first.json()["evidence_state"] == "unverified"
    duplicate = _evidence(first_key)
    assert duplicate.status_code == 409
    second = _evidence(second_key)
    assert second.status_code == 200
    assert second.json()["evidence_state"] == "corroborated"
    assert second.json()["corroborating_agent_count"] == 2
    with SessionLocal() as db:
        rows = list(db.scalars(select(models.AgentEvidenceClaim)))
        assert {row.state for row in rows} == {"corroborated"}
        assert {row.corroborating_agent_count for row in rows} == {2}
        assert all(row.state != "verified" for row in rows)


def test_duplicate_logical_agent_rows_cannot_self_corroborate():
    token = uuid.uuid4().hex
    endpoint = f"https://example.com/corroboration/{token}"
    first = _agent(name="Corroborator " + token, endpoint=endpoint)
    second = _agent(name="Corroborator " + token, endpoint=endpoint)
    payload = schemas.AgentEvidenceSubmission(
        category="missing_capability",
        subject_key="logical-corroboration-gap",
        description="Same logical source",
    )
    learning_engine.submit_agent_evidence(first, payload, "logical-a-" + token)
    learning_engine.submit_agent_evidence(second, payload, "logical-b-" + token)
    with SessionLocal() as db:
        rows = list(db.scalars(select(models.AgentEvidenceClaim).where(
            models.AgentEvidenceClaim.subject_key == "logical-corroboration-gap"
        )))
    assert len(rows) == 2
    assert {row.state for row in rows} == {"unverified"}
    assert {row.corroborating_agent_count for row in rows} == {1}


def test_rest_and_mcp_use_same_evidence_service_semantics():
    _, key = _join()
    rest = _evidence(key, idem="rest-" + uuid.uuid4().hex, subject_key="rest-gap")
    mcp = _mcp(key, {
        "category": "missing_capability", "subject_key": "mcp-gap",
        "description": "MCP gap", "idempotency_key": "mcp-" + uuid.uuid4().hex,
    })
    assert rest.status_code == 200
    assert mcp.status_code == 200
    structured = mcp.json()["result"]["structuredContent"]
    assert structured["evidence_state"] == "unverified"
    assert structured["trust_boundary"] == rest.json()["trust_boundary"]
    assert structured["reference_url_contacted"] is False


def test_per_agent_evidence_rate_limit_is_bounded(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(rate_limit, "_EVIDENCE_LIMIT", 2)
    for number in range(2):
        assert _evidence(key, subject_key=f"gap-{number}").status_code == 200
    assert _evidence(key, subject_key="gap-3").status_code == 429


def test_rest_replay_and_idempotency_conflict_count_toward_rate_limit(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(rate_limit, "_EVIDENCE_LIMIT", 3)
    idem = "replay-rate-" + uuid.uuid4().hex
    assert _evidence(key, idem=idem).status_code == 200
    replay = _evidence(key, idem=idem)
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    conflict = _evidence(key, idem=idem, description="changed payload")
    assert conflict.status_code == 409
    limited = _evidence(key, idem=idem)
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "evidence_rate_limited"


def test_duplicate_material_attempts_count_toward_rate_limit(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(rate_limit, "_EVIDENCE_LIMIT", 2)
    assert _evidence(key, idem="material-one-" + uuid.uuid4().hex).status_code == 200
    duplicate = _evidence(key, idem="material-two-" + uuid.uuid4().hex)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "duplicate_material_claim"
    limited = _evidence(key, idem="material-three-" + uuid.uuid4().hex)
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "evidence_rate_limited"


def test_mcp_replay_cannot_bypass_shared_evidence_rate_limit(monkeypatch):
    _, key = _join()
    monkeypatch.setattr(rate_limit, "_EVIDENCE_LIMIT", 1)
    arguments = {
        "category": "missing_capability",
        "subject_key": "mcp-rate-gap",
        "description": "MCP bounded replay",
        "idempotency_key": "mcp-rate-" + uuid.uuid4().hex,
    }
    assert _mcp(key, arguments).json()["result"]["isError"] is False
    replay = _mcp(key, arguments).json()["result"]
    assert replay["isError"] is True
    assert replay["structuredContent"] == {
        "code": "evidence_rate_limited", "status": 429
    }


def test_demand_semantics_exclude_operational_failures_and_count_distinct_agents():
    first, second, third = _agent(), _agent(), _agent()
    _action(first, "Research Reports", "no_result", 1)
    _action(first, "Research Reports", "no_result", 2)
    _action(second, "Research Reports", "capability_not_found", 3)
    _action(third, "Research Reports", "rate_limited", 4)
    _action(third, "Only Operational", "unavailable", 5)
    candidates = learning_engine.recompute_opportunity_candidates(NOW + timedelta(seconds=10))
    candidate = next(row for row in candidates if row["normalized_demand_key"] == "research-reports")
    assert all(row["normalized_demand_key"] != "only-operational" for row in candidates)
    assert candidate["normalized_demand_key"] == "research-reports"
    assert candidate["total_meaningful_signals"] == 3
    assert candidate["distinct_requester_count"] == 2
    assert candidate["repeat_requester_count"] == 1
    assert candidate["failure_class_breakdown"] == {"capability_not_found": 1, "no_result": 2}
    assert candidate["operational_failure_breakdown"] == {"rate_limited": 1}
    assert candidate["payment_potential"] == candidate["known_cost"] == candidate["margin_feasibility"] == "unknown"


def test_logical_identity_rows_count_as_one_requester_with_repeat_demand():
    token = uuid.uuid4().hex
    endpoint = f"https://example.com/logical/{token}"
    first = _agent(name="Logical " + token, endpoint=endpoint)
    second = _agent(name="Logical " + token, endpoint=endpoint)
    _action(first, "logical-gap", "no_result", 1)
    _action(second, "logical-gap", "capability_not_found", 2)
    candidate = next(
        row for row in learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1))
        if row["normalized_demand_key"] == "logical-gap"
    )
    assert candidate["total_meaningful_signals"] == 2
    assert candidate["distinct_requester_count"] == 1
    assert candidate["repeat_requester_count"] == 1
    assert candidate["evidence_state"] == "limited"


def test_operated_or_test_identity_cannot_inflate_independent_demand():
    external = _agent()
    operated = _agent(acquisition_source="aion-operated")
    _action(external, "mixed-market-gap", "no_result", 1)
    _action(operated, "mixed-market-gap", "no_result", 2)
    _action(operated, "internal-only-gap", "no_result", 3)
    candidates = learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1))
    candidate = next(row for row in candidates if row["normalized_demand_key"] == "mixed-market-gap")
    assert candidate["total_meaningful_signals"] == 1
    assert candidate["distinct_requester_count"] == 1
    assert candidate["repeat_requester_count"] == 0
    assert candidate["evidence_state"] == "limited"
    assert candidate["priority_score"] == 120
    assert all(row["normalized_demand_key"] != "internal-only-gap" for row in candidates)


def test_operated_marker_excludes_the_whole_resolved_logical_identity():
    token = uuid.uuid4().hex
    endpoint = f"https://example.com/operated/{token}"
    first = _agent(name="Operated Logical " + token, endpoint=endpoint)
    second = _agent(
        name="Operated Logical " + token,
        endpoint=endpoint,
        acquisition_source="internal-test",
    )
    _action(first, "operated-logical-gap", "no_result", 1)
    _action(second, "operated-logical-gap", "no_result", 2)
    candidates = learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1))
    assert all(row["normalized_demand_key"] != "operated-logical-gap" for row in candidates)


def test_distinct_external_logical_agents_increase_breadth():
    first, second = _agent(), _agent()
    _action(first, "independent-gap", "no_result", 1)
    _action(second, "independent-gap", "no_result", 2)
    candidate = next(
        row for row in learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1))
        if row["normalized_demand_key"] == "independent-gap"
    )
    assert candidate["distinct_requester_count"] == 2
    assert candidate["repeat_requester_count"] == 0
    assert candidate["evidence_state"] == "corroborated"
    assert candidate["priority_score"] == 240


def test_future_claim_observed_at_is_provenance_not_market_recency():
    agent_id = _agent()
    future = NOW + timedelta(days=365)
    payload = schemas.AgentEvidenceSubmission(
        category="missing_capability",
        subject_key="future-proof-gap",
        description="Untrusted future timestamp",
        observed_at=future,
    )
    result = learning_engine.submit_agent_evidence(
        agent_id, payload, "future-proof-" + uuid.uuid4().hex
    )
    received = NOW - timedelta(days=40)
    with SessionLocal.begin() as db:
        claim = db.scalar(select(models.AgentEvidenceClaim).where(
            models.AgentEvidenceClaim.claim_id == result["claim_id"]
        ))
        claim.submitted_at = received
    candidate = next(
        row for row in learning_engine.recompute_opportunity_candidates(NOW)
        if row["normalized_demand_key"] == "future-proof-gap"
    )
    assert candidate["last_seen_at"] == received.isoformat()
    assert candidate["priority_score"] == 100
    with SessionLocal() as db:
        claim = db.scalar(select(models.AgentEvidenceClaim).where(
            models.AgentEvidenceClaim.claim_id == result["claim_id"]
        ))
        assert learning_engine._utc(claim.observed_at) == future


def test_action_demand_recency_uses_durable_action_timestamp():
    agent = _agent()
    _action(agent, "action-time-gap", "no_result", 7)
    candidate = next(
        row for row in learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1))
        if row["normalized_demand_key"] == "action-time-gap"
    )
    assert candidate["last_seen_at"] == (NOW + timedelta(seconds=7)).isoformat()


def test_candidate_is_deterministic_bounded_and_updated_not_duplicated():
    agent = _agent()
    for number in range(25):
        _action(agent, "Spam-resistant gap", "no_result", number)
    first = next(row for row in learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1)) if row["normalized_demand_key"] == "spam-resistant-gap")
    second = next(row for row in learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=2)) if row["normalized_demand_key"] == "spam-resistant-gap")
    assert first["candidate_key"] == second["candidate_key"]
    assert len(second["supporting_evidence_references"]) == learning_engine.MAX_SUPPORTING_REFERENCES
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(models.LearningOpportunityCandidate).where(
                models.LearningOpportunityCandidate.candidate_key == first["candidate_key"]
            )
        ) == 1


def test_two_agent_breadth_outranks_one_spammy_identity():
    spammer, broad_one, broad_two = _agent(), _agent(), _agent()
    for number in range(10):
        _action(spammer, "spam-gap", "no_result", number)
    _action(broad_one, "broad-gap", "no_result", 20)
    _action(broad_two, "broad-gap", "no_result", 21)
    candidates = learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1))
    priorities = {row["normalized_demand_key"]: row["priority_score"] for row in candidates}
    assert priorities["broad-gap"] > priorities["spam-gap"]


def test_concurrent_candidate_recomputation_is_single_and_logically_consistent():
    agent = _agent()
    _action(agent, "concurrent-gap", "no_result", 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: learning_engine.recompute_opportunity_candidates(NOW + timedelta(minutes=1)), range(2)))
    first = next(row for row in results[0] if row["normalized_demand_key"] == "concurrent-gap")
    second = next(row for row in results[1] if row["normalized_demand_key"] == "concurrent-gap")
    assert first["candidate_key"] == second["candidate_key"]
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(models.LearningOpportunityCandidate).where(
                models.LearningOpportunityCandidate.candidate_key == first["candidate_key"]
            )
        ) == 1
