"""Package 5E operator-control tests; no real outreach is performed."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import models
from app.db import SessionLocal
from app.main import app
from app.security import hash_key
from app.services import ambassador, ambassador_operator, safe_http
from app.services.external_registry import DiscoveryResult


client = TestClient(app)
CONTROL_TOKEN = "package5e-control-" + "x" * 48


def _headers(key: str | None = None) -> dict[str, str]:
    result = {"Authorization": "Bearer " + CONTROL_TOKEN}
    if key is not None:
        result["Idempotency-Key"] = key
    return result


def _candidate(**overrides):
    token = uuid.uuid4().hex
    result = {
        "source": "global_a2a_registry",
        "identifier": "package5e-agent-" + token,
        "url": f"https://cards.example/{token}/agent-card.json",
        "interaction_url": f"https://agents.example/{token}/a2a",
        "manifest_reachable": True,
        "declared_a2a_v1_jsonrpc": True,
        "interaction_url_validated": True,
        "authentication_requirement": "none",
        "payment_required": False,
    }
    result.update(overrides)
    return result


def _campaign_and_target(*, campaign_state="draft", candidate=None, maximum_contacts=1):
    with SessionLocal() as db:
        campaign_id = ambassador.create_campaign(
            db,
            name="Package 5E pilot",
            purpose="One explicitly selected bounded target",
            maximum_targets=2,
            maximum_contacts=maximum_contacts,
        )["campaign_id"]
        campaign = db.scalar(
            select(models.AmbassadorCampaign).where(
                models.AmbassadorCampaign.campaign_id == campaign_id
            )
        )
        target, outcome = ambassador._insert_candidate(db, campaign, candidate or _candidate())
        assert outcome == "created"
        db.commit()
        if campaign_state != "draft":
            ambassador.set_campaign_state(db, campaign_id, campaign_state)
        return campaign_id, target.target_id


@pytest.fixture(autouse=True)
def package5e_isolation(monkeypatch):
    monkeypatch.setenv("AION_AMBASSADOR_CONTROL_TOKEN", CONTROL_TOKEN)
    monkeypatch.delenv("AION_AMBASSADOR_OUTBOUND_ENABLED", raising=False)
    monkeypatch.delenv("AION_AMBASSADOR_OPERATOR", raising=False)
    monkeypatch.setenv("AION_PUBLIC_URL", "https://aion.example")
    monkeypatch.setattr(ambassador, "_canonical_public_url", lambda value: str(value).rstrip("/"))
    with SessionLocal() as db:
        db.execute(delete(models.AmbassadorOperatorAction))
        db.execute(delete(models.DistributionJoinAttribution))
        db.execute(delete(models.DistributionToken))
        db.execute(delete(models.AmbassadorContactAttempt))
        db.execute(delete(models.AmbassadorTarget))
        db.execute(delete(models.AmbassadorCampaign))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(models.AmbassadorOperatorAction))
        db.execute(delete(models.DistributionJoinAttribution))
        db.execute(delete(models.DistributionToken))
        db.execute(delete(models.AmbassadorContactAttempt))
        db.execute(delete(models.AmbassadorTarget))
        db.execute(delete(models.AmbassadorCampaign))
        db.commit()


def test_operator_auth_fails_closed_and_agent_key_cannot_substitute(monkeypatch):
    monkeypatch.delenv("AION_AMBASSADOR_CONTROL_TOKEN")
    assert client.get("/ops/ambassador/campaigns/missing").status_code == 503

    monkeypatch.setenv("AION_AMBASSADOR_CONTROL_TOKEN", CONTROL_TOKEN)
    assert client.get("/ops/ambassador/campaigns/missing").status_code == 401
    assert client.get(
        "/ops/ambassador/campaigns/missing",
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 401
    assert client.get(
        "/ops/ambassador/campaigns/missing",
        headers={"Authorization": "Bearer " + "z" * 600},
    ).status_code == 401

    with SessionLocal() as db:
        raw_agent_key = "aion_agent_key_" + uuid.uuid4().hex
        db.add(models.Agent(
            external_id="package5e-agent-key-" + uuid.uuid4().hex,
            name="Agent key is not operator auth",
            api_key_hash=hash_key(raw_agent_key),
        ))
        db.commit()
    assert client.get(
        "/ops/ambassador/campaigns/missing",
        headers={"Authorization": "Bearer " + raw_agent_key},
    ).status_code == 401


def test_operator_routes_are_hidden_and_bounded_campaign_creation_is_idempotent():
    paths = client.get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/ops/ambassador") for path in paths)
    payload = {
        "name": "Bounded pilot",
        "purpose": "HQ-selected targets only",
        "maximum_targets": 2,
        "maximum_contacts": 1,
    }
    first = client.post(
        "/ops/ambassador/campaigns", headers=_headers("create-one"), json=payload
    )
    assert first.status_code == 200
    assert first.json()["result"]["bounds"]["hard_global_target_cap"] == 30
    replay = client.post(
        "/ops/ambassador/campaigns", headers=_headers("create-one"), json=payload
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.AmbassadorCampaign)) == 1
        assert db.scalar(select(func.count()).select_from(models.AmbassadorOperatorAction)) == 1


def test_status_is_read_only_and_state_and_suppression_are_narrow_audited_mutations():
    campaign_id, target_id = _campaign_and_target()
    status = client.get(
        f"/ops/ambassador/campaigns/{campaign_id}", headers=_headers()
    )
    assert status.status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.AmbassadorOperatorAction)) == 0

    ready = client.post(
        f"/ops/ambassador/campaigns/{campaign_id}/state",
        headers=_headers("state-ready"),
        json={"state": "ready"},
    )
    suppressed = client.post(
        f"/ops/ambassador/targets/{target_id}/suppress",
        headers=_headers("suppress-one"),
        json={"reason": "HQ selected suppression"},
    )
    assert ready.status_code == suppressed.status_code == 200
    assert ready.json()["result"]["state"] == "ready"
    assert suppressed.json()["result"]["suppressed"] is True
    with SessionLocal() as db:
        rows = list(db.scalars(select(models.AmbassadorOperatorAction)))
        assert {row.operation_kind for row in rows} == {
            "set_campaign_state", "suppress_target"
        }
        assert all(row.result_class == "succeeded" for row in rows)


def test_operator_idempotency_conflict_does_not_repeat_mutation():
    first = client.post(
        "/ops/ambassador/campaigns",
        headers=_headers("same-key"),
        json={
            "name": "First",
            "purpose": "Original bounded request",
            "maximum_targets": 1,
            "maximum_contacts": 0,
        },
    )
    conflict = client.post(
        "/ops/ambassador/campaigns",
        headers=_headers("same-key"),
        json={
            "name": "Changed",
            "purpose": "Different request",
            "maximum_targets": 1,
            "maximum_contacts": 0,
        },
    )
    assert first.status_code == 200
    assert conflict.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.AmbassadorCampaign)) == 1


def test_create_scout_and_qualify_never_contact_target(monkeypatch):
    campaign_id, target_id = _campaign_and_target()
    monkeypatch.setattr(
        ambassador,
        "discover_external_agents_with_status",
        lambda query, limit: DiscoveryResult([], "success", None, {"candidate_limit": 5}),
    )
    monkeypatch.setattr(
        safe_http,
        "fetch_json",
        lambda *args, **kwargs: pytest.fail("target contact attempted"),
    )
    scout = client.post(
        f"/ops/ambassador/campaigns/{campaign_id}/scout",
        headers=_headers("scout-one"),
        json={"query": "research"},
    )
    qualify = client.post(
        f"/ops/ambassador/targets/{target_id}/qualify",
        headers=_headers("qualify-one"),
    )
    assert scout.status_code == qualify.status_code == 200
    assert scout.json()["result"]["outbound_contact_performed"] is False
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.AmbassadorContactAttempt)) == 0
        assert db.scalar(select(func.count()).select_from(models.DistributionToken)) == 0


@pytest.mark.parametrize(
    "outbound,operator",
    [(None, None), ("1", None), (None, "1")],
)
def test_contact_requires_both_environment_gates_before_token_issue(monkeypatch, outbound, operator):
    _, target_id = _campaign_and_target(campaign_state="ready")
    if outbound:
        monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", outbound)
    if operator:
        monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", operator)
    response = client.post(
        f"/ops/ambassador/targets/{target_id}/contact",
        headers=_headers("gates-" + str(outbound) + str(operator)),
        json={"confirm": "SEND"},
    )
    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.DistributionToken)) == 0
        assert db.scalar(select(func.count()).select_from(models.AmbassadorContactAttempt)) == 0


def test_contact_requires_exact_send_confirmation_and_one_server_selected_target():
    _, target_id = _campaign_and_target(campaign_state="ready")
    for body in (
        {"confirm": "send"},
        {"confirm": "SEND", "interaction_url": "https://attacker.example/a2a"},
        {"confirm": "SEND", "target_ids": [target_id]},
    ):
        response = client.post(
            f"/ops/ambassador/targets/{target_id}/contact",
            headers=_headers(uuid.uuid4().hex),
            json=body,
        )
        assert response.status_code == 422


@pytest.mark.parametrize("state", ["draft", "paused", "closed"])
def test_contact_rejects_non_ready_campaign_before_token(monkeypatch, state):
    _, target_id = _campaign_and_target(campaign_state=state)
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    response = client.post(
        f"/ops/ambassador/targets/{target_id}/contact",
        headers=_headers("state-" + state),
        json={"confirm": "SEND"},
    )
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.DistributionToken)) == 0


def test_contact_rejects_unqualified_suppressed_and_zero_limit_targets(monkeypatch):
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    cases = [
        (_candidate(authentication_requirement="bearer"), 1, False),
        (_candidate(), 1, True),
        (_candidate(), 0, False),
    ]
    for candidate, maximum_contacts, suppress in cases:
        _, target_id = _campaign_and_target(
            campaign_state="ready", candidate=candidate, maximum_contacts=maximum_contacts
        )
        if suppress:
            with SessionLocal() as db:
                ambassador.suppress_target(db, target_id=target_id, reason="HQ suppression")
        response = client.post(
            f"/ops/ambassador/targets/{target_id}/contact",
            headers=_headers(uuid.uuid4().hex),
            json={"confirm": "SEND"},
        )
        assert response.status_code == 409


def test_operator_contact_sends_exact_bound_message_without_secret_leak(monkeypatch):
    campaign_id, target_id = _campaign_and_target(campaign_state="ready")
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    calls = []

    def respond(method, url, *, payload, headers, policy):
        calls.append((method, url, payload, policy.max_attempts))
        message = json.loads(payload["params"]["message"]["parts"][0]["text"])
        raw_token = message["join"]["distribution_token"]
        with SessionLocal() as db:
            target = db.scalar(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id))
            token = db.scalar(select(models.DistributionToken).where(models.DistributionToken.target_id == target.id))
            assert target.prepared_message_digest == ambassador._digest_json(message)
            assert token.token_digest == ambassador._token_digest(raw_token)
            assert token.campaign_id == target.campaign_id
        return safe_http.FetchResult(200, b'{}', None, 1), {
            "jsonrpc": "2.0", "id": payload["id"], "result": {"accepted": True}
        }

    monkeypatch.setattr(safe_http, "fetch_json", respond)
    response = client.post(
        f"/ops/ambassador/targets/{target_id}/contact",
        headers=_headers("contact-one"),
        json={"confirm": "SEND"},
    )
    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body)
    assert len(calls) == 1 and calls[0][0] == "POST" and calls[0][3] == 1
    assert body["result"]["raw_distribution_token_returned"] is False
    assert body["result"]["raw_prepared_message_returned"] is False
    assert "aion_dist_" not in serialized
    assert CONTROL_TOKEN not in serialized
    assert "bounded_machine_utility_invitation" not in serialized
    with SessionLocal() as db:
        audit = db.scalar(select(models.AmbassadorOperatorAction))
        assert audit.campaign_id is not None and audit.target_id is not None
        persisted = " ".join(str(value) for value in vars(audit).values())
        assert CONTROL_TOKEN not in persisted and "aion_dist_" not in persisted
        assert audit.result_class == "succeeded"
        assert ambassador.campaign_status(db, campaign_id)["truth_boundary"].startswith("Coordinated")

    replay = client.post(
        f"/ops/ambassador/targets/{target_id}/contact",
        headers=_headers("contact-one"),
        json={"confirm": "SEND"},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["result"]["send_performed"] is False
    assert len(calls) == 1
    changed_key = client.post(
        f"/ops/ambassador/targets/{target_id}/contact",
        headers=_headers("contact-two"),
        json={"confirm": "SEND"},
    )
    assert changed_key.status_code == 409
    assert len(calls) == 1


@pytest.mark.parametrize(
    "fetch_result,response,result_class",
    [
        (safe_http.FetchResult(402, b"{}", "http_402", 1), {}, "payment_required"),
        (safe_http.FetchResult(None, None, "timeout", 1), None, "ambiguous"),
    ],
)
def test_contact_never_pays_or_retries_ambiguous_or_x402(monkeypatch, fetch_result, response, result_class):
    _, target_id = _campaign_and_target(campaign_state="ready")
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    calls = []
    monkeypatch.setattr(
        safe_http,
        "fetch_json",
        lambda *args, **kwargs: (calls.append((args, kwargs)) or (fetch_result, response)),
    )
    result = client.post(
        f"/ops/ambassador/targets/{target_id}/contact",
        headers=_headers(uuid.uuid4().hex),
        json={"confirm": "SEND"},
    )
    assert result.status_code == 200
    assert result.json()["result"]["result_class"] == result_class
    assert result.json()["result"]["automatic_retry"] is False
    assert len(calls) == 1


def test_operator_body_limit_rejects_oversized_request():
    response = client.post(
        "/ops/ambassador/campaigns",
        headers={**_headers("oversized"), "Content-Type": "application/json"},
        content=b'{"name":"' + b"x" * (64 * 1024) + b'"}',
    )
    assert response.status_code == 413


@pytest.mark.skipif(
    os.getenv("AION_POSTGRES_GATE") != "1",
    reason="requires disposable PostgreSQL gate",
)
def test_concurrent_same_target_operator_contact_produces_one_post(monkeypatch):
    _, target_id = _campaign_and_target(campaign_state="ready")
    monkeypatch.setenv("AION_AMBASSADOR_OUTBOUND_ENABLED", "1")
    monkeypatch.setenv("AION_AMBASSADOR_OPERATOR", "1")
    calls = []

    def respond(*args, **kwargs):
        calls.append(1)
        payload = kwargs["payload"]
        return safe_http.FetchResult(200, b"{}", None, 1), {
            "jsonrpc": "2.0", "id": payload["id"], "result": {"accepted": True}
        }

    monkeypatch.setattr(safe_http, "fetch_json", respond)

    def send(index):
        return client.post(
            f"/ops/ambassador/targets/{target_id}/contact",
            headers=_headers("concurrent-" + str(index)),
            json={"confirm": "SEND"},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(send, range(2)))
    assert statuses.count(200) == 1
    assert statuses.count(409) == 1
    assert len(calls) == 1
