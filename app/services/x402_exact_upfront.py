"""Production-first x402 v2 ``exact`` + ``upfront`` payment contract.

The contract is intentionally separate from the future auth-capture escrow path.
With ``upfront`` the facilitator settles before AION releases the prepared
resource, matching AION's PAY BEFORE EXECUTION law without pretending that a
settled payment is a reserve. V1 deliberately supports EIP-3009 only.
"""
from __future__ import annotations

import base64
from decimal import Decimal, InvalidOperation
import json
import os
import re

from ..public_origin import canonical_public_origin
from . import economic_kernel
from .cdp_x402_facilitator import facilitator_credential_readiness
from .paid_route_intelligence import (
    ROUTE_INTELLIGENCE_SKU,
    configured_route_intelligence_plan,
    route_intelligence_readiness,
)
from .x402_payment_offer import (
    ASSET_CODE_ENV,
    ASSET_DECIMALS_ENV,
    ASSET_ENV,
    ASSET_NAME_ENV,
    ASSET_TRANSFER_METHOD_ENV,
    ASSET_VERSION_ENV,
    MAX_TIMEOUT_SECONDS_ENV,
    NETWORK_ENV,
    PAY_TO_ENV,
)


EXACT_UPFRONT_ENABLE_ENV = "AION_X402_EXACT_UPFRONT_ENABLED"
LIVE_EXACT_SETTLEMENT_HANDLER_IMPLEMENTED = True

_CAIP_EVM = re.compile(r"^eip155:[1-9][0-9]{0,18}$")
_EVM_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ASSET_CODE = re.compile(r"^[A-Z][A-Z0-9]{2,15}$")
_TOKEN_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,64}$")
_TOKEN_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,16}$")
_PURCHASE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_RESULT_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ExactUpfrontError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _bounded_int(name: str, *, minimum: int, maximum: int) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip().isdigit():
        return None
    value = int(raw.strip())
    return value if minimum <= value <= maximum else None


def _address(name: str) -> str | None:
    value = (os.getenv(name) or "").strip()
    return value if _EVM_ADDRESS.fullmatch(value) else None


def _base_units(amount: str, decimals: int) -> str | None:
    try:
        value = Decimal(amount)
    except InvalidOperation:
        return None
    scaled = value * (Decimal(10) ** decimals)
    if scaled < 0 or scaled != scaled.to_integral_value():
        return None
    return str(int(scaled))


def configured_exact_upfront_offer() -> dict | None:
    if os.getenv(EXACT_UPFRONT_ENABLE_ENV) != "1":
        return None
    plan = configured_route_intelligence_plan()
    if plan is None:
        return None

    network = (os.getenv(NETWORK_ENV) or "").strip()
    asset = _address(ASSET_ENV)
    asset_code = (os.getenv(ASSET_CODE_ENV) or "").strip()
    token_name = (os.getenv(ASSET_NAME_ENV) or "").strip()
    token_version = (os.getenv(ASSET_VERSION_ENV) or "").strip()
    decimals = _bounded_int(ASSET_DECIMALS_ENV, minimum=0, maximum=18)
    pay_to = _address(PAY_TO_ENV)
    max_timeout = _bounded_int(MAX_TIMEOUT_SECONDS_ENV, minimum=1, maximum=3600)
    transfer_method = (os.getenv(ASSET_TRANSFER_METHOD_ENV) or "").strip()

    if not _CAIP_EVM.fullmatch(network):
        return None
    if asset is None or pay_to is None or decimals is None or max_timeout is None:
        return None
    if not _ASSET_CODE.fullmatch(asset_code) or asset_code != plan.currency:
        return None
    if not _TOKEN_NAME.fullmatch(token_name) or not _TOKEN_VERSION.fullmatch(token_version):
        return None
    if transfer_method != "eip3009":
        return None

    amount = _base_units(plan.customer_price, decimals)
    if amount is None or int(amount) <= 0:
        return None

    return {
        "network": network,
        "asset": asset,
        "asset_code": asset_code,
        "token_name": token_name,
        "token_version": token_version,
        "asset_decimals": decimals,
        "pay_to": pay_to,
        "atomic_amount": amount,
        "quote_currency": plan.currency,
        "quote_amount": plan.customer_price,
        "max_timeout_seconds": max_timeout,
        "asset_transfer_method": transfer_method,
    }


