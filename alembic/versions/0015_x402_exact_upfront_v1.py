"""x402 exact upfront non-member purchase evidence.

Revision ID: 0015_x402_exact_upfront_v1
Revises: 0014_conversation_intel_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_x402_exact_upfront_v1"
down_revision = "0014_conversation_intel_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "route_intelligence_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("purchase_id", sa.String(length=36), nullable=False),
        sa.Column("product_sku", sa.String(length=120), nullable=False),
        sa.Column("request_digest", sa.String(length=71), nullable=False),
        sa.Column("request_evidence", sa.JSON(), nullable=False),
        sa.Column("result_digest", sa.String(length=71), nullable=False),
        sa.Column("prepared_result", sa.JSON(), nullable=False),
        sa.Column("quote_currency", sa.String(length=16), nullable=False),
        sa.Column("quote_amount", sa.String(length=48), nullable=False),
        sa.Column("network", sa.String(length=80), nullable=False),
        sa.Column("asset", sa.String(length=80), nullable=False),
        sa.Column("asset_code", sa.String(length=16), nullable=False),
        sa.Column("pay_to", sa.String(length=80), nullable=False),
        sa.Column("atomic_amount", sa.String(length=80), nullable=False),
        sa.Column("payment_requirements_digest", sa.String(length=71), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("payment_payload_digest", sa.String(length=71), nullable=True),
        sa.Column("transaction_id", sa.String(length=160), nullable=True),
        sa.Column("payer", sa.String(length=160), nullable=True),
        sa.Column("settlement_response_digest", sa.String(length=71), nullable=True),
        sa.Column("failure_code", sa.String(length=96), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entitled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("purchase_id", name="uq_route_intelligence_purchase_id"),
        sa.UniqueConstraint("request_digest", name="uq_route_intelligence_request_digest"),
        sa.UniqueConstraint(
            "payment_payload_digest", name="uq_route_intelligence_payment_payload_digest"
        ),
        sa.UniqueConstraint("transaction_id", name="uq_route_intelligence_transaction_id"),
        sa.CheckConstraint(
            "state IN ('prepared', 'settlement_claimed', 'settlement_pending', "
            "'entitled', 'settlement_failed', 'settlement_ambiguous')",
            name="ck_route_intelligence_purchase_state",
        ),
        sa.CheckConstraint(
            "state = 'prepared' OR payment_payload_digest IS NOT NULL",
            name="ck_route_intelligence_claim_has_payment_digest",
        ),
        sa.CheckConstraint(
            "state != 'entitled' OR "
            "(payment_payload_digest IS NOT NULL AND transaction_id IS NOT NULL "
            "AND payer IS NOT NULL AND settlement_response_digest IS NOT NULL "
            "AND entitled_at IS NOT NULL)",
            name="ck_route_intelligence_entitlement_evidence",
        ),
        sa.CheckConstraint(
            "expires_at >= prepared_at",
            name="ck_route_intelligence_purchase_expiry_order",
        ),
        sa.CheckConstraint(
            "entitled_at IS NULL OR entitled_at >= prepared_at",
            name="ck_route_intelligence_entitlement_time_order",
        ),
    )
    op.create_index(
        "ix_route_intelligence_purchase_state_updated",
        "route_intelligence_purchases",
        ["state", "updated_at"],
    )


def downgrade():
    op.drop_index(
        "ix_route_intelligence_purchase_state_updated",
        table_name="route_intelligence_purchases",
    )
    op.drop_table("route_intelligence_purchases")
