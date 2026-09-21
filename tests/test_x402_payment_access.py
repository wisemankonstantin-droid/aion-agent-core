"""Payment access friction tests perform no real payment."""

from fastapi.testclient import TestClient

from app.main import app


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
