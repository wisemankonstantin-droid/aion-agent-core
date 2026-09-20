import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.services import learning_engine, official_data_execution as service
from app.services.safe_http import FetchResult


client = TestClient(app)


def _join(label: str) -> tuple[dict, str]:
    token = uuid.uuid4().hex
    response = client.post(
        "/agents",
        json={
            "external_id": f"official-data-{label}-{token}",
            "name": f"Official Data {label}",
            "protocol": "REST",
            "capabilities": [{"name": "public_data"}],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["agent"], body["agent_key"]


def _auth(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def _provider_payload(country_code: str = "US") -> bytes:
    document = [
        {
            "page": 1,
            "pages": 7,
            "per_page": 10,
            "total": 66,
            "sourceid": "2",
            "lastupdated": "2026-07-13",
        },
        [
            {
                "indicator": {"id": "SP.POP.TOTL", "value": "Population, total"},
                "country": {"id": country_code, "value": "United States"},
                "countryiso3code": "USA",
                "date": "2025",
                "value": 341_784_857,
                "unit": "",
                "obs_status": "",
                "decimal": 0,
            }
        ],
    ]
    return json.dumps(document, separators=(",", ":")).encode()


def _execute(key: str, *, idem: str, country_code: str = "US"):
    return client.post(
        "/commercial/executions/world-bank-population",
        headers={**_auth(key), "Idempotency-Key": idem},
        json={
            "capability": service.CAPABILITY,
            "country_code": country_code,
            "authorize_external_contact": True,
        },
    )


def test_real_supply_route_executes_verifies_persists_and_acknowledges(monkeypatch):
    agent, key = _join("success")
    calls = []

    def fetch(method, url, **kwargs):
        calls.append((method, url, kwargs["policy"]))
        return FetchResult(200, _provider_payload(), None, 1)

    monkeypatch.setattr(service, "_FETCH", fetch)
    idem = "population-" + uuid.uuid4().hex
    response = _execute(key, idem=idem, country_code="us")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["state"] == "completed"
    assert data["request"]["country_code"] == "US"
    assert data["intake_trace"] == {
        "raw_request": {
            "capability": service.CAPABILITY,
            "country_code": "US",
            "external_contact_authorized": True,
        },
        "aion_interpretation": {
            "method": "deterministic_fixed_capability_v1",
            "need": "latest_available_population_for_country",
            "country_code": "US",
        },
        "executable_requirement": {
            "provider_identifier": "world_bank_wdi",
            "indicator_id": "SP.POP.TOTL",
            "selection_rule": "latest_available_non_null_observation",
        },
        "conversation_intelligence": {
            "state": "not_applicable_structured_api_intake",
            "requester_statement_inferred": False,
        },
    }
    assert data["route"]["candidate_count"] == 1
    assert data["route"]["fallback"] == {
        "available": False,
        "reason": "no_fallback_provider_available",
    }
    assert data["route"]["provider"]["identifier"] == "world_bank_wdi"
    assert data["route"]["provider"]["commercial_rights"] == {
        "state": "known_compatible_with_attribution",
        "license": "CC-BY-4.0",
        "dataset_url": service.DATASET_URL,
        "attribution_required": True,
    }
    assert data["route"]["economics"] == {
        "currency": "USD",
        "provider_maximum_cost": "0",
        "customer_price": "0",
        "variable_cost_funded": True,
        "payment_required": False,
        "margin_policy": "not_applicable_zero_price_zero_variable_cost",
        "policy_evaluation_source": "package_6a_economic_kernel",
        "policy_eligible": True,
        "execution_eligible": True,
        "maximum_total_spend": "0",
        "verification_cost": "0",
        "payment_fee_allowance": "0",
        "expected_cost_per_verified_outcome": "0",
        "decision_reasons": ["known_zero_cost_no_payment_required"],
    }
    assert data["execution"]["provider_invoked"] is True
    assert data["execution"]["normalized_result"]["population"] == 341_784_857
    assert data["execution"]["normalized_result"]["freshness"] == {
        "semantics": "latest_available_not_current_year_claim",
        "observation_year": 2025,
        "provider_dataset_last_updated": "2026-07-13",
    }
    assert data["verification"] == {
        "state": "verified",
        "method": service.VERIFICATION_METHOD,
        "capability_verified": True,
    }
    assert data["outcome"]["machine_completion_state"] == "machine_verified_result_delivered"
    assert data["outcome"]["human_usefulness_confirmation_required"] is False
    assert data["outcome"]["optional_requester_feedback_recorded"] is False
    assert data["outcome"]["useful_outcome"] is False
    assert data["outcome"]["usefulness_evidence"] is None
    assert data["outcome"]["vuo_state"] == "optional_feedback_not_recorded"
    assert len(calls) == 1
    assert calls[0][0] == "GET"
    assert calls[0][1].startswith(service.PROVIDER_BASE + "/country/US/")
    assert calls[0][1].endswith("?format=json&mrv=1&per_page=1")
    assert calls[0][2].max_attempts == 1
    assert calls[0][2].max_response_bytes == service.MAX_RESPONSE_BYTES

    replay = _execute(key, idem=idem, country_code="US")
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["execution_id"] == data["execution_id"]
    assert len(calls) == 1

    status = client.get(
        f"/commercial/executions/{data['execution_id']}", headers=_auth(key)
    )
    assert status.status_code == 200
    assert status.json()["execution"]["response_digest"].startswith("sha256:")

    acknowledgement = client.post(
        f"/commercial/executions/{data['execution_id']}/acknowledge",
        headers=_auth(key),
        json={
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_population_result_was_useful",
        },
    )
    assert acknowledgement.status_code == 200, acknowledgement.text
    acknowledged = acknowledgement.json()
    assert acknowledged["outcome"] == {
        "machine_completion_state": "machine_verified_result_delivered",
        "human_usefulness_confirmation_required": False,
        "optional_requester_feedback_recorded": True,
        "optional_requester_feedback": "requester_confirms_population_result_was_useful",
        "legacy_vuo_state": "requester_confirmed_verified_useful_outcome",
        "useful_outcome": True,
        "usefulness_evidence": "requester_confirms_population_result_was_useful",
        "vuo_state": "requester_confirmed_verified_useful_outcome",
    }
    assert acknowledged["requester_history"]["verified_execution_count"] >= 1
    assert acknowledged["requester_history"]["confirmed_useful_outcome_count"] >= 1
    assert acknowledged["truth_boundaries"]["zero_price_execution_is_not_revenue_or_settlement"] is True
    assert acknowledged["truth_boundaries"]["machine_verified_completion_does_not_require_human_acknowledgement"] is True
    assert acknowledged["truth_boundaries"]["zero_price_execution_is_not_paid_vuo"] is True
    assert acknowledged["truth_boundaries"]["requester_confirmation_is_not_independent_third_party_verification"] is True
    with SessionLocal() as db:
        learning = learning_engine.commercial_execution_evidence_summary(db)
    assert learning["verified_execution_count"] >= 1
    assert learning["usefulness_confirmed_count"] >= 1
    assert learning["provider_failure_count"] == 0
    assert learning["routing_effect"] == "bounded_evidence_only_no_autonomous_policy_change"

    acknowledgement_replay = client.post(
        f"/commercial/executions/{data['execution_id']}/acknowledge",
        headers=_auth(key),
        json={
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_population_result_was_useful",
        },
    )
    assert acknowledgement_replay.status_code == 200
    assert acknowledgement_replay.json()["idempotent_replay"] is True
    assert acknowledgement_replay.json()["requester_history"]["confirmed_useful_outcome_count"] >= 1
    assert agent["id"] == data["requester_history"].get("agent_id", agent["id"])


def test_validation_authorization_and_idempotency_fail_before_extra_contact(monkeypatch):
    _, key = _join("validation")
    calls = []
    monkeypatch.setattr(
        service,
        "_FETCH",
        lambda *args, **kwargs: calls.append(1)
        or FetchResult(200, _provider_payload(), None, 1),
    )

    invalid = _execute(key, idem="invalid-country", country_code="USA")
    assert invalid.status_code == 422
    assert calls == []

    unauthorized = client.post(
        "/commercial/executions/world-bank-population",
        headers={**_auth(key), "Idempotency-Key": "not-authorized"},
        json={
            "capability": service.CAPABILITY,
            "country_code": "US",
            "authorize_external_contact": False,
        },
    )
    assert unauthorized.status_code == 422
    assert unauthorized.json()["detail"]["code"] == "external_contact_not_authorized"
    assert calls == []

    idem = "conflict-" + uuid.uuid4().hex
    assert _execute(key, idem=idem, country_code="US").status_code == 200
    conflict = _execute(key, idem=idem, country_code="CA")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    assert len(calls) == 1


def test_economic_policy_denial_prevents_provider_invocation(monkeypatch):
    _, key = _join("economic-denial")
    calls = []
    monkeypatch.setattr(
        service,
        "evaluate_plan",
        lambda *args, **kwargs: {
            "policy_eligible": False,
            "execution_eligible": False,
            "decision_reasons": ["free_variable_cost_execution_prohibited"],
        },
    )
    monkeypatch.setattr(service, "_FETCH", lambda *args, **kwargs: calls.append(1))
    response = _execute(
        key, idem="economic-denial-" + uuid.uuid4().hex, country_code="US"
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "economic_policy_denied",
        "message": "Economic policy denied execution: free_variable_cost_execution_prohibited",
    }
    assert calls == []


def test_provider_failure_is_durable_non_vuo_and_requester_scoped(monkeypatch):
    _, key = _join("failure")
    _, other_key = _join("other")
    monkeypatch.setattr(
        service,
        "_FETCH",
        lambda *args, **kwargs: FetchResult(503, None, "http_503", 1),
    )
    response = _execute(key, idem="provider-failure-" + uuid.uuid4().hex)
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "failed"
    assert data["failure_class"] == "provider_http_failure"
    assert data["verification"]["capability_verified"] is False
    assert data["outcome"]["machine_completion_state"] == "not_completed"
    assert data["outcome"]["legacy_vuo_state"] == "not_established"
    assert data["outcome"]["vuo_state"] == "not_established"

    forbidden = client.get(
        f"/commercial/executions/{data['execution_id']}", headers=_auth(other_key)
    )
    assert forbidden.status_code == 404

    acknowledgement = client.post(
        f"/commercial/executions/{data['execution_id']}/acknowledge",
        headers=_auth(key),
        json={
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_population_result_was_useful",
        },
    )
    assert acknowledgement.status_code == 409
    assert acknowledgement.json()["detail"]["code"] == "verified_result_required"


@pytest.mark.parametrize(
    "transport_error,expected",
    [
        ("TimeoutError:timed out", "timeout"),
        ("SSLCertVerificationError:certificate verify failed", "tls_failure"),
        ("url_validation_error:gaierror", "dns_failure"),
        ("connection_failed", "connectivity_failure"),
        ("redirect_rejected", "https_policy_failure"),
    ],
)
def test_transport_failures_are_distinguished_and_have_no_fallback(
    monkeypatch, transport_error, expected
):
    _, key = _join("transport-" + expected)
    monkeypatch.setattr(
        service,
        "_FETCH",
        lambda *args, **kwargs: FetchResult(None, None, transport_error, 1),
    )
    response = _execute(key, idem="transport-" + expected + "-" + uuid.uuid4().hex)
    assert response.status_code == 200
    data = response.json()
    assert data["failure_class"] == expected
    assert data["route"]["fallback"]["available"] is False


def test_malformed_or_mismatched_provider_payload_fails_verification(monkeypatch):
    _, key = _join("malformed")
    wrong = _provider_payload("CA")
    monkeypatch.setattr(
        service,
        "_FETCH",
        lambda *args, **kwargs: FetchResult(200, wrong, None, 1),
    )
    response = _execute(key, idem="mismatch-" + uuid.uuid4().hex, country_code="US")
    assert response.status_code == 200
    data = response.json()
    assert data["state"] == "failed"
    assert data["failure_class"] == "provider_result_verification_failed"
    assert data["execution"]["response_digest"].startswith("sha256:")
    assert data["verification"]["state"] == "failed"
