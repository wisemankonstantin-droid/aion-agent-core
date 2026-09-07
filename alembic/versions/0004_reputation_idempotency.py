"""make reputation events idempotent at the database layer

Revision ID: 0004_reputation_idempotency
Revises: 0003_activation_funnel
"""
from alembic import op

revision = "0004_reputation_idempotency"
down_revision = "0003_activation_funnel"
branch_labels = None
depends_on = None


def upgrade():
    # Keep the earliest copy if an older deployment somehow accumulated duplicates.
    op.execute(
        "DELETE FROM reputation_events "
        "WHERE id NOT IN (SELECT MIN(id) FROM reputation_events GROUP BY agent_id, reason)"
    )
    op.create_index(
        "uq_reputation_events_agent_reason",
        "reputation_events",
        ["agent_id", "reason"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_reputation_events_agent_reason", table_name="reputation_events")
