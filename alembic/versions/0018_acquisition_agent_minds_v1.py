"""Durable per-worker AI acquisition mind state.

Revision ID: 0018_acquisition_agent_minds_v1
Revises: 0017_first_sat_accounting_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_acquisition_agent_minds_v1"
down_revision = "0017_first_sat_accounting_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "acquisition_agent_minds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.String(length=80), nullable=False),
        sa.Column("mind_version", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("cognitive_profile", sa.JSON(), nullable=False),
        sa.Column("safe_memory", sa.JSON(), nullable=False),
        sa.Column("last_plan", sa.JSON(), nullable=True),
        sa.Column("last_observation_digest", sa.String(length=71), nullable=True),
        sa.Column("last_plan_digest", sa.String(length=71), nullable=True),
        sa.Column("last_state", sa.String(length=32), nullable=False),
        sa.Column("total_reasoning_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reasoning_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reasoned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("worker_id", name="uq_acquisition_agent_minds_worker"),
        sa.CheckConstraint(
            "total_reasoning_calls >= 0",
            name="ck_acquisition_agent_minds_calls_nonnegative",
        ),
        sa.CheckConstraint(
            "reasoning_failures >= 0",
            name="ck_acquisition_agent_minds_failures_nonnegative",
        ),
    )
    op.create_index(
        "ix_acquisition_agent_minds_state",
        "acquisition_agent_minds",
        ["last_state", "updated_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_acquisition_agent_minds_state",
        table_name="acquisition_agent_minds",
    )
    op.drop_table("acquisition_agent_minds")
