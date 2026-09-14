"""Buyer-facing x402 offer tests remain fixture-only and never move money."""

import base64
from datetime import datetime, timezone
import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app import models
from app.db import SessionLocal
from app.main import MCP_TOOLS, app
from app.security import hash_key
from app.services import economic_kernel, x402_payment_offer
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
)
from app.services.x402_payment_offer import (
    ASSET_DECIMALS_ENV,
    ASSET_ENV,
    ASSET_NAME_ENV,
    ASSET_TRANSFER_METHOD_ENV,
    ASSET_VERSION_ENV,
    AUTH_CAPTURE_ESCROW_ENV,
    CAPTURE_AUTHORIZER_ENV,
    CAPTURE_WINDOW_SECONDS_ENV,
    FEE_RECIPIENT_ENV,
    MAX_FEE_BPS_ENV,
    MAX_TIMEOUT_SECONDS_ENV,
    MIN_FEE_BPS_ENV,
    NETWORK_ENV,
    OFFER_ENABLE_ENV,
    PAY_TO_ENV,
    RECEIVER_AUTHORIZER_ENV,
    REFUND_WINDOW_SECONDS_ENV,
    build_payment_required,
    encode_payment_required,
    payment_offer_readiness,
)


client = TestClient(app)

_X402_ENVS = (
    OFFER_ENABLE_ENV,
    NETWORK_ENV,
    ASSET_ENV,
    ASSET_NAME_ENV,
    ASSET_VERSION_ENV,
    ASSET_DECIMALS_ENV,
    PAY_TO_ENV,
    AUTH_CAPTURE_ESCROW_ENV,
    CAPTURE_AUTHORIZER_ENV,
    RECEIVER_AUTHORIZER_ENV,
    FEE_RECIPIENT_ENV,
    MIN_FEE_BPS_ENV,
    MAX_FEE_BPS_ENV,
    MAX_TIMEOUT_SECONDS_ENV,
    CAPTURE_WINDOW_SECONDS_ENV,
    REFUND_WINDOW_SECONDS_ENV,
    ASSET_TRANSFER_METHOD_ENV,
)


@pytest.fixture(autouse=True)
def reset_payment_offer(monkeypatch):
    for name in (QUOTE_ENABLE_ENV, CURRENCY_ENV, PRICE_ENV, MAX_PAYMENT_FEE_ENV, *_X402_ENVS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AION_PUBLIC_URL", "https://aion.example")
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)
    monkeypatch.setattr(x402_payment_offer, "LIVE_PAYMENT_HANDLER_IMPLEMENTED", False)
    yield
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)


def _agent():
    token = uuid.uuid4().hex
    key = "aion_x402_buyer_" + token
    with SessionLocal() as db:
        row = models.Agent(
            external_id="x402-buyer-" + token,
            name="x402 buyer " + token,
            protocol="REST",
            api_key_hash=hash_key(key),
        )
        db.add(row)
        db.commit()
    return key


def _configure_quote(monkeypatch, *, price="1.25", fee="0.10"):
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(CURRENCY_ENV, "USDC")
    monkeypatch.setenv(PRICE_ENV, price)
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, fee)
    assert register_paid_route_intelligence_profile() is True


def _configure_offer(monkeypatch, *, price="1.25", fee="0.10"):
    _configure_quote(monkeypatch, price=price, fee=fee)
    monkeypatch.setenv(OFFER_ENABLE_ENV, "1")
    monkeypatch.setenv(NETWORK_ENV, "eip155:8453")
    monkeypatch.setenv(ASSET_ENV, "0x" + "1" * 40)
    monkeypatch.setenv(ASSET_NAME_ENV, "USDC")
    monkeypatch.setenv(ASSET_VERSION_ENV, "2")
    monkeypatch.setenv(ASSET_DECIMALS_ENV, "6")
    monkeypatch.setenv(PAY_TO_ENV, "0x" + "2" * 40)
    monkeypatch.setenv(AUTH_CAPTURE_ESCROW_ENV, "0x" + "3" * 40)
    monkeypatch.setenv(CAPTURE_AUTHORIZER_ENV, "0x" + "4" * 40)
    monkeypatch.setenv(RECEIVER_AUTHORIZER_ENV, "0x" + "5" * 40)
    monkeypatch.setenv(FEE_RECIPIENT_ENV, "0x" + "6" * 40)
    monkeypatch.setenv(MIN_FEE_BPS_ENV, "0")
    monkeypatch.setenv(MAX_FEE_BPS_ENV, "100")
    monkeypatch.setenv(MAX_TIMEOUT_SECONDS_ENV, "60")
    monkeypatch.setenv(CAPTURE_WINDOW_SECONDS_ENV, "300")
    monkeypatch.setenv(REFUND_WINDOW_SECONDS_ENV, "900")
    monkeypatch.setenv(ASSET_TRANSFER_METHOD_ENV, "eip3009")


