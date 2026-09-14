"""x402 escrow contract tests are fixture-only and perform no real payment."""

import uuid

import pytest
from sqlalchemy import delete

from app import models
from app.db import SessionLocal
from app.security import hash_key
from app.services import economic_kernel
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
)
from app.services.x402_escrow_contract import (
    X402EscrowReceiptVerifier,
    authorize_payment_operation,
    capture_settlement_operation,
    reserve_funds_operation,
    void_reserved_operation,
    x402_escrow_readiness,
)
from test_package5_proof import _action


@pytest.fixture(autouse=True)
def reset_x402_fixtures(monkeypatch):
    for name in (QUOTE_ENABLE_ENV, CURRENCY_ENV, PRICE_ENV, MAX_PAYMENT_FEE_ENV):
        monkeypatch.delenv(name, raising=False)
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)
    with SessionLocal() as db:
        db.execute(delete(models.EconomicTransition))
        db.execute(delete(models.EconomicOperation))
        db.commit()
    yield
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    with SessionLocal() as db:
        db.execute(delete(models.EconomicTransition))
        db.execute(delete(models.EconomicOperation))
        db.commit()


def _agent():
    token = uuid.uuid4().hex
    key = "aion_x402_" + token
    with SessionLocal() as db:
        row = models.Agent(
            external_id="x402-" + token,
            name="x402 fixture " + token,
            protocol="REST",
            api_key_hash=hash_key(key),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id


def _configure_plan(monkeypatch, *, currency="USDC", price="1", fee="0.1"):
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(CURRENCY_ENV, currency)
    monkeypatch.setenv(PRICE_ENV, price)
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, fee)
    assert register_paid_route_intelligence_profile() is True


def _quote(agent_id, *, idem=None):
    with SessionLocal() as db:
        return economic_kernel.create_preflight(
            db,
            requester_agent_id=agent_id,
            product_sku=ROUTE_INTELLIGENCE_SKU,
            requested_currency="USDC",
            requester_max_price="1",
            idempotency_key=idem or "quote-" + uuid.uuid4().hex,
        )


def _receipt(lifecycle, *, amount="1", currency="USDC", suffix=None, **overrides):
    suffix = suffix or uuid.uuid4().hex
    data = {
        "protocol": "x402",
        "protocol_version": "2",
        "scheme": "auth-capture",
        "payment_flow": "escrow",
        "lifecycle_operation": lifecycle,
        "success": True,
        "payment_id": "payment-" + suffix,
        "network": "eip155:8453",
        "asset": "USDC",
        "rail_reference": "rail-" + suffix,
        "quote_currency": currency,
        "quote_amount": amount,
    }
    data.update(overrides)
    return data


class ReceiptBook:
    def __init__(self, mapping):
        self.mapping = mapping

    def __call__(self, ref):
        return self.mapping[ref]


def _verifier(mapping, *, enabled=True, authority="trusted_facilitator_receipt_resolver"):
    return X402EscrowReceiptVerifier(
        ReceiptBook(mapping),
        enabled=enabled,
        resolver_authority=authority,
    )


class InternalFixtureAdapter:
    enabled = True

    def verify(self, transition, evidence_reference):
        assert evidence_reference.startswith("fixture:")
        authority = {
            "execution_started": "internal_executor_verified",
            "settlement_ready": "provider_meter_verified",
        }[transition]
        return {"authority": authority, "digest": "sha256:" + "b" * 64}


def _internal_transition(db, agent_id, operation_id, state, amount, sequence):
    return economic_kernel.apply_economic_transition(
        db,
        requester_agent_id=agent_id,
        operation_id=operation_id,
        to_state=state,
        idempotency_key=f"internal-{state}-{sequence}",
        adapter=InternalFixtureAdapter(),
        evidence_reference=f"fixture:{state}:{sequence}",
        amount=amount,
        currency="USDC",
    )


def test_readiness_is_truthful_and_disabled_by_default():
    readiness = x402_escrow_readiness()
    assert readiness["protocol"] == "x402"
    assert readiness["protocol_version"] == "2"
    assert readiness["scheme"] == "auth-capture"
    assert readiness["payment_flow"] == "escrow"
    assert readiness["verify_semantics"] == "authorization_evidence_only_not_funds_reserved"
    assert readiness["receipt_amount_and_currency_binding_required"] is True
    assert readiness["generic_unbound_adapter_allowed"] is False
    assert readiness["network_transport_implemented"] is False
    assert readiness["real_money_launch_ready"] is False


