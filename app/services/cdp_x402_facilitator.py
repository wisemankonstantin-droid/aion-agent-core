"""Bounded x402 facilitator settlement seam.

The active launch facilitator is XPay's public x402 v2 facilitator on Base. It
requires no API credentials and never receives an AION wallet private key.
Legacy CDP JWT helpers remain for compatibility/testing only. Settlement uses
exactly one POST attempt; an ambiguous transport result is never automatically
retried because the first request may already have committed payment.
"""
from __future__ import annotations

import base64
import json
import os
import time
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from . import economic_kernel
from .safe_http import FetchPolicy, fetch_json


CDP_API_KEY_ID_ENV = "CDP_API_KEY_ID"
CDP_API_KEY_SECRET_ENV = "CDP_API_KEY_SECRET"
CDP_SETTLE_URL = "https://api.cdp.coinbase.com/platform/v2/x402/settle"
CDP_SETTLE_HOST = "api.cdp.coinbase.com"
CDP_SETTLE_PATH = "/platform/v2/x402/settle"
XPAY_FACILITATOR_URL = "https://facilitator.xpay.sh"
XPAY_SETTLE_URL = XPAY_FACILITATOR_URL + "/settle"
ACTIVE_FACILITATOR_PROVIDER = "xpay_public"

_MAX_RESPONSE_BYTES = 32_768
_MAX_ERROR_DETAIL = 240
_EVM_TRANSACTION = __import__("re").compile(r"^0x[0-9a-fA-F]{64}$")
_EVM_ADDRESS = __import__("re").compile(r"^0x[0-9a-fA-F]{40}$")
_CDP_NETWORK_ALIASES = {
    "eip155:8453": "base",
    "eip155:84532": "base-sepolia",
}
# CDP documents confirmation timeout and node-failure settlement reasons. A
# confirmation timeout with a valid transaction is pending, not a rejection;
# node failure is ambiguous because the transport/node can fail after broadcast.
_CDP_PENDING_REASONS = {
    "settlement_pending",  # defensive compatibility with older facilitator responses
    "settle_exact_evm_transaction_confirmation_timed_out",
}
_CDP_AMBIGUOUS_REASONS = {
    "settle_exact_node_failure",
}


class FacilitatorSettlementError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def facilitator_credentials_configured() -> bool:
    return bool(
        (os.getenv(CDP_API_KEY_ID_ENV) or "").strip()
        and (os.getenv(CDP_API_KEY_SECRET_ENV) or "").strip()
    )


def facilitator_credential_readiness() -> dict:
    """Report active facilitator readiness without contacting a remote service.

    XPay's public facilitator requires no API key. CDP credential shape is still
    reported only as optional fallback metadata and never gates the active path.
    """
    key_id_present = bool((os.getenv(CDP_API_KEY_ID_ENV) or "").strip())
    secret = (os.getenv(CDP_API_KEY_SECRET_ENV) or "").strip()
    secret_present = bool(secret)
    secret_locally_valid = False
    if secret_present:
        try:
            _parse_private_key(secret)
            secret_locally_valid = True
        except FacilitatorSettlementError:
            pass
    cdp_fallback_valid = bool(
        key_id_present and secret_present and secret_locally_valid
    )
    return {
        "provider": ACTIVE_FACILITATOR_PROVIDER,
        "facilitator_url": XPAY_FACILITATOR_URL,
        "facilitator_ready": True,
        "credentials_required": False,
        "key_id_present": key_id_present,
        "secret_present": secret_present,
        "secret_locally_valid": secret_locally_valid,
        "credentials_locally_valid": cdp_fallback_valid,
        "remote_acceptance_verified": False,
        "blocking_reasons": [],
    }


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _parse_private_key(secret: str):
    value = secret.replace("\\n", "\n")
    try:
        key = serialization.load_pem_private_key(value.encode("utf-8"), password=None)
        if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1):
            return key
    except Exception:
        pass
    try:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) == 64:
            return ed25519.Ed25519PrivateKey.from_private_bytes(decoded[:32])
    except Exception:
        pass
    raise FacilitatorSettlementError(
        "invalid_cdp_api_key_secret",
        "CDP API key secret must be a supported EC PEM or 64-byte base64 Ed25519 key",
    )


