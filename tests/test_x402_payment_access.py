"""Payment access friction tests perform no real payment."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.main import app
from app.services import commercial_payment_routes


client = TestClient(app)
_PURCHASE_REQUEST = {"need": "public route intelligence"}


def test_purchase_surface_does_not_require_aion_membership_or_agent_key():
    response = client.post(
        "/commercial/route-intelligence/purchase",
        json=_PURCHASE_REQUEST,
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "commercial_payment_not_activated"
    assert body["aion_membership_required"] is False
    assert response.headers["cache-control"] == "private, no-store"


def test_unsigned_or_signed_payment_attempt_never_turns_missing_aion_auth_into_401():
    response = client.post(
        "/commercial/route-intelligence/purchase",
        json=_PURCHASE_REQUEST,
        headers={"PAYMENT-SIGNATURE": "ZXhhbXBsZS1zaWduZWQtcGF5bG9hZA=="},
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "x402_exact_upfront_not_activated"
    assert body["aion_membership_required"] is False
    assert body["result_released"] is False


def test_openapi_exposes_agentcash_x402_discovery_contract(monkeypatch):
    monkeypatch.setattr(
        commercial_payment_routes,
        "configured_route_intelligence_plan",
        lambda: SimpleNamespace(customer_price="0.01", currency="USDC"),
    )
    monkeypatch.setattr(
        commercial_payment_routes,
        "exact_upfront_readiness",
        lambda: {"launch_ready": True},
    )
    app.openapi_schema = None
    try:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert "Before external spend" in schema["info"]["x-guidance"]

        operation = schema["paths"][
            "/commercial/route-intelligence/x402/purchase"
        ]["post"]
        body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        assert body_schema["required"] == ["need"]
        assert body_schema["properties"]["need"]["minLength"] == 1
        assert body_schema["properties"]["need"]["maxLength"] == 128
        assert operation["responses"]["402"]["description"] == "Payment Required"
        assert operation["x-payment-info"] == {
            "price": {
                "mode": "fixed",
                "currency": "USDC",
                "amount": "0.01",
            },
            "protocols": [{"x402": {}}],
        }
    finally:
        app.openapi_schema = None



def test_x402_get_compat_requires_need():
    response = client.get("/commercial/route-intelligence/x402/purchase")
    assert response.status_code == 422


def test_x402_get_compat_builds_same_purchase_payload_and_returns_402(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        commercial_payment_routes,
        "exact_upfront_readiness",
        lambda: {"launch_ready": True, "blocking_reasons": []},
    )

    def fake_prepare(db, payload, *, payment_method):
        captured["payload"] = payload
        captured["payment_method"] = payment_method
        return object()

    def fake_required(row, *, x402_resource_url):
        captured["resource_url"] = x402_resource_url
        return {
            "state": "awaiting_payment",
            "payment_required": {
                "x402Version": 2,
                "resource": {"url": x402_resource_url},
                "accepts": [],
            },
        }

    monkeypatch.setattr(
        commercial_payment_routes,
        "prepare_route_intelligence",
        fake_prepare,
    )
    monkeypatch.setattr(
        commercial_payment_routes,
        "payment_required_response_data",
        fake_required,
    )

    response = client.get(
        "/commercial/route-intelligence/x402/purchase",
        params={
            "need": "choose a paid research API before external spend",
            "candidate_identifier": "example.provider",
        },
    )

    assert response.status_code == 402
    assert captured["payload"] == {
        "need": "choose a paid research API before external spend",
        "candidate_identifier": "example.provider",
    }
    assert captured["payment_method"] == commercial_payment_routes.X402_PAYMENT_METHOD
    assert captured["resource_url"].endswith(
        "/commercial/route-intelligence/x402/purchase"
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert "payment-required" in response.headers


def test_x402_get_compat_signed_retry_uses_existing_settlement_path(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        commercial_payment_routes,
        "exact_upfront_readiness",
        lambda: {"launch_ready": True, "blocking_reasons": []},
    )

    def fake_settle(db, payload, payment_signature):
        captured["payload"] = payload
        captured["payment_signature"] = payment_signature
        return {
            "state": "entitled",
            "payment": {"method": "x402_exact_upfront"},
            "result": {"route_version": "commercial_router_v1"},
        }

    monkeypatch.setattr(
        commercial_payment_routes,
        "settle_and_release",
        fake_settle,
    )
    monkeypatch.setattr(
        commercial_payment_routes,
        "_payment_response_header",
        lambda data: "test-payment-response",
    )

    response = client.get(
        "/commercial/route-intelligence/x402/purchase",
        params={"need": "verify a paid provider before external spend"},
        headers={"PAYMENT-SIGNATURE": "signed-payment-payload"},
    )

    assert response.status_code == 200
    assert captured["payload"] == {
        "need": "verify a paid provider before external spend"
    }
    assert captured["payment_signature"] == "signed-payment-payload"
    assert response.headers["payment-response"] == "test-payment-response"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["state"] == "entitled"
