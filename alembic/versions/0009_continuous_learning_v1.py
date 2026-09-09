"""add bounded continuous learning and evidence intake v1

Revision ID: 0009_continuous_learning_v1
Revises: 0008_action_outcome_evidence
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_continuous_learning_v1"
down_revision = "0008_action_outcome_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "learning_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("trigger", sa.String(40), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sources_considered", sa.Integer(), nullable=False),
        sa.Column("outbound_attempts", sa.Integer(), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("paid_external_spend_permitted", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.CheckConstraint("sources_considered >= 0", name="ck_learning_runs_sources_nonnegative"),
        sa.CheckConstraint("outbound_attempts >= 0", name="ck_learning_runs_attempts_nonnegative"),
        sa.CheckConstraint("response_bytes >= 0", name="ck_learning_runs_bytes_nonnegative"),
        sa.CheckConstraint("paid_external_spend_permitted = false", name="ck_learning_runs_paid_spend_disabled_v1"),
        sa.UniqueConstraint("run_id", name="uq_learning_runs_run_id"),
    )

    op.create_table(
        "learning_source_watch_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observation_id", sa.String(160), nullable=True),
        sa.Column("last_material_change_observation_id", sa.String(160), nullable=True),
        sa.Column("next_eligible_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("circuit_open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_class", sa.String(64), nullable=True),
        sa.Column("outbound_attempts_total", sa.Integer(), nullable=False),
        sa.Column("response_bytes_total", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(36), nullable=True),
        sa.Column("claim_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("consecutive_failures >= 0", name="ck_learning_watch_failures_nonnegative"),
        sa.CheckConstraint("outbound_attempts_total >= 0", name="ck_learning_watch_attempts_nonnegative"),
        sa.CheckConstraint("response_bytes_total >= 0", name="ck_learning_watch_bytes_nonnegative"),
        sa.ForeignKeyConstraint(["source_id"], ["live_utility_sources.source_id"], ondelete="CASCADE", name="fk_learning_watch_source"),
        sa.ForeignKeyConstraint(["last_observation_id"], ["live_utility_observations.observation_id"], ondelete="RESTRICT", name="fk_learning_watch_last_observation"),
        sa.ForeignKeyConstraint(["last_material_change_observation_id"], ["live_utility_observations.observation_id"], ondelete="RESTRICT", name="fk_learning_watch_last_change"),
        sa.UniqueConstraint("source_id", name="uq_learning_source_watch_states_source"),
    )

    op.create_table(
        "agent_evidence_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("claim_id", sa.String(36), nullable=False),
        sa.Column("requester_agent_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("evidence_digest", sa.String(71), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("subject_key", sa.String(120), nullable=False),
        sa.Column("description", sa.String(2000), nullable=False),
        sa.Column("reference_url", sa.String(1000), nullable=True),
        sa.Column("provider_identifier", sa.String(240), nullable=True),
        sa.Column("protocol", sa.String(40), nullable=True),
        sa.Column("failure_class", sa.String(64), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(40), nullable=False),
        sa.Column("corroborating_agent_count", sa.Integer(), nullable=False),
        sa.Column("supporting_references", sa.JSON(), nullable=True),
        sa.CheckConstraint("corroborating_agent_count >= 1", name="ck_agent_evidence_corroboration_positive"),
        sa.ForeignKeyConstraint(["requester_agent_id"], ["agents.id"], ondelete="CASCADE", name="fk_agent_evidence_requester"),
        sa.UniqueConstraint("claim_id", name="uq_agent_evidence_claims_claim_id"),
        sa.UniqueConstraint("requester_agent_id", "idempotency_key", name="uq_agent_evidence_claims_requester_idempotency"),
        sa.UniqueConstraint("requester_agent_id", "evidence_digest", name="uq_agent_evidence_claims_requester_material"),
    )
    op.create_index("ix_agent_evidence_claims_requester_agent_id", "agent_evidence_claims", ["requester_agent_id"])
    op.create_index("ix_agent_evidence_digest_state", "agent_evidence_claims", ["evidence_digest", "state"])
    op.create_index("ix_agent_evidence_category_submitted", "agent_evidence_claims", ["category", "submitted_at"])

    op.create_table(
        "learning_opportunity_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_key", sa.String(71), nullable=False),
        sa.Column("normalized_demand_key", sa.String(120), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_meaningful_signals", sa.Integer(), nullable=False),
        sa.Column("distinct_requester_count", sa.Integer(), nullable=False),
        sa.Column("repeat_requester_count", sa.Integer(), nullable=False),
        sa.Column("anonymous_signal_count", sa.Integer(), nullable=False),
        sa.Column("failure_class_breakdown", sa.JSON(), nullable=False),
        sa.Column("operational_failure_breakdown", sa.JSON(), nullable=False),
        sa.Column("supporting_evidence_references", sa.JSON(), nullable=False),
        sa.Column("evidence_state", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("priority_score", sa.Integer(), nullable=False),
        sa.Column("known_provider_availability", sa.String(40), nullable=True),
        sa.Column("payment_potential", sa.String(40), nullable=True),
        sa.Column("known_cost", sa.String(64), nullable=True),
        sa.Column("margin_feasibility", sa.String(40), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("total_meaningful_signals >= 0", name="ck_learning_opportunities_signals_nonnegative"),
        sa.CheckConstraint("distinct_requester_count >= 0", name="ck_learning_opportunities_requesters_nonnegative"),
        sa.CheckConstraint("repeat_requester_count >= 0", name="ck_learning_opportunities_repeats_nonnegative"),
        sa.CheckConstraint("anonymous_signal_count >= 0", name="ck_learning_opportunities_anonymous_nonnegative"),
        sa.UniqueConstraint("candidate_key", name="uq_learning_opportunities_candidate_key"),
    )
    op.create_index("ix_learning_opportunity_candidates_normalized_demand_key", "learning_opportunity_candidates", ["normalized_demand_key"])
    op.create_index("ix_learning_opportunities_priority", "learning_opportunity_candidates", ["priority_score", "last_seen_at"])


def downgrade():
    op.drop_index("ix_learning_opportunities_priority", table_name="learning_opportunity_candidates")
    op.drop_index("ix_learning_opportunity_candidates_normalized_demand_key", table_name="learning_opportunity_candidates")
    op.drop_table("learning_opportunity_candidates")
    op.drop_index("ix_agent_evidence_category_submitted", table_name="agent_evidence_claims")
    op.drop_index("ix_agent_evidence_digest_state", table_name="agent_evidence_claims")
    op.drop_index("ix_agent_evidence_claims_requester_agent_id", table_name="agent_evidence_claims")
    op.drop_table("agent_evidence_claims")
    op.drop_table("learning_source_watch_states")
    op.drop_table("learning_runs")
