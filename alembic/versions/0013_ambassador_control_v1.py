"""add Ambassador Operator Control V1 audit evidence

Revision ID: 0013_ambassador_control_v1
Revises: 0012_ambassador_pilot_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_ambassador_control_v1"
down_revision = "0012_ambassador_pilot_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ambassador_operator_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.String(36), nullable=False),
        sa.Column("operation_kind", sa.String(32), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_digest", sa.String(71), nullable=False),
        sa.Column("result_class", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation_kind IN ('create_campaign', 'scout_campaign', 'qualify_target', "
            "'set_campaign_state', 'suppress_target', 'contact_target')",
            name="ck_ambassador_operator_action_kind",
        ),
        sa.CheckConstraint(
            "result_class IN ('claimed', 'succeeded', 'rejected', 'ambiguous', 'failed')",
            name="ck_ambassador_operator_action_result",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["ambassador_campaigns.id"],
            ondelete="RESTRICT", name="fk_ambassador_operator_action_campaign",
        ),
        sa.ForeignKeyConstraint(
            ["target_id"], ["ambassador_targets.id"],
            ondelete="RESTRICT", name="fk_ambassador_operator_action_target",
        ),
        sa.UniqueConstraint("action_id", name="uq_ambassador_operator_action_id"),
        sa.UniqueConstraint(
            "operation_kind", "idempotency_key",
            name="uq_ambassador_operator_action_idempotency",
        ),
    )
    op.create_index(
        "ix_ambassador_operator_actions_created_at",
        "ambassador_operator_actions",
        ["created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_ambassador_operator_actions_created_at",
        table_name="ambassador_operator_actions",
    )
    op.drop_table("ambassador_operator_actions")