def exact_payment_requirements() -> dict:
    offer = configured_exact_upfront_offer()
    if offer is None:
        raise ExactUpfrontError(
            "x402_exact_upfront_not_configured",
            "Bounded x402 exact upfront EIP-3009 offer is not fully configured",
        )
    return {
        "scheme": "exact",
        "network": offer["network"],
        "amount": offer["atomic_amount"],
        "asset": offer["asset"],
        "payTo": offer["pay_to"],
        "maxTimeoutSeconds": offer["max_timeout_seconds"],
        "extra": {
            "name": offer["token_name"],
            "version": offer["token_version"],
            "assetTransferMethod": "eip3009",
            "paymentFlow": "upfront",
        },
    }


def bound_exact_payment_requirements(purchase_id: str, prepared_result_digest: str) -> dict:
    """Add a server-enforced frozen-result identity to the x402 envelope.

    x402 v2 clients echo selected PaymentRequirements in
    ``PaymentPayload.accepted``. The AION values are non-secret scheme-specific
    metadata that let the resource server reject an envelope for the wrong
    prepared snapshot. They do not change the EIP-3009 cryptographic statement:
    that signature still authorizes only the token transfer fields defined by
    EIP-3009. Transfer-identity replay prevention is enforced separately.
    """
    normalized_purchase_id = str(purchase_id or "").lower()
    normalized_digest = str(prepared_result_digest or "").lower()
    if not _PURCHASE_ID.fullmatch(normalized_purchase_id):
        raise ExactUpfrontError("invalid_purchase_binding", "Purchase ID is not a canonical UUID")
    if not _RESULT_DIGEST.fullmatch(normalized_digest):
        raise ExactUpfrontError(
            "invalid_purchase_binding", "Prepared result digest is not a canonical sha256 digest"
        )
    requirements = exact_payment_requirements()
    requirements["extra"] = {
        **requirements["extra"],
        "aionPurchaseId": normalized_purchase_id,
        "aionPreparedResultDigest": normalized_digest,
    }
    return requirements


def build_exact_payment_required(requirements: dict | None = None) -> dict:
    requirements = exact_payment_requirements() if requirements is None else requirements
    resource_url = (
        canonical_public_origin().rstrip("/")
        + "/commercial/route-intelligence/purchase"
    )
    return {
        "x402Version": 2,
        "error": "PAYMENT-SIGNATURE header is required",
        "resource": {
            "url": resource_url,
            "description": (
                "AION Verified Route Intelligence: a prepared bounded route and "
                "verification evidence result"
            ),
            "mimeType": "application/json",
        },
        "accepts": [requirements],
    }


