"""Package 6A controlled fixtures prove policy; they are not real money evidence."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import models
from app.db import SessionLocal
from app.main import MCP_VERSION, app
from app.security import hash_key
from app.services import economic_kernel, package5_proof
from app.services.economic_kernel import EconomicKernelError, TrustedEconomicPlan
from test_package5_proof import _action


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_economic_fixtures():
    with SessionLocal() as db:
        db.execute(delete(models.EconomicTransition))
        db.execute(delete(models.EconomicOperation))
        db.commit()
    yield
    with SessionLocal() as db:
        db.execute(delete(models.EconomicTransition))
        db.execute(delete(models.EconomicOperation))
        db.commit()


def _agent(*, external_id=None, name=None, endpoint=None):
    token = uuid.uuid4().hex
    key = "aion_package6a_" + token
    with SessionLocal() as db:
        row = models.Agent(
            external_id=external_id or "package6a-" + token,
            name=name or "Package 6A " + token,
            endpoint=endpoint,
            protocol="REST",
            api_key_hash=hash_key(key),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id, key


def _rest_preflight(key, *, idem=None, payload=None):
    return client.post(
        "/economic/preflight",
        headers={"Authorization": "Bearer " + key, "Idempotency-Key": idem or uuid.uuid4().hex},
        json=payload or {"product_sku": "aion.verified.callability.v1", "currency": "USD"},
    )


def _mcp(key, name, arguments):
    return client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer " + key,
            "MCP-Protocol-Version": MCP_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0", "id": "package6a", "method": "tools/call",
            "params": {
                "name": name, "arguments": arguments,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
                    "io.modelcontextprotocol/clientInfo": {"name": "package6a-tests", "version": "1"},
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        },
    )


class VerifiedFixtureAdapter:
    """Test-only evidence adapter. It never contacts a rail or provider."""

    enabled = True

    def verify(self, transition, evidence_reference):
        authorities = {
            "payment_authorized": "payment_rail_verified",
            "funds_reserved": "payment_rail_verified",
            "execution_started": "internal_executor_verified",
            "settlement_ready": "provider_meter_verified",
            "settled": "payment_rail_verified",
            "reserve_released": "payment_rail_verified",
        }
        assert evidence_reference.startswith("fixture:")
        return {"authority": authorities[transition], "digest": "sha256:" + "a" * 64}


def _transition(db, agent_id, operation_id, state, sequence, **kwargs):
    return economic_kernel.apply_economic_transition(
        db,
        requester_agent_id=agent_id,
        operation_id=operation_id,
        to_state=state,
        idempotency_key=f"fixture-transition-{sequence}",
        adapter=VerifiedFixtureAdapter(),
        evidence_reference=f"fixture:{sequence}",
        **kwargs,
    )


def test_exact_margin_floor_and_fail_closed_arithmetic():
    base = TrustedEconomicPlan(
        product_sku="fixture", currency="USD", customer_price="10",
        expected_variable_cost="5.5", maximum_variable_cost="5.5",
        verification_cost="0.5", payment_fee_allowance="0",
        maximum_attempts=1, commercial_rights_state="allowed",
        maximum_total_spend_cap="6", direct_expected_cost_per_vuo="6",
    )
    floor = economic_kernel.evaluate_plan(base, requested_currency="USD", requester_max_price=None)
    assert floor["expected_total_cost"] == "6"
    assert floor["contribution_amount"] == "4"
    assert floor["expected_margin_bps"] == 4000
    assert floor["policy_eligible"] is True

    below = economic_kernel.evaluate_plan(
        replace(base, expected_variable_cost="5.51", maximum_variable_cost="5.51", maximum_total_spend_cap="6.01"),
        requested_currency="USD", requester_max_price=None,
    )
    assert below["expected_total_cost"] == "6.01"
    assert below["expected_margin_bps"] == 3990
    assert "margin_below_floor" in below["decision_reasons"]

    loss = economic_kernel.evaluate_plan(
        replace(base, expected_variable_cost="11", maximum_variable_cost="11", verification_cost="0", maximum_total_spend_cap="11", direct_expected_cost_per_vuo="11"),
        requested_currency="USD", requester_max_price=None,
    )
    assert loss["contribution_amount"] == "-1"
    assert loss["policy_eligible"] is False


@pytest.mark.parametrize("value", ["-1", "NaN", "Infinity", "1e2", "1.0000001", "1000000000000000000", " 1", "1 ", ".5", "01"])
def test_malformed_negative_nonfinite_and_noncanonical_money_is_rejected(value):
    with pytest.raises(EconomicKernelError) as error:
        economic_kernel.canonical_money(value)
    assert error.value.code == "malformed_money"


def test_unknown_cost_rights_currency_budget_and_free_variable_cost_fail_closed():
    base = economic_kernel.TRUSTED_PRODUCT_PROFILES["aion.verified.callability.v1"]
    unknown_cost = economic_kernel.evaluate_plan(replace(base, maximum_variable_cost=None), requested_currency="USD", requester_max_price=None)
    assert unknown_cost["maximum_total_spend"] is None
    assert "unknown_maximum_cost" in unknown_cost["decision_reasons"]
    unknown_rights = economic_kernel.evaluate_plan(replace(base, commercial_rights_state="unknown"), requested_currency="USD", requester_max_price=None)
    assert "commercial_rights_unknown" in unknown_rights["decision_reasons"]
    free_paid = economic_kernel.evaluate_plan(
        replace(base, customer_price="0", expected_variable_cost="1", maximum_variable_cost="1", verification_cost="0", maximum_total_spend_cap="1", direct_expected_cost_per_vuo="1"),
        requested_currency="USD", requester_max_price=None,
    )
    assert "free_variable_cost_execution_prohibited" in free_paid["decision_reasons"]
    budget = economic_kernel.evaluate_plan(base, requested_currency="USD", requester_max_price="9.99")
    assert "requester_budget_below_price" in budget["decision_reasons"]
    assert "payment_not_authorized" in budget["decision_reasons"]
    with pytest.raises(EconomicKernelError, match="No FX adapter"):
        economic_kernel.evaluate_plan(base, requested_currency="EUR", requester_max_price=None)


def test_unknown_maximum_is_durably_unknown_not_coerced_to_zero(monkeypatch):
    agent_id, _ = _agent()
    unknown = replace(
        economic_kernel.TRUSTED_PRODUCT_PROFILES["aion.verified.callability.v1"],
        product_sku="fixture.unknown", maximum_variable_cost=None,
    )
    monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, "fixture.unknown", unknown)
    with SessionLocal() as db:
        result = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku="fixture.unknown",
            requested_currency="USD", requester_max_price=None,
            idempotency_key="unknown-maximum",
        )
        row = db.scalar(select(models.EconomicOperation).where(
            models.EconomicOperation.operation_id == result["operation_id"]
        ))
        assert result["maximum_variable_cost"] is None
        assert result["maximum_total_spend"] is None
        assert row.maximum_variable_cost is None and row.maximum_total_spend is None
        assert "unknown_maximum_cost" in result["decision_reasons"]


def test_rest_preflight_is_authenticated_strict_idempotent_and_not_funding():
    agent_id, key = _agent()
    with SessionLocal() as db:
        before_agent = db.get(models.Agent, agent_id)
        lifecycle_before = (before_agent.authenticated_calls, before_agent.last_seen_at, before_agent.first_useful_action_at)
        proof_before = package5_proof.package5_proof_snapshot(db)["counts"]
    response = _rest_preflight(key, idem="same-economic-request")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert data["policy_eligible"] is True
    assert data["execution_eligible"] is False
    assert data["payment_authorized"] is False
    assert data["reserve_established"] is False
    assert data["settlement_completed"] is False
    assert data["real_settlement_revenue"] == "0"
    assert data["truth_boundaries"]["requester_budget_is_not_funds"] is True
    replay = _rest_preflight(key, idem="same-economic-request").json()
    assert replay["operation_id"] == data["operation_id"] and replay["idempotent_replay"] is True
    conflict = _rest_preflight(key, idem="same-economic-request", payload={
        "product_sku": "aion.cached.utility.v1", "currency": "USD"
    })
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"
    injected = _rest_preflight(key, payload={
        "product_sku": "aion.verified.callability.v1", "currency": "USD",
        "paid": True, "provider_cost": "0", "settled": True,
    })
    assert injected.status_code == 422
    with SessionLocal() as db:
        after_agent = db.get(models.Agent, agent_id)
        assert (after_agent.authenticated_calls, after_agent.last_seen_at, after_agent.first_useful_action_at) == lifecycle_before
        assert package5_proof.package5_proof_snapshot(db)["counts"] == proof_before


def test_rest_and_mcp_share_requester_scoped_status_and_hide_credentials():
    agent_id, key = _agent()
    _, other_key = _agent()
    rest = _rest_preflight(key, idem="rest-mcp-parity").json()
    rpc = _mcp(other_key, "get_economic_operation", {"operation_id": rest["operation_id"]}).json()
    assert rpc["result"]["isError"] is True
    assert rpc["result"]["structuredContent"]["code"] == "economic_operation_forbidden"
    status = client.get(
        "/economic/operations/" + rest["operation_id"],
        headers={"Authorization": "Bearer " + key},
    )
    assert status.status_code == 200 and status.headers["cache-control"] == "private, no-store"
    mcp = _mcp(key, "get_economic_operation", {"operation_id": rest["operation_id"]})
    assert mcp.headers["cache-control"] == "private, no-store"
    assert mcp.json()["result"]["structuredContent"] == status.json()
    serialized = json.dumps(status.json())
    for secret in (key, "api_key_hash", "DATABASE_URL", "fixture:"):
        assert secret not in serialized
    assert status.json()["canonical_requester_agent_id"] == agent_id
    malformed = client.get(
        "/economic/operations/" + "x" * 500,
        headers={"Authorization": "Bearer " + key},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_operation_id"


def test_duplicate_raw_agent_rows_share_one_canonical_economic_identity():
    endpoint = "https://logical-" + uuid.uuid4().hex + ".example/a2a"
    first_id, first_key = _agent(name="Same Logical Agent", endpoint=endpoint)
    second_id, second_key = _agent(name="Same Logical Agent", endpoint=endpoint)
    created = _rest_preflight(second_key, idem="logical-shared").json()
    assert created["canonical_requester_agent_id"] == min(first_id, second_id)
    first_read = client.get(
        "/economic/operations/" + created["operation_id"],
        headers={"Authorization": "Bearer " + first_key},
    )
    assert first_read.status_code == 200
    assert first_read.json()["operation_id"] == created["operation_id"]


def test_mcp_preflight_matches_rest_policy_and_rejects_unknown_fields():
    _, key = _agent()
    rpc = _mcp(key, "economic_preflight", {
        "product_sku": "aion.cached.utility.v1", "currency": "USD", "idempotency_key": "mcp-zero"
    })
    data = rpc.json()["result"]["structuredContent"]
    assert rpc.headers["cache-control"] == "private, no-store"
    assert data["execution_eligible"] is True
    assert data["funding_required"] is False
    bad = _mcp(key, "economic_preflight", {
        "product_sku": "aion.cached.utility.v1", "currency": "USD",
        "idempotency_key": "mcp-injected", "authorized": True,
    }).json()
    assert bad["error"]["code"] == -32602


def test_real_money_transition_is_disabled_and_state_remains_quoted():
    agent_id, key = _agent()
    operation_id = _rest_preflight(key).json()["operation_id"]
    with SessionLocal() as db:
        with pytest.raises(EconomicKernelError) as error:
            economic_kernel.apply_economic_transition(
                db, requester_agent_id=agent_id, operation_id=operation_id,
                to_state="payment_authorized", idempotency_key="disabled-payment",
                evidence_reference="untrusted", amount="10", currency="USD",
            )
        assert error.value.code == "real_money_adapter_disabled"
        assert economic_kernel.get_operation(db, requester_agent_id=agent_id, operation_id=operation_id)["state"] == "quoted"


def test_complete_test_only_state_machine_requires_verified_action_and_is_idempotent(monkeypatch):
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id, key = _agent()
    operation_id = _rest_preflight(key, idem="full-state-machine").json()["operation_id"]
    with SessionLocal() as db:
        _transition(db, agent_id, operation_id, "payment_authorized", 1, amount="10", currency="USD")
        _transition(db, agent_id, operation_id, "funds_reserved", 2, amount="10", currency="USD")
        _transition(db, agent_id, operation_id, "execution_started", 3, amount="6", currency="USD")
        action_id = _action(agent_id, cost_amount="6", cost_currency="USD")
        _transition(db, agent_id, operation_id, "outcome_verified", 4, action_id=action_id)
        _transition(db, agent_id, operation_id, "settlement_ready", 5, amount="6", currency="USD")
        settled = _transition(db, agent_id, operation_id, "settled", 6, amount="10", currency="USD")
        replay = _transition(db, agent_id, operation_id, "settled", 6, amount="10", currency="USD")
        assert replay["operation_id"] == settled["operation_id"] and replay["idempotent_replay"] is True
        final = _transition(db, agent_id, operation_id, "reserve_released", 7, amount="0", currency="USD")
        assert final["state"] == "reserve_released"
        assert final["actual_cost"] == "6"
        assert final["real_settlement_revenue"] == "10"
        with pytest.raises(EconomicKernelError) as terminal:
            _transition(db, agent_id, operation_id, "failed", 8)
        assert terminal.value.code == "illegal_economic_transition"


def test_actual_cost_settlement_and_duplicate_settlement_fail_closed(monkeypatch):
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id, key = _agent()
    operation_id = _rest_preflight(key, idem="economic-caps").json()["operation_id"]
    with SessionLocal() as db:
        _transition(db, agent_id, operation_id, "payment_authorized", 1, amount="10", currency="USD")
        _transition(db, agent_id, operation_id, "funds_reserved", 2, amount="10", currency="USD")
        with pytest.raises(EconomicKernelError) as fallback:
            _transition(db, agent_id, operation_id, "execution_started", "fallback", amount="6.01", currency="USD")
        assert fallback.value.code == "paid_fallback_requires_reauthorization"
        _transition(db, agent_id, operation_id, "execution_started", 3, amount="6", currency="USD")
        action_id = _action(agent_id, cost_amount="6", cost_currency="USD")
        _transition(db, agent_id, operation_id, "outcome_verified", 4, action_id=action_id)
        with pytest.raises(EconomicKernelError) as cost:
            _transition(db, agent_id, operation_id, "settlement_ready", "too-much", amount="6.01", currency="USD")
        assert cost.value.code == "max_total_spend_exceeded"
        _transition(db, agent_id, operation_id, "settlement_ready", 5, amount="6", currency="USD")
        with pytest.raises(EconomicKernelError) as settlement:
            _transition(db, agent_id, operation_id, "settled", "wrong-settlement", amount="10.01", currency="USD")
        assert settlement.value.code == "settlement_amount_invalid"
        _transition(db, agent_id, operation_id, "settled", 6, amount="10", currency="USD")
        with pytest.raises(EconomicKernelError) as duplicate:
            _transition(db, agent_id, operation_id, "settled", "duplicate-settlement", amount="10", currency="USD")
        assert duplicate.value.code == "illegal_economic_transition"


def test_settlement_and_action_evidence_cannot_escape_quote_or_requester_scope(monkeypatch):
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id, key = _agent()
    other_id, _ = _agent()
    operation_id = _rest_preflight(key).json()["operation_id"]
    foreign_action = _action(other_id, cost_amount="6", cost_currency="USD")
    historical_owned_action = _action(agent_id, cost_amount="6", cost_currency="USD")
    with SessionLocal() as db:
        _transition(db, agent_id, operation_id, "payment_authorized", 1, amount="10", currency="USD")
        _transition(db, agent_id, operation_id, "funds_reserved", 2, amount="10", currency="USD")
        _transition(db, agent_id, operation_id, "execution_started", 3, amount="6", currency="USD")
        with pytest.raises(EconomicKernelError) as forbidden:
            _transition(db, agent_id, operation_id, "outcome_verified", 4, action_id=foreign_action)
        assert forbidden.value.code == "action_evidence_forbidden"
        with pytest.raises(EconomicKernelError) as historical:
            _transition(db, agent_id, operation_id, "outcome_verified", "historical", action_id=historical_owned_action)
        assert historical.value.code == "action_evidence_predates_execution_permission"


def test_parent_child_maximum_spend_is_one_nonexpanding_budget(monkeypatch):
    agent_id, _ = _agent()
    parent_plan = replace(
        economic_kernel.TRUSTED_PRODUCT_PROFILES["aion.verified.callability.v1"],
        product_sku="fixture.parent", expected_variable_cost="5", maximum_variable_cost="6",
        verification_cost="0", maximum_total_spend_cap="6", direct_expected_cost_per_vuo="5",
    )
    child_plan = replace(
        parent_plan, product_sku="fixture.child", expected_variable_cost="4",
        maximum_variable_cost="4", maximum_total_spend_cap="4", direct_expected_cost_per_vuo="4",
    )
    monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, "fixture.parent", parent_plan)
    monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, "fixture.child", child_plan)
    with SessionLocal() as db:
        parent = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku="fixture.parent", requested_currency="USD",
            requester_max_price=None, idempotency_key="parent",
        )
        child = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku="fixture.child", requested_currency="USD",
            requester_max_price=None, idempotency_key="child-one", parent_operation_id=parent["operation_id"],
        )
        assert child["parent_operation_id"] == parent["operation_id"]
        parent_status = economic_kernel.get_operation(db, requester_agent_id=agent_id, operation_id=parent["operation_id"])
        assert parent_status["allocated_child_maximum_spend"] == "4"
        assert parent_status["remaining_unallocated_maximum_spend"] == "2"
        with pytest.raises(EconomicKernelError) as budget:
            economic_kernel.create_preflight(
                db, requester_agent_id=agent_id, product_sku="fixture.child", requested_currency="USD",
                requester_max_price=None, idempotency_key="child-two", parent_operation_id=parent["operation_id"],
            )
        assert budget.value.code == "child_budget_exceeds_parent_remaining"
        monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
        _transition(db, agent_id, parent["operation_id"], "payment_authorized", "parent-auth", amount="10", currency="USD")
        _transition(db, agent_id, parent["operation_id"], "funds_reserved", "parent-reserve", amount="10", currency="USD")
        with pytest.raises(EconomicKernelError) as delegated:
            _transition(db, agent_id, parent["operation_id"], "execution_started", "parent-execute", amount="2", currency="USD")
        assert delegated.value.code == "parent_budget_delegated_to_children"


def test_parent_funded_child_cannot_create_a_second_customer_charge(monkeypatch):
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id, _ = _agent()
    parent_plan = replace(
        economic_kernel.TRUSTED_PRODUCT_PROFILES["aion.verified.callability.v1"],
        product_sku="fixture.delegating-parent", expected_variable_cost="4",
        maximum_variable_cost="6", verification_cost="0",
        maximum_total_spend_cap="6", direct_expected_cost_per_vuo="4",
    )
    child_plan = replace(
        parent_plan, product_sku="fixture.delegated-child", expected_variable_cost="3",
        maximum_variable_cost="4", maximum_total_spend_cap="4", direct_expected_cost_per_vuo="3",
    )
    monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, parent_plan.product_sku, parent_plan)
    monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, child_plan.product_sku, child_plan)
    with SessionLocal() as db:
        proof_before = package5_proof.package5_proof_snapshot(db)["counts"]
        parent = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku=parent_plan.product_sku,
            requested_currency="USD", requester_max_price=None, idempotency_key="delegating-parent",
        )
        child = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku=child_plan.product_sku,
            requested_currency="USD", requester_max_price=None, idempotency_key="delegated-child",
            parent_operation_id=parent["operation_id"],
        )
        assert child["funding_scope"] == "parent_reserved_budget"
        assert child["customer_settlement_scope"] == "parent_only"
        assert child["independent_customer_payment_allowed"] is False
        assert child["payment_authorized"] is child["reserve_established"] is False
        assert child["authorized_amount"] is child["reserved_amount"] is None
        assert child["real_settlement_revenue"] == "0"
        assert child["truth_boundaries"]["child_creates_independent_customer_charge"] is False
        for state in ("payment_authorized", "funds_reserved", "settled", "reserve_released"):
            with pytest.raises(EconomicKernelError) as forbidden:
                _transition(db, agent_id, child["operation_id"], state, "child-" + state, amount="10", currency="USD")
            assert forbidden.value.code == "child_uses_parent_funding"
        with pytest.raises(EconomicKernelError) as unfunded:
            _transition(db, agent_id, child["operation_id"], "execution_started", "child-unfunded", amount="4", currency="USD")
        assert unfunded.value.code == "parent_reserve_not_established"
        _transition(db, agent_id, parent["operation_id"], "payment_authorized", "parent-auth", amount="10", currency="USD")
        _transition(db, agent_id, parent["operation_id"], "funds_reserved", "parent-reserve", amount="10", currency="USD")
        with pytest.raises(EconomicKernelError) as fallback:
            _transition(db, agent_id, child["operation_id"], "execution_started", "child-fallback", amount="4.01", currency="USD")
        assert fallback.value.code == "paid_fallback_requires_reauthorization"
        monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)
        with pytest.raises(EconomicKernelError) as disabled:
            _transition(db, agent_id, child["operation_id"], "execution_started", "child-disabled", amount="4", currency="USD")
        assert disabled.value.code == "real_money_adapter_disabled"
        monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
        started = _transition(db, agent_id, child["operation_id"], "execution_started", "child-start", amount="4", currency="USD")
        assert started["transitions"][-1]["reason_code"] == "delegated_execution_under_parent_reserve"
        action_id = _action(agent_id, cost_amount="4", cost_currency="USD")
        _transition(db, agent_id, child["operation_id"], "outcome_verified", "child-outcome", action_id=action_id)
        ready = _transition(db, agent_id, child["operation_id"], "settlement_ready", "child-cost", amount="4", currency="USD")
        assert ready["state"] == "settlement_ready"
        assert ready["actual_cost"] == "4"
        assert ready["settlement_amount"] is None
        assert ready["real_settlement_revenue"] == "0"
        with pytest.raises(EconomicKernelError) as settlement:
            _transition(db, agent_id, child["operation_id"], "settled", "child-settle", amount="10", currency="USD")
        assert settlement.value.code == "child_uses_parent_funding"
        parent_status = economic_kernel.get_operation(
            db, requester_agent_id=agent_id, operation_id=parent["operation_id"]
        )
        assert parent_status["state"] == "funds_reserved"
        assert parent_status["real_settlement_revenue"] == "0"
        assert package5_proof.package5_proof_snapshot(db)["counts"] == proof_before


def test_parent_reserve_must_cover_full_delegated_maximum_risk(monkeypatch):
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id, _ = _agent()
    parent_plan = TrustedEconomicPlan(
        product_sku="fixture.parent-reserve-five", currency="USD", customer_price="5",
        expected_variable_cost="3", maximum_variable_cost="6", verification_cost="0",
        payment_fee_allowance="0", maximum_attempts=1, commercial_rights_state="allowed",
        maximum_total_spend_cap="6", direct_expected_cost_per_vuo="3",
    )
    child_plan = replace(
        parent_plan, product_sku="fixture.child-risk-six", expected_variable_cost="3",
        customer_price="5", direct_expected_cost_per_vuo="3",
    )
    monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, parent_plan.product_sku, parent_plan)
    monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, child_plan.product_sku, child_plan)
    with SessionLocal() as db:
        parent = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku=parent_plan.product_sku,
            requested_currency="USD", requester_max_price=None, idempotency_key="reserve-five-parent",
        )
        child = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku=child_plan.product_sku,
            requested_currency="USD", requester_max_price=None, idempotency_key="risk-six-child",
            parent_operation_id=parent["operation_id"],
        )
        _transition(db, agent_id, parent["operation_id"], "payment_authorized", "reserve-five-auth", amount="5", currency="USD")
        _transition(db, agent_id, parent["operation_id"], "funds_reserved", "reserve-five", amount="5", currency="USD")
        status = economic_kernel.get_operation(db, requester_agent_id=agent_id, operation_id=child["operation_id"])
        assert status["parent_funding_ready"] is False
        assert status["decision_reasons"] == ["parent_reserve_insufficient_for_delegated_budget"]
        with pytest.raises(EconomicKernelError) as insufficient:
            _transition(db, agent_id, child["operation_id"], "execution_started", "risk-six-start", amount="5", currency="USD")
        assert insufficient.value.code == "parent_reserve_insufficient_for_delegated_budget"


def test_child_rejects_unverified_parent_funding_fields(monkeypatch):
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id, _ = _agent()
    with SessionLocal() as db:
        parent = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku="aion.verified.callability.v1",
            requested_currency="USD", requester_max_price=None, idempotency_key="unverified-parent",
        )
        child = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku="aion.verified.callability.v1",
            requested_currency="USD", requester_max_price=None, idempotency_key="unverified-child",
            parent_operation_id=parent["operation_id"],
        )
        parent_row = db.scalar(select(models.EconomicOperation).where(
            models.EconomicOperation.operation_id == parent["operation_id"]
        ))
        parent_row.state = "funds_reserved"
        parent_row.authorized_amount = parent_row.customer_price
        parent_row.reserved_amount = parent_row.customer_price
        parent_row.adapter_state = "verified_adapter_evidence"
        db.commit()
        with pytest.raises(EconomicKernelError) as invalid:
            _transition(db, agent_id, child["operation_id"], "execution_started", "invalid-parent-evidence", amount="6", currency="USD")
        assert invalid.value.code == "parent_funding_evidence_invalid"


def test_child_parent_scope_rejects_other_requester_currency_and_expiry(monkeypatch):
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", True)
    agent_id, _ = _agent()
    other_id, _ = _agent()
    parent = None
    with SessionLocal() as db:
        parent = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku="aion.verified.callability.v1",
            requested_currency="USD", requester_max_price=None, idempotency_key="scope-parent",
        )
        with pytest.raises(EconomicKernelError) as requester:
            economic_kernel.create_preflight(
                db, requester_agent_id=other_id, product_sku="aion.verified.callability.v1",
                requested_currency="USD", requester_max_price=None, idempotency_key="wrong-requester-child",
                parent_operation_id=parent["operation_id"],
            )
        assert requester.value.code == "parent_operation_forbidden"
        eur = replace(
            economic_kernel.TRUSTED_PRODUCT_PROFILES["aion.verified.callability.v1"],
            product_sku="fixture.eur-child", currency="EUR",
        )
        monkeypatch.setitem(economic_kernel.TRUSTED_PRODUCT_PROFILES, eur.product_sku, eur)
        with pytest.raises(EconomicKernelError) as currency:
            economic_kernel.create_preflight(
                db, requester_agent_id=agent_id, product_sku=eur.product_sku,
                requested_currency="EUR", requester_max_price=None, idempotency_key="wrong-currency-child",
                parent_operation_id=parent["operation_id"],
            )
        assert currency.value.code == "currency_mismatch"
        child = economic_kernel.create_preflight(
            db, requester_agent_id=agent_id, product_sku="aion.verified.callability.v1",
            requested_currency="USD", requester_max_price=None, idempotency_key="expiring-child",
            parent_operation_id=parent["operation_id"],
        )
        _transition(db, agent_id, parent["operation_id"], "payment_authorized", "expiry-auth", amount="10", currency="USD")
        _transition(db, agent_id, parent["operation_id"], "funds_reserved", "expiry-reserve", amount="10", currency="USD")
        parent_row = db.scalar(select(models.EconomicOperation).where(
            models.EconomicOperation.operation_id == parent["operation_id"]
        ))
        monkeypatch.setattr(economic_kernel, "_now", lambda: economic_kernel._aware(parent_row.quote_expires_at) + timedelta(seconds=1))
        with pytest.raises(EconomicKernelError) as expired:
            _transition(db, agent_id, child["operation_id"], "execution_started", "expired-child", amount="6", currency="USD")
        assert expired.value.code == "parent_funding_expired"


def test_quote_expiry_and_resource_bound_fail_closed(monkeypatch):
    _, key = _agent()
    operation = _rest_preflight(key).json()
    with SessionLocal() as db:
        row = db.scalar(select(models.EconomicOperation).where(models.EconomicOperation.operation_id == operation["operation_id"]))
        expires = economic_kernel._aware(row.quote_expires_at)
        monkeypatch.setattr(economic_kernel, "_now", lambda: expires + timedelta(seconds=1))
        status = economic_kernel.get_operation(db, requester_agent_id=row.requester_agent_id, operation_id=row.operation_id)
        assert status["execution_eligible"] is False
        assert status["decision_reasons"] == ["quote_expired"]
    monkeypatch.setattr(economic_kernel, "MAX_LOGICAL_IDENTITIES", 0)
    limited = _rest_preflight(key)
    assert limited.status_code == 503
    assert limited.json()["detail"]["code"] == "economic_resource_limit"


def test_preflight_rate_guard_is_shared_and_creates_no_row_when_blocked(monkeypatch):
    _, key = _agent()
    monkeypatch.setattr(economic_kernel, "allow_economic_preflight", lambda agent_id: False)
    rest = _rest_preflight(key)
    assert rest.status_code == 429
    assert rest.json()["detail"]["code"] == "economic_rate_limited"
    rpc = _mcp(key, "economic_preflight", {
        "product_sku": "aion.cached.utility.v1", "currency": "USD",
        "idempotency_key": "rate-limited-mcp",
    }).json()
    assert rpc["result"]["structuredContent"]["code"] == "economic_rate_limited"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.EconomicOperation)) == 0


def test_body_limit_and_legacy_intent_never_create_economic_truth():
    _, key = _agent()
    oversized = client.post(
        "/economic/preflight",
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        content=b'{' + b' ' * (64 * 1024) + b'}',
    )
    assert oversized.status_code == 413
    injected = client.post(
        "/payments/intents",
        headers={"Authorization": "Bearer " + key},
        json={"purpose": "fixture", "amount": "1.00", "protocol": "x402", "paid": True},
    )
    assert injected.status_code == 422
    legacy = client.post(
        "/payments/intents",
        headers={"Authorization": "Bearer " + key},
        json={"purpose": "fixture", "amount": "1.00", "protocol": "x402"},
    )
    assert legacy.status_code == 200
    assert legacy.json()["economic_kernel_funding_evidence"] is False
    assert "not_authorization" in legacy.json()["semantic_class"]
    options = client.get("/donations/options").json()
    assert options["real_money_execution_enabled"] is False
    assert options["methods"][0]["status"] == "legacy_intent_only_adapter_disabled"
    for malformed in ("-1", "NaN", "1e2", "1.0000001", "1000000000000000000"):
        assert client.post(
            "/payments/intents", headers={"Authorization": "Bearer " + key},
            json={"purpose": "fixture", "amount": malformed, "protocol": "x402"},
        ).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(models.EconomicOperation)) == 0


def test_no_a2a_money_mutation_is_advertised():
    card = client.get("/.well-known/agent-card.json").json()
    serialized = json.dumps(card).lower()
    assert "mark-paid" not in serialized and "settle" not in serialized
    source = open("app/a2a_official.py", encoding="utf-8").read()
    for action in ("economic_preflight", "payment_authorized", "funds_reserved", "settled"):
        assert f'action == "{action}"' not in source
