"""add Package 3 action and verified outcome evidence

Revision ID: 0008_action_outcome_evidence
Revises: 0007_agent_utility_checkpoints
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_action_outcome_evidence"
down_revision = "0007_agent_utility_checkpoints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "action_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.String(36), nullable=False),
        sa.Column("requester_agent_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("requested_query", sa.String(128), nullable=False),
        sa.Column("requested_candidate_identifier", sa.String(240), nullable=True),
        sa.Column("authorize_external_contact", sa.Boolean(), nullable=False),
        sa.Column("selected_provider_identifier", sa.String(240), nullable=True),
        sa.Column("source_id", sa.String(160), nullable=True),
        sa.Column("agent_card_url", sa.String(1000), nullable=True),
        sa.Column("interaction_url", sa.String(1000), nullable=True),
        sa.Column("discovery_evidence", sa.JSON(), nullable=True),
        sa.Column("protocol_binding", sa.String(40), nullable=True),
        sa.Column("protocol_version", sa.String(40), nullable=True),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("failure_class", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("discovery_attempt_count", sa.Integer(), nullable=False),
        sa.Column("action_attempt_count", sa.Integer(), nullable=False),
        sa.Column("request_bytes", sa.Integer(), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column("cost_amount", sa.String(64), nullable=True),
        sa.Column("cost_currency", sa.String(16), nullable=True),
        sa.CheckConstraint(
            "action_attempt_count >= 0", name="ck_action_runs_attempts_nonnegative"
        ),
        sa.CheckConstraint(
            "discovery_attempt_count >= 0", name="ck_action_runs_discovery_nonnegative"
        ),
        sa.CheckConstraint(
            "request_bytes >= 0", name="ck_action_runs_request_bytes_nonnegative"
        ),
        sa.CheckConstraint(
            "response_bytes IS NULL OR response_bytes >= 0",
            name="ck_action_runs_response_bytes_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["requester_agent_id"],
            ["agents.id"],
            ondelete="CASCADE",
            name="fk_action_runs_requester_agent_id",
        ),
        sa.UniqueConstraint("action_id", name="uq_action_runs_action_id"),
        sa.UniqueConstraint(
            "requester_agent_id",
            "idempotency_key",
            name="uq_action_runs_requester_idempotency",
        ),
    )
    op.create_index(
        "ix_action_runs_requester_created",
        "action_runs",
        ["requester_agent_id", "created_at"],
    )

    op.create_table(
        "action_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_run_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("delivery_state", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_bytes", sa.Integer(), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("transport_error", sa.String(300), nullable=True),
        sa.Column("response_digest", sa.String(71), nullable=True),
        sa.Column("protocol_response_id", sa.String(128), nullable=True),
        sa.CheckConstraint(
            "attempt_number = 1", name="ck_action_attempts_one_post_v1"
        ),
        sa.CheckConstraint(
            "request_bytes >= 0", name="ck_action_attempts_request_bytes_nonnegative"
        ),
        sa.CheckConstraint(
            "response_bytes IS NULL OR response_bytes >= 0",
            name="ck_action_attempts_response_bytes_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["action_run_id"],
            ["action_runs.id"],
            ondelete="CASCADE",
            name="fk_action_attempts_action_run_id",
        ),
        sa.UniqueConstraint(
            "action_run_id", "attempt_number", name="uq_action_attempts_run_number"
        ),
    )
    op.create_index(
        "ix_action_attempts_action_run_id", "action_attempts", ["action_run_id"]
    )

    op.create_table(
        "action_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_run_id", sa.Integer(), nullable=False),
        sa.Column("outcome_type", sa.String(80), nullable=False),
        sa.Column("protocol_response_received", sa.Boolean(), nullable=False),
        sa.Column("callability_verified", sa.Boolean(), nullable=False),
        sa.Column("capability_verified", sa.Boolean(), nullable=False),
        sa.Column("verified_outcome", sa.Boolean(), nullable=False),
        sa.Column("normalized_result_kind", sa.String(40), nullable=True),
        sa.Column("failure_class", sa.String(64), nullable=True),
        sa.Column("response_digest", sa.String(71), nullable=True),
        sa.Column("protocol_task_id", sa.String(160), nullable=True),
        sa.Column("protocol_message_id", sa.String(160), nullable=True),
        sa.Column("proof_present", sa.Boolean(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_run_id"],
            ["action_runs.id"],
            ondelete="CASCADE",
            name="fk_action_outcomes_action_run_id",
        ),
        sa.UniqueConstraint("action_run_id", name="uq_action_outcomes_run"),
    )
    op.create_index(
        "ix_action_outcomes_action_run_id", "action_outcomes", ["action_run_id"]
    )

    op.create_table(
        "action_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_run_id", sa.Integer(), nullable=False),
        sa.Column("action_outcome_id", sa.Integer(), nullable=False),
        sa.Column("verification_method", sa.String(80), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("challenge_digest", sa.String(71), nullable=True),
        sa.Column("proof_digest", sa.String(71), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["action_run_id"],
            ["action_runs.id"],
            ondelete="CASCADE",
            name="fk_action_verifications_action_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["action_outcome_id"],
            ["action_outcomes.id"],
            ondelete="CASCADE",
            name="fk_action_verifications_action_outcome_id",
        ),
        sa.UniqueConstraint("action_run_id", name="uq_action_verifications_run"),
        sa.UniqueConstraint(
            "action_outcome_id", name="uq_action_verifications_outcome"
        ),
    )
    op.create_index(
        "ix_action_verifications_action_run_id",
        "action_verifications",
        ["action_run_id"],
    )


def downgrade():
    op.drop_index(
        "ix_action_verifications_action_run_id", table_name="action_verifications"
    )
    op.drop_table("action_verifications")
    op.drop_index("ix_action_outcomes_action_run_id", table_name="action_outcomes")
    op.drop_table("action_outcomes")
    op.drop_index("ix_action_attempts_action_run_id", table_name="action_attempts")
    op.drop_table("action_attempts")
    op.drop_index("ix_action_runs_requester_created", table_name="action_runs")
    op.drop_table("action_runs")