def generate_cdp_request_jwt(
    *,
    method: str = "POST",
    host: str = CDP_SETTLE_HOST,
    path: str = CDP_SETTLE_PATH,
    now: int | None = None,
    nonce: str | None = None,
) -> str:
    key_id = (os.getenv(CDP_API_KEY_ID_ENV) or "").strip()
    secret = (os.getenv(CDP_API_KEY_SECRET_ENV) or "").strip()
    if not key_id or not secret:
        raise FacilitatorSettlementError(
            "cdp_credentials_missing", "CDP facilitator credentials are not configured"
        )
    if method != "POST" or host != CDP_SETTLE_HOST or path != CDP_SETTLE_PATH:
        raise FacilitatorSettlementError(
            "untrusted_facilitator_target", "Only the fixed CDP x402 settle endpoint is allowed"
        )

    private_key = _parse_private_key(secret)
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        algorithm = "ES256"
    elif isinstance(private_key, ed25519.Ed25519PrivateKey):
        algorithm = "EdDSA"
    else:  # pragma: no cover - defensive after strict parser
        raise FacilitatorSettlementError("unsupported_cdp_key", "Unsupported CDP key type")

    timestamp = int(time.time()) if now is None else int(now)
    header = {
        "alg": algorithm,
        "kid": key_id,
        "typ": "JWT",
        "nonce": nonce or uuid.uuid4().hex,
    }
    # Coinbase CDP request authentication binds one JWT to one exact request
    # through a singular `uri` claim: "METHOD host/path". Keep the claim set
    # minimal and aligned with the current official API examples; in particular
    # do not emit an `aud: null` value or a non-standard `uris` array.
    claims = {
        "sub": key_id,
        "iss": "cdp",
        "nbf": timestamp,
        "exp": timestamp + 120,
        "uri": f"POST {host}{path}",
    }
    signing_input = (
        _b64url(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        + "."
        + _b64url(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    ).encode("ascii")

    if algorithm == "EdDSA":
        signature = private_key.sign(signing_input)
    else:
        der = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r, s = decode_dss_signature(der)
        signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return signing_input.decode("ascii") + "." + _b64url(signature)


def _safe_detail(value) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:_MAX_ERROR_DETAIL]


def _network_matches(requirement_network: object, response_network: object) -> bool:
    """Accept only the documented CDP alias for the exact configured CAIP-2 network.

    x402 v2 requirements use CAIP-2 identifiers, while CDP's settle response
    schema documents human-readable Base aliases. Exact CAIP echoing is also
    accepted defensively. No fuzzy or cross-chain normalization is allowed.
    """
    expected = str(requirement_network or "")
    actual = str(response_network or "")
    if not expected or not actual:
        return False
    if actual == expected:
        return True
    return _CDP_NETWORK_ALIASES.get(expected) == actual


def _validated_pending_evidence(
    *,
    code: str,
    transaction: object,
    network: object,
    payer: object,
    error_message: object,
    data: dict,
    payment_requirements: dict,
) -> dict:
    if (
        isinstance(transaction, str)
        and _EVM_TRANSACTION.fullmatch(transaction)
        and _network_matches(payment_requirements.get("network"), network)
    ):
        return {
            "outcome": "pending",
            "code": code,
            "transaction": transaction.lower(),
            "network": network,
            "payer": payer.lower()
            if isinstance(payer, str) and _EVM_ADDRESS.fullmatch(payer)
            else None,
            "detail": _safe_detail(error_message),
            "response": data,
        }
    return {
        "outcome": "ambiguous",
        "code": code + "_evidence_invalid",
        "detail": _safe_detail(error_message),
        "response": data,
    }


def _ambiguous_with_optional_evidence(
    *,
    code: str,
    transaction: object,
    network: object,
    payer: object,
    error_message: object,
    data: dict,
    payment_requirements: dict,
) -> dict:
    result = {
        "outcome": "ambiguous",
        "code": code,
        "detail": _safe_detail(error_message),
        "response": data,
    }
    if (
        isinstance(transaction, str)
        and _EVM_TRANSACTION.fullmatch(transaction)
        and _network_matches(payment_requirements.get("network"), network)
    ):
        result["transaction"] = transaction.lower()
        result["network"] = network
        result["payer"] = (
            payer.lower()
            if isinstance(payer, str) and _EVM_ADDRESS.fullmatch(payer)
            else None
        )
    return result


def settle_exact_upfront(payment_payload: dict, payment_requirements: dict) -> dict:
    """Submit one bounded settlement attempt and classify the result truthfully."""
    if not economic_kernel.REAL_MONEY_EXECUTION_ENABLED:
        raise FacilitatorSettlementError(
            "real_money_adapter_disabled", "Real-money execution is disabled in code"
        )
    if not isinstance(payment_payload, dict) or not isinstance(payment_requirements, dict):
        raise FacilitatorSettlementError("malformed_payment", "Payment payload is malformed")

    body = {
        "x402Version": 2,
        "paymentPayload": payment_payload,
        "paymentRequirements": payment_requirements,
    }
    result, data = fetch_json(
        "POST",
        XPAY_SETTLE_URL,
        payload=body,
        headers={"Accept": "application/json"},
        policy=FetchPolicy(
            timeout_seconds=20.0,
            max_response_bytes=_MAX_RESPONSE_BYTES,
            max_attempts=1,
            max_resolved_addresses=4,
            user_agent="AION-x402-XPay-Settlement/0.8.0",
        ),
    )

    if result.error:
        if result.status is not None and 400 <= result.status < 500:
            return {
                "outcome": "rejected",
                "code": f"facilitator_http_{result.status}",
                "detail": None,
            }
        return {
            "outcome": "ambiguous",
            "code": "settlement_transport_ambiguous",
            "detail": _safe_detail(result.error),
        }
    if not isinstance(data, dict):
        return {
            "outcome": "ambiguous",
            "code": "facilitator_response_malformed",
            "detail": None,
        }

    success = data.get("success")
    network = data.get("network")
    transaction = data.get("transaction")
    payer = data.get("payer")
    amount = data.get("amount")
    error_reason = data.get("errorReason", data.get("error_reason"))
    error_message = data.get("errorMessage", data.get("error_message"))

    if success is True:
        if not _network_matches(payment_requirements.get("network"), network):
            return {"outcome": "ambiguous", "code": "settlement_network_mismatch", "detail": None}
        if not isinstance(transaction, str) or not _EVM_TRANSACTION.fullmatch(transaction):
            return {"outcome": "ambiguous", "code": "settlement_transaction_invalid", "detail": None}
        if not isinstance(payer, str) or not _EVM_ADDRESS.fullmatch(payer):
            return {"outcome": "ambiguous", "code": "settlement_payer_invalid", "detail": None}
        expected_amount = str(payment_requirements.get("amount") or "")
        if amount is not None and str(amount) != expected_amount:
            return {"outcome": "ambiguous", "code": "settlement_amount_mismatch", "detail": None}
        return {
            "outcome": "settled",
            "transaction": transaction.lower(),
            "network": network,
            "payer": payer.lower(),
            "amount": expected_amount,
            "response": data,
        }

    if success is False and error_reason in _CDP_PENDING_REASONS:
        return _validated_pending_evidence(
            code=str(error_reason),
            transaction=transaction,
            network=network,
            payer=payer,
            error_message=error_message,
            data=data,
            payment_requirements=payment_requirements,
        )

    if success is False and error_reason in _CDP_AMBIGUOUS_REASONS:
        return _ambiguous_with_optional_evidence(
            code=str(error_reason),
            transaction=transaction,
            network=network,
            payer=payer,
            error_message=error_message,
            data=data,
            payment_requirements=payment_requirements,
        )

    if success is False:
        return {
            "outcome": "rejected",
            "code": _safe_detail(error_reason) or "settlement_rejected",
            "detail": _safe_detail(error_message),
            "response": data,
        }
    return {
        "outcome": "ambiguous",
        "code": "facilitator_response_invalid",
        "detail": None,
    }