def test_disabled_or_untrusted_receipt_resolver_cannot_advance_money(monkeypatch):
    _configure_plan(monkeypatch)
    agent_id = _agent()
    operation_id = _quote(agent_id)["operation_id"]
    mapping = {"verify": _receipt("verify")}

    with SessionLocal() as db:
        with pytest.raises(economic_kernel.EconomicKernelError) as disabled:
            authorize_payment_operation(
                db,
                requester_agent_id=agent_id,
                operation_id=operation_id,
                idempotency_key="disabled",
                verifier=_verifier(mapping, enabled=False),
                evidence_reference="verify",
            )
        assert disabled.value.code == "real_money_adapter_disabled"

        with pytest.raises(economic_kernel.EconomicKernelError) as untrusted:
            authorize_payment_operation(
                db,
                requester_agent_id=agent_id,
                operation_id=operation_id,
                idempotency_key="untrusted",
                verifier=_verifier(mapping, authority="requester_supplied_json"),
                evidence_reference="verify",
            )
        assert untrusted.value.code == "unverified_economic_evidence"
        assert economic_kernel.get_operation(
            db, requester_agent_id=agent_id, operation_id=operation_id
        )["state"] == "quoted"


def test_verify_is_authorization_only_and_never_creates_reserve(monkeypatch):
    _configure_plan(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id = _agent()
    operation_id = _quote(agent_id)["operation_id"]
    mapping = {
        "verify": _receipt("verify", suffix="verify"),
        "wrong-reserve": _receipt("verify", suffix="wrong-reserve"),
    }
    verifier = _verifier(mapping)

    with SessionLocal() as db:
        authorized = authorize_payment_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="authorize",
            verifier=verifier,
            evidence_reference="verify",
        )
        assert authorized["state"] == "payment_authorized"
        assert authorized["payment_authorized"] is True
        assert authorized["reserve_established"] is False
        assert authorized["reserved_amount"] is None

        with pytest.raises(economic_kernel.EconomicKernelError) as mismatch:
            reserve_funds_operation(
                db,
                requester_agent_id=agent_id,
                operation_id=operation_id,
                idempotency_key="reserve-wrong-lifecycle",
                verifier=verifier,
                evidence_reference="wrong-reserve",
            )
        assert mismatch.value.code == "x402_lifecycle_mismatch"
        status = economic_kernel.get_operation(
            db, requester_agent_id=agent_id, operation_id=operation_id
        )
        assert status["state"] == "payment_authorized"
        assert status["reserve_established"] is False


def test_authorize_receipt_creates_reserve_only_after_prior_payment_authorization(monkeypatch):
    _configure_plan(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id = _agent()
    operation_id = _quote(agent_id)["operation_id"]
    mapping = {
        "verify": _receipt("verify", suffix="v"),
        "authorize": _receipt("authorize", suffix="a"),
    }
    verifier = _verifier(mapping)

    with SessionLocal() as db:
        with pytest.raises(economic_kernel.EconomicKernelError) as missing:
            reserve_funds_operation(
                db,
                requester_agent_id=agent_id,
                operation_id=operation_id,
                idempotency_key="reserve-before-auth",
                verifier=verifier,
                evidence_reference="authorize",
            )
        assert missing.value.code == "payment_not_authorized"

        authorize_payment_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="authorize-first",
            verifier=verifier,
            evidence_reference="verify",
        )
        reserved = reserve_funds_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="reserve-second",
            verifier=verifier,
            evidence_reference="authorize",
        )
        assert reserved["state"] == "funds_reserved"
        assert reserved["reserve_established"] is True
        assert reserved["reserved_amount"] == "1"
        assert reserved["settlement_completed"] is False


