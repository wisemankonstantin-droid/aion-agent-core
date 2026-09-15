"""CDP facilitator seam tests use local cryptographic fixtures only."""

import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.services import cdp_x402_facilitator, economic_kernel
from app.services.cdp_x402_facilitator import (
    CDP_API_KEY_ID_ENV,
    CDP_API_KEY_SECRET_ENV,
    CDP_SETTLE_URL,
    FacilitatorSettlementError,
    generate_cdp_request_jwt,
    settle_exact_upfront,
)
from app.services.safe_http import FetchResult


def _decode_b64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _ed25519_secret():
    private = ed25519.Ed25519PrivateKey.generate()
    seed = private.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    return private.public_key(), base64.b64encode(seed + public).decode("ascii")


@pytest.fixture(autouse=True)
def reset_facilitator(monkeypatch):
    monkeypatch.delenv(CDP_API_KEY_ID_ENV, raising=False)
    monkeypatch.delenv(CDP_API_KEY_SECRET_ENV, raising=False)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)


def _requirements():
    return {
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": "1250000",
        "asset": "0x" + "1" * 40,
        "payTo": "0x" + "2" * 40,
        "maxTimeoutSeconds": 60,
        "extra": {
            "name": "USD Coin",
            "version": "2",
            "assetTransferMethod": "eip3009",
            "paymentFlow": "upfront",
        },
    }


def _payload():
    requirements = _requirements()
    return {
        "x402Version": 2,
        "accepted": requirements,
        "payload": {
            "signature": "0x" + "a" * 130,
            "authorization": {
                "from": "0x" + "3" * 40,
                "to": requirements["payTo"],
                "value": requirements["amount"],
                "validAfter": "1",
                "validBefore": "4102444800",
                "nonce": "0x" + "b" * 64,
            },
        },
    }


def test_cdp_jwt_is_short_lived_request_bound_and_cryptographically_valid(monkeypatch):
    public, secret = _ed25519_secret()
    monkeypatch.setenv(CDP_API_KEY_ID_ENV, "organizations/test/apiKeys/key")
    monkeypatch.setenv(CDP_API_KEY_SECRET_ENV, secret)

    token = generate_cdp_request_jwt(now=1_800_000_000, nonce="fixture-nonce")
    header_part, claims_part, signature_part = token.split(".")
    header = json.loads(_decode_b64url(header_part))
    claims = json.loads(_decode_b64url(claims_part))
    public.verify(
        _decode_b64url(signature_part),
        (header_part + "." + claims_part).encode("ascii"),
    )

    assert header == {
        "alg": "EdDSA",
        "kid": "organizations/test/apiKeys/key",
        "nonce": "fixture-nonce",
        "typ": "JWT",
    }
    assert claims == {
        "iss": "cdp",
        "sub": "organizations/test/apiKeys/key",
        "nbf": 1_800_000_000,
        "exp": 1_800_000_120,
        "uri": "POST api.cdp.coinbase.com/platform/v2/x402/settle",
    }
    assert "uris" not in claims
    assert "aud" not in claims


def test_real_money_gate_blocks_before_credentials_or_network(monkeypatch):
    network_calls = []
    monkeypatch.setattr(
        cdp_x402_facilitator,
        "fetch_json",
        lambda *args, **kwargs: network_calls.append(1),
    )
    with pytest.raises(FacilitatorSettlementError) as error:
        settle_exact_upfront(_payload(), _requirements())
    assert error.value.code == "real_money_adapter_disabled"
    assert network_calls == []


def test_settlement_uses_fixed_endpoint_one_attempt_and_documented_base_alias(monkeypatch):
    _, secret = _ed25519_secret()
    monkeypatch.setenv(CDP_API_KEY_ID_ENV, "fixture-key")
    monkeypatch.setenv(CDP_API_KEY_SECRET_ENV, secret)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    calls = []

    def fake_fetch(method, url, *, payload, headers, policy):
        calls.append((method, url, payload, headers, policy))
        return (
            FetchResult(status=200, body=b"{}", error=None, attempts=1),
            {
                "success": True,
                "transaction": "0x" + "4" * 64,
                # CDP's settle response schema documents the short alias even
                # though v2 PaymentRequirements use CAIP-2 eip155:8453.
                "network": "base",
                "payer": "0x" + "3" * 40,
                "amount": "1250000",
            },
        )

    monkeypatch.setattr(cdp_x402_facilitator, "fetch_json", fake_fetch)
    result = settle_exact_upfront(_payload(), _requirements())
    assert result["outcome"] == "settled"
    assert result["network"] == "base"
    assert result["transaction"] == "0x" + "4" * 64
    assert len(calls) == 1
    method, url, body, headers, policy = calls[0]
    assert method == "POST" and url == CDP_SETTLE_URL
    assert policy.max_attempts == 1
    assert policy.max_response_bytes == 32_768
    assert body["x402Version"] == 2
    assert body["paymentPayload"] == _payload()
    assert body["paymentRequirements"] == _requirements()
    assert headers["Authorization"].startswith("Bearer ")