def test_mcp_economic_preflight_metadata_includes_paid_route_intelligence():
    tool = next(item for item in MCP_TOOLS if item["name"] == "economic_preflight")
    values = tool["inputSchema"]["properties"]["product_sku"]["enum"]
    assert ROUTE_INTELLIGENCE_SKU in values
    assert len(values) == len(set(values))


def test_payment_readiness_is_fail_closed_by_default():
    readiness = payment_offer_readiness()
    assert readiness["quote_configured"] is False
    assert readiness["payment_offer_configured"] is False
    assert readiness["live_payment_handler_implemented"] is False
    assert readiness["real_money_execution_enabled"] is False
    assert readiness["launch_ready"] is False
    assert readiness["payment_signature_accepted_now"] is False
    assert readiness["truth_boundaries"]["no_fx_assumption"] is True


def test_offer_requires_complete_exact_asset_configuration(monkeypatch):
    _configure_quote(monkeypatch)
    monkeypatch.setenv(OFFER_ENABLE_ENV, "1")
    assert payment_offer_readiness()["payment_offer_configured"] is False

    _configure_offer(monkeypatch)
    assert payment_offer_readiness()["payment_offer_configured"] is True

    monkeypatch.setenv(ASSET_NAME_ENV, "USD")
    mismatch = payment_offer_readiness()
    assert mismatch["payment_offer_configured"] is False
    assert mismatch["launch_ready"] is False


def test_payment_required_is_exact_x402_v2_auth_capture_and_base_units(monkeypatch):
    _configure_offer(monkeypatch, price="1.25")
    at = datetime(2026, 9, 14, 19, 30, tzinfo=timezone.utc)
    required = build_payment_required(now=at)

    assert required["x402Version"] == 2
    assert required["resource"]["url"] == "https://aion.example/commercial/route-intelligence/purchase"
    accepted = required["accepts"][0]
    assert accepted["scheme"] == "auth-capture"
    assert accepted["network"] == "eip155:8453"
    assert accepted["amount"] == "1250000"
    assert accepted["extra"]["name"] == "USDC"
    assert accepted["extra"]["paymentFlow"] == "escrow"
    assert accepted["extra"]["captureMode"] == "deferred"
    assert accepted["extra"]["captureDeadline"] == int(at.timestamp()) + 300
    assert accepted["extra"]["refundDeadline"] == int(at.timestamp()) + 900
    assert accepted["extra"]["minFeeBps"] == 0
    assert accepted["extra"]["maxFeeBps"] == 100
    assert accepted["extra"]["assetTransferMethod"] == "eip3009"

    decoded = json.loads(base64.b64decode(encode_payment_required(required)).decode("utf-8"))
    assert decoded == required


def test_non_integral_asset_base_units_fail_closed(monkeypatch):
    _configure_offer(monkeypatch, price="0.0000001", fee="0")
    # Seven fractional digits cannot be represented exactly by a six-decimal asset.
    assert payment_offer_readiness()["payment_offer_configured"] is False


def test_public_readiness_route_records_no_payment_and_purchase_stays_503(monkeypatch):
    _configure_offer(monkeypatch)
    key = _agent()

    readiness = client.get("/commercial/route-intelligence/payment-readiness")
    assert readiness.status_code == 200
    data = readiness.json()
    assert data["payment_offer_configured"] is True
    assert data["launch_ready"] is False

    purchase = client.post(
        "/commercial/route-intelligence/purchase",
        headers={"Authorization": "Bearer " + key},
    )
    assert purchase.status_code == 503
    assert purchase.json()["code"] == "x402_payment_rail_not_activated"
    assert "PAYMENT-REQUIRED" not in purchase.headers


def test_signed_payload_is_never_echoed_or_accepted_without_live_handler(monkeypatch):
    _configure_offer(monkeypatch)
    key = _agent()
    secret_signature = "ZXhhbXBsZS1zaWduZWQtcGF5bG9hZA=="
    response = client.post(
        "/commercial/route-intelligence/purchase",
        headers={
            "Authorization": "Bearer " + key,
            "PAYMENT-SIGNATURE": secret_signature,
        },
    )
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "x402_live_payment_handler_not_implemented"
    assert body["payment_signature_accepted"] is False
    assert secret_signature not in response.text
    assert "PAYMENT-REQUIRED" not in response.headers


def test_402_header_is_emitted_only_when_all_activation_gates_are_true(monkeypatch):
    _configure_offer(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    monkeypatch.setattr(x402_payment_offer, "LIVE_PAYMENT_HANDLER_IMPLEMENTED", True)
    key = _agent()

    readiness = payment_offer_readiness()
    assert readiness["launch_ready"] is True
    response = client.post(
        "/commercial/route-intelligence/purchase",
        headers={"Authorization": "Bearer " + key},
    )
    assert response.status_code == 402
    required = json.loads(base64.b64decode(response.headers["PAYMENT-REQUIRED"]).decode("utf-8"))
    assert required["x402Version"] == 2
    assert required["accepts"][0]["scheme"] == "auth-capture"
    assert required["accepts"][0]["extra"]["paymentFlow"] == "escrow"
