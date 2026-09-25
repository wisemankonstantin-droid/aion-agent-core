from __future__ import annotations

import base64
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import commercial_payment_routes, economic_kernel
from app.services.commercial_payment_routes import install_commercial_payment_routes
from app.services.x402_exact_upfront import exact_payment_requirements


def _configure(monkeypatch):
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_QUOTE_ENABLED", "1")
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_CURRENCY", "USDC")
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_PRICE", "0.01")
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_MAX_PAYMENT_FEE", "0")
    monkeypatch.setenv("AION_X402_EXACT_UPFRONT_ENABLED", "1")
    monkeypatch.setenv("AION_X402_NETWORK", "eip155:8453")
    monkeypatch.setenv(
        "AION_X402_ASSET",
        "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    )
    monkeypatch.setenv("AION_X402_ASSET_CODE", "USDC")
    monkeypatch.setenv("AION_X402_ASSET_NAME", "USD Coin")
    monkeypatch.setenv("AION_X402_ASSET_VERSION", "2")
    monkeypatch.setenv("AION_X402_ASSET_DECIMALS", "6")
    monkeypatch.setenv(
        "AION_X402_PAY_TO",
        "0x50aB5ba3dc7aaF9a2d667DE7daADA016ad4C4067",
    )
    monkeypatch.setenv("AION_X402_MAX_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("AION_X402_ASSET_TRANSFER_METHOD", "eip3009")
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)


def _app(monkeypatch):
    _configure(monkeypatch)
    app = FastAPI()
    install_commercial_payment_routes(app)
    return app


def test_stateless_agent_readiness_audit_unpaid_returns_x402_without_database(monkeypatch):
    client = TestClient(_app(monkeypatch))
    response = client.get(
        "/commercial/agent-readiness-audit",
        params={"url": "https://example.com"},
    )
    assert response.status_code == 402
    body = response.json()
    assert body["x402Version"] == 2
    assert body["resource"]["serviceName"] == "AION Agent Readiness Audit"
    assert body["accepts"][0]["amount"] == "10000"
    assert body["accepts"][0]["extra"]["name"] == "USD Coin"
    assert response.headers["payment-required"]


def test_stateless_agent_readiness_audit_paid_delivers_without_database(monkeypatch):
    app = _app(monkeypatch)

    monkeypatch.setattr(
        commercial_payment_routes,
        "_agent_readiness_audit",
        lambda origin: {
            "product_sku": "aion.agent_readiness_audit.v1",
            "origin": origin,
            "score": 100,
            "verdict": "ready",
            "checks": {},
            "prioritized_fixes": [],
            "truth_boundaries": {"public_surfaces_only": True},
        },
    )
    monkeypatch.setattr(
        commercial_payment_routes,
        "settle_exact_upfront",
        lambda payload, requirements: {
            "outcome": "settled",
            "transaction": "0x" + "ab" * 32,
            "network": "eip155:8453",
            "payer": "0x" + "11" * 20,
            "amount": requirements["amount"],
        },
    )

    requirements = exact_payment_requirements()
    envelope = {
        "x402Version": 2,
        "accepted": requirements,
        "payload": {
            "signature": "0x" + "22" * 65,
            "authorization": {
                "from": "0x" + "11" * 20,
                "to": requirements["payTo"],
                "value": requirements["amount"],
                "validAfter": "0",
                "validBefore": "9999999999",
                "nonce": "0x" + "33" * 32,
            },
        },
    }
    signature = base64.b64encode(
        json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")

    client = TestClient(app)
    response = client.get(
        "/commercial/agent-readiness-audit",
        params={"url": "example.com/path"},
        headers={"PAYMENT-SIGNATURE": signature},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "delivered"
    assert body["database_required"] is False
    assert body["result"]["origin"] == "https://example.com"
    assert body["result"]["score"] == 100
    assert body["payment"]["amount"] == "0.01"
    assert body["payment"]["atomic_amount"] == "10000"
    assert response.headers["payment-response"]


def test_x402_manifest_advertises_stateless_agent_readiness_audit(monkeypatch):
    client = TestClient(_app(monkeypatch))
    response = client.get("/.well-known/x402")
    assert response.status_code == 200
    resources = response.json()["resources"]
    audit = next(
        item
        for item in resources
        if item["resource"].endswith("/commercial/agent-readiness-audit")
    )
    assert audit["method"] == "GET"
    assert audit["price"] == "0.01 USDC"
    assert audit["inputSchema"]["required"] == ["url"]
    assert audit["accepts"][0]["amount"] == "10000"