def test_success_network_alias_is_bounded_and_cross_chain_mismatch_is_ambiguous(monkeypatch):
    _, secret = _ed25519_secret()
    monkeypatch.setenv(CDP_API_KEY_ID_ENV, "fixture-key")
    monkeypatch.setenv(CDP_API_KEY_SECRET_ENV, secret)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)

    def wrong_network(method, url, *, payload, headers, policy):
        return (
            FetchResult(status=200, body=b"{}", error=None, attempts=1),
            {
                "success": True,
                "transaction": "0x" + "4" * 64,
                "network": "base-sepolia",
                "payer": "0x" + "3" * 40,
                "amount": "1250000",
            },
        )

    monkeypatch.setattr(cdp_x402_facilitator, "fetch_json", wrong_network)
    result = settle_exact_upfront(_payload(), _requirements())
    assert result == {
        "outcome": "ambiguous",
        "code": "settlement_network_mismatch",
        "detail": None,
    }


def test_server_or_transport_failure_is_ambiguous_and_never_retried(monkeypatch):
    _, secret = _ed25519_secret()
    monkeypatch.setenv(CDP_API_KEY_ID_ENV, "fixture-key")
    monkeypatch.setenv(CDP_API_KEY_SECRET_ENV, secret)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    calls = []

    def fake_fetch(method, url, *, payload, headers, policy):
        calls.append(1)
        return FetchResult(status=500, body=None, error="http_500", attempts=1), None

    monkeypatch.setattr(cdp_x402_facilitator, "fetch_json", fake_fetch)
    result = settle_exact_upfront(_payload(), _requirements())
    assert result["outcome"] == "ambiguous"
    assert result["code"] == "settlement_transport_ambiguous"
    assert calls == [1]


def test_documented_confirmation_timeout_is_pending_with_valid_transaction(monkeypatch):
    _, secret = _ed25519_secret()
    monkeypatch.setenv(CDP_API_KEY_ID_ENV, "fixture-key")
    monkeypatch.setenv(CDP_API_KEY_SECRET_ENV, secret)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)

    def timed_out(method, url, *, payload, headers, policy):
        return (
            FetchResult(status=200, body=b"{}", error=None, attempts=1),
            {
                "success": False,
                "errorReason": "settle_exact_evm_transaction_confirmation_timed_out",
                "errorMessage": "confirmation timed out",
                "transaction": "0x" + "5" * 64,
                "network": "base",
                "payer": "0x" + "3" * 40,
            },
        )

    monkeypatch.setattr(cdp_x402_facilitator, "fetch_json", timed_out)
    result = settle_exact_upfront(_payload(), _requirements())
    assert result["outcome"] == "pending"
    assert result["code"] == "settle_exact_evm_transaction_confirmation_timed_out"
    assert result["transaction"] == "0x" + "5" * 64

    def bad_timeout(method, url, *, payload, headers, policy):
        return (
            FetchResult(status=200, body=b"{}", error=None, attempts=1),
            {
                "success": False,
                "errorReason": "settle_exact_evm_transaction_confirmation_timed_out",
                "transaction": "not-a-transaction",
                "network": "base",
            },
        )

    monkeypatch.setattr(cdp_x402_facilitator, "fetch_json", bad_timeout)
    bad = settle_exact_upfront(_payload(), _requirements())
    assert bad["outcome"] == "ambiguous"
    assert bad["code"] == "settle_exact_evm_transaction_confirmation_timed_out_evidence_invalid"


def test_documented_node_failure_is_ambiguous_not_rejected(monkeypatch):
    _, secret = _ed25519_secret()
    monkeypatch.setenv(CDP_API_KEY_ID_ENV, "fixture-key")
    monkeypatch.setenv(CDP_API_KEY_SECRET_ENV, secret)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)

    def node_failure(method, url, *, payload, headers, policy):
        return (
            FetchResult(status=200, body=b"{}", error=None, attempts=1),
            {
                "success": False,
                "errorReason": "settle_exact_node_failure",
                "errorMessage": "node unavailable after submit",
                "transaction": "0x" + "6" * 64,
                "network": "base",
                "payer": "0x" + "3" * 40,
            },
        )

    monkeypatch.setattr(cdp_x402_facilitator, "fetch_json", node_failure)
    result = settle_exact_upfront(_payload(), _requirements())
    assert result["outcome"] == "ambiguous"
    assert result["code"] == "settle_exact_node_failure"
    assert result["transaction"] == "0x" + "6" * 64
    assert result["payer"] == "0x" + "3" * 40


def test_legacy_settlement_pending_requires_transaction_and_matching_network(monkeypatch):
    _, secret = _ed25519_secret()
    monkeypatch.setenv(CDP_API_KEY_ID_ENV, "fixture-key")
    monkeypatch.setenv(CDP_API_KEY_SECRET_ENV, secret)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)

    def pending(method, url, *, payload, headers, policy):
        return (
            FetchResult(status=200, body=b"{}", error=None, attempts=1),
            {
                "success": False,
                "errorReason": "settlement_pending",
                "errorMessage": "broadcast confirmation unknown",
                "transaction": "0x" + "5" * 64,
                "network": "base",
                "payer": "0x" + "3" * 40,
            },
        )

    monkeypatch.setattr(cdp_x402_facilitator, "fetch_json", pending)
    result = settle_exact_upfront(_payload(), _requirements())
    assert result["outcome"] == "pending"
    assert result["transaction"] == "0x" + "5" * 64
