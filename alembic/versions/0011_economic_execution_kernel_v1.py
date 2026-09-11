"""add Package 6A economic execution kernel v1

Revision ID: 0011_economic_execution_kernel_v1
Revises: 0010_package5_proof_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_economic_execution_kernel_v1"
down_revision = "0010_package5_proof_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "economic_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operation_id", sa.String(36), nullable=False),
        sa.Column("requester_agent_id", sa.Integer(), nullable=False),
        sa.Column("parent_economic_operation_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("product_sku", sa.String(120), nullable=False),
        sa.Column("currency", sa.String(16), nullable=False),
        sa.Column("customer_price", sa.String(48), nullable=False),
        sa.Column("expected_variable_cost", sa.String(48), nullable=False),
        sa.Column("maximum_variable_cost", sa.String(48), nullable=True),
        sa.Column("verification_cost", sa.String(48), nullable=False),
        sa.Column("payment_fee_allowance", sa.String(48), nullable=False),
        sa.Column("expected_total_cost", sa.String(48), nullable=False),
        sa.Column("maximum_total_spend", sa.String(48), nullable=True),
        sa.Column("contribution_amount", sa.String(48), nullable=False),
        sa.Column("expected_margin_bps", sa.Integer(), nullable=False),
        sa.Column("expected_cost_per_verified_outcome", sa.String(48), nullable=False),
        sa.Column("maximum_attempts", sa.Integer(), nullable=False),
        sa.Column("commercial_rights_state", sa.String(24), nullable=False),
        sa.Column("funding_required", sa.Boolean(), nullable=False),
        sa.Column("policy_eligible", sa.Boolean(), nullable=False),
        sa.Column("execution_eligible", sa.Boolean(), nullable=False),
        sa.Column("decision_reasons", sa.JSON(), nullable=False),
        sa.Column("adapter_state", sa.String(40), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("authorized_amount", sa.String(48), nullable=True),
        sa.Column("reserved_amount", sa.String(48), nullable=True),
        sa.Column("actual_cost", sa.String(48), nullable=True),
        sa.Column("settlement_amount", sa.String(48), nullable=True),
        sa.Column("released_amount", sa.String(48), nullable=True),
        sa.Column("action_run_id", sa.Integer(), nullable=True),
        sa.Column("release_sha", sa.String(40), nullable=True),
        sa.Column("quote_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("maximum_attempts > 0", name="ck_economic_operations_attempts_positive"),
        sa.CheckConstraint("expected_margin_bps >= 0 AND expected_margin_bps <= 10000", name="ck_economic_operations_margin_bps"),
        sa.CheckConstraint("commercial_rights_state IN ('allowed', 'unknown', 'prohibited')", name="ck_economic_operations_rights"),
        sa.CheckConstraint("state IN ('quoted', 'payment_authorized', 'funds_reserved', 'execution_started', 'outcome_verified', 'settlement_ready', 'settled', 'reserve_released', 'failed', 'cancelled')", name="ck_economic_operations_state"),
        sa.CheckConstraint("NOT funding_required OR NOT execution_eligible", name="ck_economic_operations_no_unfunded_execution"),
        sa.CheckConstraint("parent_economic_operation_id IS NULL OR parent_economic_operation_id <> id", name="ck_economic_operations_not_own_parent"),
        sa.CheckConstraint("state != 'payment_authorized' OR authorized_amount IS NOT NULL", name="ck_economic_operations_authorized_state_evidence"),
        sa.CheckConstraint("state != 'funds_reserved' OR (authorized_amount IS NOT NULL AND reserved_amount IS NOT NULL)", name="ck_economic_operations_reserved_state_evidence"),
        sa.CheckConstraint("state NOT IN ('execution_started', 'outcome_verified', 'settlement_ready', 'settled', 'reserve_released') OR NOT funding_required OR reserved_amount IS NOT NULL", name="ck_economic_operations_funded_execution_evidence"),
        sa.CheckConstraint("state NOT IN ('outcome_verified', 'settlement_ready', 'settled', 'reserve_released') OR action_run_id IS NOT NULL", name="ck_economic_operations_outcome_state_evidence"),
        sa.CheckConstraint("state NOT IN ('settlement_ready', 'settled', 'reserve_released') OR actual_cost IS NOT NULL", name="ck_economic_operations_cost_state_evidence"),
        sa.CheckConstraint("state NOT IN ('settled', 'reserve_released') OR settlement_amount IS NOT NULL", name="ck_economic_operations_settlement_state_evidence"),
        sa.CheckConstraint("state != 'reserve_released' OR released_amount IS NOT NULL", name="ck_economic_operations_release_state_evidence"),
        sa.ForeignKeyConstraint(["requester_agent_id"], ["agents.id"], ondelete="RESTRICT", name="fk_economic_operations_requester"),
        sa.ForeignKeyConstraint(["parent_economic_operation_id"], ["economic_operations.id"], ondelete="RESTRICT", name="fk_economic_operations_parent"),
        sa.ForeignKeyConstraint(["action_run_id"], ["action_runs.id"], ondelete="RESTRICT", name="fk_economic_operations_action"),
        sa.UniqueConstraint("operation_id", name="uq_economic_operations_operation_id"),
        sa.UniqueConstraint("requester_agent_id", "idempotency_key", name="uq_economic_operations_requester_idempotency"),
        sa.UniqueConstraint("action_run_id", name="uq_economic_operations_action_run"),
    )
    op.create_index("ix_economic_operations_requester_created", "economic_operations", ["requester_agent_id", "created_at"])
    op.create_table(
        "economic_transitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transition_id", sa.String(36), nullable=False),
        sa.Column("economic_operation_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("transition_digest", sa.String(71), nullable=False),
        sa.Column("from_state", sa.String(40), nullable=True),
        sa.Column("to_state", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("evidence_authority", sa.String(64), nullable=False),
        sa.Column("evidence_digest", sa.String(71), nullable=False),
        sa.Column("amount", sa.String(48), nullable=True),
        sa.Column("currency", sa.String(16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["economic_operation_id"], ["economic_operations.id"], ondelete="RESTRICT", name="fk_economic_transitions_operation"),
        sa.UniqueConstraint("transition_id", name="uq_economic_transitions_transition_id"),
        sa.UniqueConstraint("economic_operation_id", "sequence", name="uq_economic_transitions_operation_sequence"),
        sa.UniqueConstraint("economic_operation_id", "idempotency_key", name="uq_economic_transitions_operation_idempotency"),
    )
    op.create_index("ix_economic_transitions_operation_created", "economic_transitions", ["economic_operation_id", "created_at"])


def downgrade():
    op.drop_index("ix_economic_transitions_operation_created", table_name="economic_transitions")
    op.drop_table("economic_transitions")
    op.drop_index("ix_economic_operations_requester_created", table_name="economic_operations")
    op.drop_table("economic_operations")
