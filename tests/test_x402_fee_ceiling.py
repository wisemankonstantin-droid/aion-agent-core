"""Economic fee-ceiling binding tests perform no real payment."""

from app.services import economic_kernel
from app.services.paid_route_intelligence import (
    CURRENCY_ENV,
    MAX_PAYMENT_FEE_ENV,
    PRICE_ENV,
    QUOTE_ENABLE_ENV,
    ROUTE_INTELLIGENCE_SKU,
    register_paid_route_intelligence_profile,
)
from app.services.x402_payment_offer import (
    ASSET_CODE_ENV,
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
    payment_offer_readiness,
)


def test_wire_fee_ceiling_cannot_exceed_economic_kernel_allowance(monkeypatch):
    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
    monkeypatch.setenv(QUOTE_ENABLE_ENV, "1")
    monkeypatch.setenv(CURRENCY_ENV, "USDC")
    monkeypatch.setenv(PRICE_ENV, "1")
    monkeypatch.setenv(MAX_PAYMENT_FEE_ENV, "0.01")
    assert register_paid_route_intelligence_profile() is True

    values = {
        OFFER_ENABLE_ENV: "1",
        NETWORK_ENV: "eip155:8453",
        ASSET_ENV: "0x" + "1" * 40,
        ASSET_CODE_ENV: "USDC",
        ASSET_NAME_ENV: "USD Coin",
        ASSET_VERSION_ENV: "2",
        ASSET_DECIMALS_ENV: "6",
        PAY_TO_ENV: "0x" + "2" * 40,
        AUTH_CAPTURE_ESCROW_ENV: "0x" + "3" * 40,
        CAPTURE_AUTHORIZER_ENV: "0x" + "4" * 40,
        RECEIVER_AUTHORIZER_ENV: "0x" + "5" * 40,
        FEE_RECIPIENT_ENV: "0x" + "6" * 40,
        MIN_FEE_BPS_ENV: "0",
        MAX_FEE_BPS_ENV: "200",
        MAX_TIMEOUT_SECONDS_ENV: "60",
        CAPTURE_WINDOW_SECONDS_ENV: "300",
        REFUND_WINDOW_SECONDS_ENV: "900",
        ASSET_TRANSFER_METHOD_ENV: "eip3009",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    # 2% of 1 USDC = 0.02 USDC, above the immutable 0.01 allowance.
    blocked = payment_offer_readiness()
    assert blocked["payment_offer_configured"] is False
    assert blocked["launch_ready"] is False

    # Exactly 1% = 0.01, so the wire ceiling now fits the economic allowance.
    # The safety invariant is asserted through observable readiness behavior,
    # not a duplicate diagnostic flag that could drift from enforcement.
    monkeypatch.setenv(MAX_FEE_BPS_ENV, "100")
    bounded = payment_offer_readiness()
    assert bounded["payment_offer_configured"] is True
    assert bounded["launch_ready"] is False

    economic_kernel.TRUSTED_PRODUCT_PROFILES.pop(ROUTE_INTELLIGENCE_SKU, None)
