"""add activation funnel telemetry

Revision ID: 0003_activation_funnel
Revises: 0002_acquisition_attribution
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_activation_funnel"
down_revision = "0002_acquisition_attribution"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("last_seen_at", sa.DateTime(), nullable=True))
    op.add_column("agents", sa.Column("first_useful_action_at", sa.DateTime(), nullable=True))
    op.add_column("agents", sa.Column("authenticated_calls", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "machine_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_machine_entries_source", "machine_entries", ["source"])


def downgrade():
    op.drop_index("ix_machine_entries_source", table_name="machine_entries")
    op.drop_table("machine_entries")
    op.drop_column("agents", "authenticated_calls")
    op.drop_column("agents", "first_useful_action_at")
    op.drop_column("agents", "last_seen_at")
