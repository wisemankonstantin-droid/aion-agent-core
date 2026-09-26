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
