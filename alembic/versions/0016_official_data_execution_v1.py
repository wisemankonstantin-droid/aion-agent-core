"""Durable evidence for one real zero-cost official-data execution path.

Revision ID: 0016_official_data_execution_v1
Revises: 0015_x402_exact_upfront_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_official_data_execution_v1"
down_revision = "0015_x402_exact_upfront_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "official_data_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("execution_id", sa.String(length=36), nullable=False),
        sa.Column(
            "requester_agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=71), nullable=False),
        sa.Column("capability", sa.String(length=120), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("provider_identifier", sa.String(length=120), nullable=False),
        sa.Column("provider_endpoint", sa.String(length=1000), nullable=False),
        sa.Column("commercial_rights_state", sa.String(length=80), nullable=False),
        sa.Column("provider_maximum_cost", sa.String(length=48), nullable=False),
        sa.Column("customer_price", sa.String(length=48), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("failure_class", sa.String(length=96), nullable=True),
        sa.Column("outbound_attempts", sa.Integer(), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_digest", sa.String(length=71), nullable=True),
        sa.Column("normalized_result", sa.JSON(), nullable=True),
        sa.Column("verification_state", sa.String(length=32), nullable=False),
        sa.Column("verification_method", sa.String(length=120), nullable=False),
        sa.Column("capability_verified", sa.Boolean(), nullable=False),
        sa.Column("useful_outcome", sa.Boolean(), nullable=False),
        sa.Column("usefulness_evidence", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "requester_agent_id",
            "idempotency_key",
            name="uq_official_data_execution_requester_idempotency",
        ),
        sa.UniqueConstraint(
            "execution_id", name="uq_official_data_execution_id"
        ),
        sa.CheckConstraint(
            "capability = 'world_bank.population.latest'",
            name="ck_official_data_execution_capability",
        ),
        sa.CheckConstraint(
            "provider_identifier = 'world_bank_wdi'",
            name="ck_official_data_execution_provider",
        ),
        sa.CheckConstraint(
            "provider_maximum_cost = '0' AND customer_price = '0' AND currency = 'USD'",
            name="ck_official_data_execution_zero_cost",
        ),
        sa.CheckConstraint(
            "state IN ('claimed', 'completed', 'failed')",
            name="ck_official_data_execution_state",
        ),
        sa.CheckConstraint(
            "verification_state IN ('not_performed', 'verified', 'failed')",
            name="ck_official_data_execution_verification_state",
        ),
        sa.CheckConstraint(
            "outbound_attempts >= 0 AND outbound_attempts <= 1",
            name="ck_official_data_execution_attempts",
        ),
        sa.CheckConstraint(
            "state != 'completed' OR (capability_verified = true AND "
            "verification_state = 'verified' AND response_digest IS NOT NULL "
            "AND normalized_result IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_official_data_execution_completed_evidence",
        ),
        sa.CheckConstraint(
            "useful_outcome = false OR (state = 'completed' AND capability_verified = true "
            "AND usefulness_evidence IS NOT NULL AND acknowledged_at IS NOT NULL)",
            name="ck_official_data_execution_useful_evidence",
        ),
    )
    op.create_index(
        "ix_official_data_execution_requester_created",
        "official_data_executions",
        ["requester_agent_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_official_data_execution_requester_created",
        table_name="official_data_executions",
    )
    op.drop_table("official_data_executions")
