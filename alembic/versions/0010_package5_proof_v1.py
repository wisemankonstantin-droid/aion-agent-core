"""add Package 5 independent participation and VUO proof v1

Revision ID: 0010_package5_proof_v1
Revises: 0009_continuous_learning_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_package5_proof_v1"
down_revision = "0009_continuous_learning_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "package5_participation_assessments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("canonical_agent_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("assessment_digest", sa.String(71), nullable=False),
        sa.Column("classification", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("evidence_authority", sa.String(64), nullable=False),
        sa.Column("evidence_reference_digest", sa.String(71), nullable=False),
        sa.Column("evidence_summary_digest", sa.String(71), nullable=False),
        sa.Column("release_sha", sa.String(40), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "classification IN ('aion_operated_internal', 'synthetic_probe_test', "
            "'coordinated_design_partner', 'operator_invited_coordinated_test', "
            "'independent_external_candidate', 'independent_external_countable')",
            name="ck_package5_participation_classification",
        ),
        sa.CheckConstraint(
            "evidence_authority = 'operator_reviewed_evidence'",
            name="ck_package5_participation_operator_authority",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_agent_id"], ["agents.id"], ondelete="RESTRICT",
            name="fk_package5_participation_agent",
        ),
        sa.UniqueConstraint("assessment_id", name="uq_package5_participation_assessment_id"),
        sa.UniqueConstraint(
            "canonical_agent_id", "idempotency_key",
            name="uq_package5_participation_agent_idempotency",
        ),
    )
    op.create_index(
        "ix_package5_participation_agent_assessed",
        "package5_participation_assessments",
        ["canonical_agent_id", "assessed_at"],
    )

    op.create_table(
        "package5_vuo_proofs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vuo_id", sa.String(36), nullable=False),
        sa.Column("canonical_requester_agent_id", sa.Integer(), nullable=False),
        sa.Column("requester_agent_id", sa.Integer(), nullable=False),
        sa.Column("action_run_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("goal_kind", sa.String(80), nullable=False),
        sa.Column("product_goal", sa.String(500), nullable=False),
        sa.Column("delivered_outcome", sa.String(1000), nullable=False),
        sa.Column("outcome_verification_state", sa.String(40), nullable=False),
        sa.Column("outcome_verification_method", sa.String(80), nullable=False),
        sa.Column("usefulness_state", sa.String(40), nullable=False),
        sa.Column("usefulness_method", sa.String(80), nullable=False),
        sa.Column("usefulness_evidence", sa.String(500), nullable=False),
        sa.Column("semantic_eligible", sa.Boolean(), nullable=False),
        sa.Column("eligibility_reason_code", sa.String(96), nullable=False),
        sa.Column("participation_assessment_id", sa.Integer(), nullable=True),
        sa.Column("participation_classification_at_submission", sa.String(64), nullable=False),
        sa.Column("participation_reason_at_submission", sa.String(96), nullable=False),
        sa.Column("cost_state", sa.String(32), nullable=False),
        sa.Column("cost_amount", sa.String(64), nullable=True),
        sa.Column("cost_currency", sa.String(16), nullable=True),
        sa.Column("release_sha", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "goal_kind = 'verify_external_agent_callability'",
            name="ck_package5_vuo_goal_kind_v1",
        ),
        sa.CheckConstraint(
            "product_goal = 'find_verify_invoke_external_a2a_agent'",
            name="ck_package5_vuo_product_goal_v1",
        ),
        sa.CheckConstraint(
            "delivered_outcome = 'verified_external_agent_callability'",
            name="ck_package5_vuo_delivered_outcome_v1",
        ),
        sa.CheckConstraint(
            "usefulness_state = 'requester_confirmed'",
            name="ck_package5_vuo_usefulness_state_v1",
        ),
        sa.CheckConstraint(
            "usefulness_method = 'authenticated_requester_attestation'",
            name="ck_package5_vuo_usefulness_method_v1",
        ),
        sa.CheckConstraint(
            "usefulness_evidence = 'requester_confirms_goal_was_useful'",
            name="ck_package5_vuo_usefulness_evidence_v1",
        ),
        sa.CheckConstraint(
            "participation_classification_at_submission IN "
            "('unknown_not_proven', 'aion_operated_internal', 'synthetic_probe_test', "
            "'coordinated_design_partner', 'operator_invited_coordinated_test', "
            "'independent_external_candidate', 'independent_external_countable')",
            name="ck_package5_vuo_submission_classification",
        ),
        sa.CheckConstraint(
            "participation_classification_at_submission != 'independent_external_countable' "
            "OR participation_assessment_id IS NOT NULL",
            name="ck_package5_vuo_countable_has_assessment",
        ),
        sa.CheckConstraint(
            "cost_state IN ('unknown', 'known_zero', 'known_nonzero')",
            name="ck_package5_vuo_cost_state",
        ),
        sa.CheckConstraint(
            "(cost_state = 'unknown' AND cost_amount IS NULL AND cost_currency IS NULL) OR "
            "(cost_state IN ('known_zero', 'known_nonzero') AND cost_amount IS NOT NULL "
            "AND cost_currency IS NOT NULL)",
            name="ck_package5_vuo_cost_material",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_requester_agent_id"], ["agents.id"], ondelete="RESTRICT",
            name="fk_package5_vuo_canonical_requester",
        ),
        sa.ForeignKeyConstraint(
            ["requester_agent_id"], ["agents.id"], ondelete="RESTRICT",
            name="fk_package5_vuo_requester",
        ),
        sa.ForeignKeyConstraint(
            ["action_run_id"], ["action_runs.id"], ondelete="RESTRICT",
            name="fk_package5_vuo_action_run",
        ),
        sa.ForeignKeyConstraint(
            ["participation_assessment_id"], ["package5_participation_assessments.id"],
            ondelete="RESTRICT", name="fk_package5_vuo_participation_assessment",
        ),
        sa.UniqueConstraint("vuo_id", name="uq_package5_vuo_id"),
        sa.UniqueConstraint("action_run_id", name="uq_package5_vuo_action_run"),
        sa.UniqueConstraint(
            "canonical_requester_agent_id", "idempotency_key",
            name="uq_package5_vuo_requester_idempotency",
        ),
    )
    op.create_index(
        "ix_package5_vuo_requester_created",
        "package5_vuo_proofs",
        ["canonical_requester_agent_id", "created_at"],
    )


def downgrade():
    op.drop_index("ix_package5_vuo_requester_created", table_name="package5_vuo_proofs")
    op.drop_table("package5_vuo_proofs")
    op.drop_index(
        "ix_package5_participation_agent_assessed",
        table_name="package5_participation_assessments",
    )
    op.drop_table("package5_participation_assessments")