def test_receipt_must_match_immutable_amount_and_currency(monkeypatch):
    _configure_plan(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id = _agent()
    operation_id = _quote(agent_id)["operation_id"]
    verifier = _verifier({
        "wrong-amount": _receipt("verify", amount="0.999", suffix="amount"),
        "wrong-currency": _receipt("verify", currency="USD", suffix="currency"),
    })

    with SessionLocal() as db:
        for ref in ("wrong-amount", "wrong-currency"):
            with pytest.raises(economic_kernel.EconomicKernelError) as exc:
                authorize_payment_operation(
                    db,
                    requester_agent_id=agent_id,
                    operation_id=operation_id,
                    idempotency_key="bad-" + ref,
                    verifier=verifier,
                    evidence_reference=ref,
                )
            assert exc.value.code == "x402_receipt_amount_mismatch"
        assert economic_kernel.get_operation(
            db, requester_agent_id=agent_id, operation_id=operation_id
        )["state"] == "quoted"


@pytest.mark.parametrize(
    "receipt, expected_code",
    [
        (_receipt("verify", protocol="not-x402"), "invalid_x402_receipt"),
        (_receipt("verify", protocol_version="1"), "invalid_x402_receipt"),
        (_receipt("verify", scheme="exact"), "invalid_x402_receipt"),
        (_receipt("verify", payment_flow="authorization"), "invalid_x402_receipt"),
        (_receipt("verify", success=False), "x402_operation_not_successful"),
        (_receipt("verify", rail_reference="bad\nreference"), "invalid_x402_receipt"),
    ],
)
def test_malformed_or_non_escrow_receipts_fail_closed(monkeypatch, receipt, expected_code):
    _configure_plan(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id = _agent()
    operation_id = _quote(agent_id)["operation_id"]
    verifier = _verifier({"bad": receipt})

    with SessionLocal() as db:
        with pytest.raises(economic_kernel.EconomicKernelError) as exc:
            authorize_payment_operation(
                db,
                requester_agent_id=agent_id,
                operation_id=operation_id,
                idempotency_key="bad-receipt-" + uuid.uuid4().hex,
                verifier=verifier,
                evidence_reference="bad",
            )
        assert exc.value.code == expected_code
        assert economic_kernel.get_operation(
            db, requester_agent_id=agent_id, operation_id=operation_id
        )["state"] == "quoted"


def test_full_capture_path_records_revenue_only_after_verified_outcome(monkeypatch):
    _configure_plan(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id = _agent()
    operation_id = _quote(agent_id)["operation_id"]
    verifier = _verifier({
        "verify": _receipt("verify", suffix="full-v"),
        "authorize": _receipt("authorize", suffix="full-a"),
        "capture": _receipt("capture", suffix="full-c"),
    })

    with SessionLocal() as db:
        authorize_payment_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="full-auth",
            verifier=verifier,
            evidence_reference="verify",
        )
        reserve_funds_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="full-reserve",
            verifier=verifier,
            evidence_reference="authorize",
        )
        _internal_transition(db, agent_id, operation_id, "execution_started", "0.1", 1)
        action_id = _action(agent_id, cost_amount="0.1", cost_currency="USDC")
        economic_kernel.apply_economic_transition(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            to_state="outcome_verified",
            idempotency_key="full-outcome",
            action_id=action_id,
        )
        _internal_transition(db, agent_id, operation_id, "settlement_ready", "0.1", 2)
        before_capture = economic_kernel.get_operation(
            db, requester_agent_id=agent_id, operation_id=operation_id
        )
        assert before_capture["real_settlement_revenue"] == "0"
        assert before_capture["settlement_completed"] is False

        settled = capture_settlement_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="full-capture",
            verifier=verifier,
            evidence_reference="capture",
        )
        assert settled["state"] == "settled"
        assert settled["settlement_completed"] is True
        assert settled["settlement_amount"] == "1"
        assert settled["real_settlement_revenue"] == "1"


def test_verified_void_releases_full_hold_without_revenue_and_replays_safely(monkeypatch):
    _configure_plan(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id = _agent()
    operation_id = _quote(agent_id)["operation_id"]
    verifier = _verifier({
        "verify": _receipt("verify", suffix="void-v"),
        "authorize": _receipt("authorize", suffix="void-a"),
        "void": _receipt("void", suffix="void-r"),
        "different-void": _receipt("void", suffix="void-other"),
    })

    with SessionLocal() as db:
        authorize_payment_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="void-auth",
            verifier=verifier,
            evidence_reference="verify",
        )
        reserve_funds_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="void-reserve",
            verifier=verifier,
            evidence_reference="authorize",
        )
        voided = void_reserved_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="void-once",
            verifier=verifier,
            evidence_reference="void",
        )
        assert voided["state"] == "cancelled"
        assert voided["reserve_established"] is False
        assert voided["reserved_amount"] is None
        assert voided["released_amount"] == "1"
        assert voided["settlement_completed"] is False
        assert voided["real_settlement_revenue"] == "0"

        replay = void_reserved_operation(
            db,
            requester_agent_id=agent_id,
            operation_id=operation_id,
            idempotency_key="void-once",
            verifier=verifier,
            evidence_reference="void",
        )
        assert replay["idempotent_replay"] is True
        assert replay["state"] == "cancelled"

        with pytest.raises(economic_kernel.EconomicKernelError) as conflict:
            void_reserved_operation(
                db,
                requester_agent_id=agent_id,
                operation_id=operation_id,
                idempotency_key="void-once",
                verifier=verifier,
                evidence_reference="different-void",
            )
        assert conflict.value.code == "idempotency_conflict"