def encode_exact_payment_required(payment_required: dict) -> str:
    raw = json.dumps(
        payment_required,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def exact_upfront_readiness() -> dict:
    product = route_intelligence_readiness()
    offer = configured_exact_upfront_offer()
    credentials = facilitator_credential_readiness()
    configured = offer is not None
    plan = configured_route_intelligence_plan()
    network = (os.getenv(NETWORK_ENV) or "").strip()
    asset_code = (os.getenv(ASSET_CODE_ENV) or "").strip()
    token_name = (os.getenv(ASSET_NAME_ENV) or "").strip()
    token_version = (os.getenv(ASSET_VERSION_ENV) or "").strip()
    transfer_method = (os.getenv(ASSET_TRANSFER_METHOD_ENV) or "").strip()
    reasons = []
    if not product.get("quote_configured"):
        reasons.append("route_intelligence_quote_not_configured")
        reasons.extend(product.get("blocking_reasons") or [])
    if os.getenv(EXACT_UPFRONT_ENABLE_ENV) != "1":
        reasons.append("x402_exact_upfront_disabled")
    if not _CAIP_EVM.fullmatch(network):
        reasons.append("payment_network_missing_or_invalid")
    if _address(ASSET_ENV) is None:
        reasons.append("asset_address_missing_or_invalid")
    if not _ASSET_CODE.fullmatch(asset_code):
        reasons.append("asset_code_missing_or_invalid")
    elif plan is not None and asset_code != plan.currency:
        reasons.append("asset_code_quote_currency_mismatch")
    if not _TOKEN_NAME.fullmatch(token_name):
        reasons.append("asset_name_missing_or_invalid")
    if not _TOKEN_VERSION.fullmatch(token_version):
        reasons.append("asset_version_missing_or_invalid")
    if _bounded_int(ASSET_DECIMALS_ENV, minimum=0, maximum=18) is None:
        reasons.append("asset_decimals_missing_or_invalid")
    elif plan is not None:
        atomic_amount = _base_units(
            plan.customer_price,
            _bounded_int(ASSET_DECIMALS_ENV, minimum=0, maximum=18),
        )
        if atomic_amount is None or int(atomic_amount) <= 0:
            reasons.append("quote_not_representable_in_asset_atomic_units")
    if _address(PAY_TO_ENV) is None:
        reasons.append("pay_to_address_invalid")
    if _bounded_int(MAX_TIMEOUT_SECONDS_ENV, minimum=1, maximum=3600) is None:
        reasons.append("payment_timeout_missing_or_invalid")
    if transfer_method != "eip3009":
        reasons.append("asset_transfer_method_not_eip3009")
    reasons.extend(credentials["blocking_reasons"])
    if not configured and not reasons:
        reasons.append("payment_offer_not_configured")
    activation_ready_except_master_gate = bool(
        configured
        and credentials["credentials_locally_valid"]
        and LIVE_EXACT_SETTLEMENT_HANDLER_IMPLEMENTED
    )
    if not economic_kernel.REAL_MONEY_EXECUTION_ENABLED:
        reasons.append("real_money_execution_disabled")
    return {
        "product_sku": ROUTE_INTELLIGENCE_SKU,
        "protocol": "x402",
        "x402_version": 2,
        "scheme": "exact",
        "payment_flow": "upfront",
        "asset_transfer_method": "eip3009",
        "quote_configured": bool(product.get("quote_configured")),
        "payment_offer_configured": configured,
        "facilitator_credentials_configured": bool(
            credentials["key_id_present"] and credentials["secret_present"]
        ),
        "facilitator_credentials_locally_valid": credentials["credentials_locally_valid"],
        "facilitator_remote_acceptance_verified": credentials["remote_acceptance_verified"],
        "pay_to_address_configured": _address(PAY_TO_ENV) is not None,
        "live_payment_handler_implemented": LIVE_EXACT_SETTLEMENT_HANDLER_IMPLEMENTED,
        "real_money_execution_enabled": bool(economic_kernel.REAL_MONEY_EXECUTION_ENABLED),
        "activation_ready_except_master_gate": activation_ready_except_master_gate,
        "launch_ready": bool(
            activation_ready_except_master_gate
            and economic_kernel.REAL_MONEY_EXECUTION_ENABLED
        ),
        "blocking_reasons": list(dict.fromkeys(reasons)),
        "asset_code": offer["asset_code"] if offer else None,
        "network": offer["network"] if offer else None,
        "purchase_endpoint": "/commercial/route-intelligence/purchase",
        "truth_boundaries": {
            "settlement_happens_before_resource_release": True,
            "upfront_settlement_is_not_a_reserve": True,
            "buyer_membership_required": False,
            "requester_budget_is_not_funds": True,
            "no_hidden_fx": True,
            "raw_payment_signature_persisted": False,
            "permit2_not_in_launch_scope": True,
            "server_enforces_envelope_purchase_and_result_binding": True,
            "eip3009_signature_does_not_sign_aion_purchase_metadata": True,
            "credential_validation_is_local_shape_validation_not_remote_acceptance": True,
        },
    }
