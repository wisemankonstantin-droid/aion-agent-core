"""add durable Package 2 agent utility checkpoints

Revision ID: 0007_agent_utility_checkpoints
Revises: 0006_live_utility_data
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_agent_utility_checkpoints"
down_revision = "0006_live_utility_data"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_utility_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("subject_key", sa.String(240), nullable=False),
        sa.Column("observation_id", sa.String(160), nullable=True),
        sa.Column("source_revision", sa.String(240), nullable=True),
        sa.Column("freshness_state", sa.String(40), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agents.id"], ondelete="CASCADE",
            name="fk_agent_utility_checkpoints_agent_id",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"], ["live_utility_observations.observation_id"],
            ondelete="RESTRICT",
            name="fk_agent_utility_checkpoints_observation_id",
        ),
        sa.UniqueConstraint(
            "agent_id", "subject_key",
            name="uq_agent_utility_checkpoints_agent_subject",
        ),
    )
    op.create_index(
        "ix_agent_utility_checkpoints_agent_checked",
        "agent_utility_checkpoints",
        ["agent_id", "checked_at"],
    )


def downgrade():
    op.drop_index(
        "ix_agent_utility_checkpoints_agent_checked",
        table_name="agent_utility_checkpoints",
    )
    op.drop_table("agent_utility_checkpoints")
