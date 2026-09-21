"""Durable non-member commercial purchase evidence.

These rows are deliberately separate from Agent membership and Package 5 proof.
A buyer can purchase an AION-owned result without creating an AION identity.
Raw PAYMENT-SIGNATURE values and facilitator credentials are never persisted.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class RouteIntelligencePurchase(Base):
    __tablename__ = "route_intelligence_purchases"
    __table_args__ = (
        UniqueConstraint("purchase_id", name="uq_route_intelligence_purchase_id"),
        UniqueConstraint(
            "payment_payload_digest", name="uq_route_intelligence_payment_payload_digest"
        ),
        UniqueConstraint("transaction_id", name="uq_route_intelligence_transaction_id"),
        Index(
            "ix_route_intelligence_request_prepared",
            "request_digest",
            "prepared_at",
        ),
        Index(
            "ix_route_intelligence_purchase_state_updated",
            "state",
            "updated_at",
        ),
        CheckConstraint(
            "state IN ('prepared', 'settlement_claimed', 'settlement_pending', "
            "'entitled', 'settlement_failed', 'settlement_ambiguous')",
            name="ck_route_intelligence_purchase_state",
        ),
        CheckConstraint(
            "state = 'prepared' OR payment_payload_digest IS NOT NULL",
            name="ck_route_intelligence_claim_has_payment_digest",
        ),
        CheckConstraint(
            "state != 'entitled' OR "
            "(payment_payload_digest IS NOT NULL AND transaction_id IS NOT NULL "
            "AND payer IS NOT NULL AND settlement_response_digest IS NOT NULL "
            "AND entitled_at IS NOT NULL)",
            name="ck_route_intelligence_entitlement_evidence",
        ),
        CheckConstraint(
            "expires_at >= prepared_at",
            name="ck_route_intelligence_purchase_expiry_order",
        ),
        CheckConstraint(
            "entitled_at IS NULL OR entitled_at >= prepared_at",
            name="ck_route_intelligence_entitlement_time_order",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[str] = mapped_column(String(36), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(120), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    request_evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    prepared_result: Mapped[dict] = mapped_column(JSON, nullable=False)

    quote_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_amount: Mapped[str] = mapped_column(String(48), nullable=False)
    network: Mapped[str] = mapped_column(String(80), nullable=False)
    asset: Mapped[str] = mapped_column(String(80), nullable=False)
    asset_code: Mapped[str] = mapped_column(String(16), nullable=False)
    pay_to: Mapped[str] = mapped_column(String(80), nullable=False)
    atomic_amount: Mapped[str] = mapped_column(String(80), nullable=False)
    payment_requirements_digest: Mapped[str] = mapped_column(String(71), nullable=False)

    state: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_payload_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    payer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    settlement_response_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    accounting_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entitled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
