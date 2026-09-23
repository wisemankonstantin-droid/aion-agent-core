"""Read-only first-SAT activation preflight; never contacts a payment rail."""

import json

from app.services import economic_kernel
from app.services.direct_base_usdc import (
    BASE_USDC_ADDRESS,
    DIRECT_ENABLE_ENV,
)
from app.services.first_sat_activation import first_sat_activation_preflight
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
)
from app.services.x402_payment_offer import (
    ASSET_CODE_ENV,
    ASSET_DECIMALS_ENV,
    ASSET_ENV,
    NETWORK_ENV,
    PAY_TO_ENV,
)


def _configured_environment(monkeypatch):
    values = {
        QUOTE_ENABLE_ENV: "1",
        CURRENCY_ENV: "USDC",
        PRICE_ENV: "1.25",
        MAX_PAYMENT_FEE_ENV: "0.10",
        DIRECT_ENABLE_ENV: "1",
        NETWORK_ENV: "eip155:8453",
        ASSET_ENV: BASE_USDC_ADDRESS,
        ASSET_CODE_ENV: "USDC",
        ASSET_DECIMALS_ENV: "6",
        PAY_TO_ENV: "0x" + "2" * 40,
        "AION_RELEASE_SHA": "a" * 40,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_preflight_is_secret_safe_read_only_and_stops_at_master_gate(monkeypatch):
    configured = _configured_environment(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)

    class CurrentSchemaSession:
        def scalars(self, statement):
            return iter(["0018_acquisition_agent_minds_v1"])

    result = first_sat_activation_preflight(CurrentSchemaSession(), expected_release_sha="a" * 40)

    serialized = json.dumps(result, sort_keys=True)
    assert "CDP_API_KEY" not in serialized
    assert result["preflight_only"] is True
    assert result["facilitator_contacted"] is False
    assert result["blockchain_rpc_contacted"] is False
    assert result["payment_attempted"] is False
    assert result["schema"]["current"] is True
    assert result["release"]["release_sha"] == "a" * 40
    assert result["payment"]["buyer_pays_gas"] is True
    assert result["payment"]["facilitator_required"] is False
    assert result["activation_ready_except_master_gate"] is True
    assert result["activation_ready"] is False
    assert result["blocking_reasons"] == ["real_money_execution_disabled"]
    assert result["human_gate"] == {
        "required": True,
        "action": "explicitly_enable_AION_REAL_MONEY_EXECUTION_ENABLED_for_one_authorized_SAT",
    }


def test_preflight_reports_schema_and_release_identity_blockers(monkeypatch):
    _configured_environment(monkeypatch)
    monkeypatch.delenv("AION_RELEASE_SHA")
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)

    class SchemaBehindSession:
        def scalars(self, statement):
            return iter(["0016_official_data_execution_v1"])

    result = first_sat_activation_preflight(SchemaBehindSession(), expected_release_sha="a" * 40)

    assert result["schema"]["current"] is False
    assert result["release"]["release_sha"] is None
    assert "release_sha_unavailable" in result["blocking_reasons"]
    assert "database_schema_not_current" in result["blocking_reasons"]
    assert result["activation_ready_except_master_gate"] is False


def test_preflight_requires_exact_expected_release_and_representable_atomic_price(monkeypatch):
    _configured_environment(monkeypatch)
    monkeypatch.setattr(economic_kernel, "REAL_MONEY_EXECUTION_ENABLED", False)

    class CurrentSchemaSession:
        def scalars(self, statement):
            return iter(["0018_acquisition_agent_minds_v1"])

    missing = first_sat_activation_preflight(CurrentSchemaSession())
    assert "expected_release_sha_missing_or_invalid" in missing["blocking_reasons"]
    assert missing["activation_ready_except_master_gate"] is False

    mismatch = first_sat_activation_preflight(
        CurrentSchemaSession(), expected_release_sha="b" * 40
    )
    assert "release_sha_mismatch" in mismatch["blocking_reasons"]
    assert mismatch["activation_ready_except_master_gate"] is False

    monkeypatch.setenv(ASSET_DECIMALS_ENV, "0")
    non_atomic = first_sat_activation_preflight(
        CurrentSchemaSession(), expected_release_sha="a" * 40
    )
    assert "direct_payment_asset_decimals_not_6" in non_atomic["blocking_reasons"]
    assert non_atomic["activation_ready_except_master_gate"] is False
    assert non_atomic["human_gate"]["required"] is False