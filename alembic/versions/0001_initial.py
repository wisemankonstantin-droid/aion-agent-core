"""Initial AION schema

Revision ID: 0001_initial
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(160), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("endpoint", sa.String(500), nullable=True),
        sa.Column("protocol", sa.String(40), nullable=False),
        sa.Column("owner_required", sa.Boolean(), nullable=False),
        sa.Column("api_key_hash", sa.String(64), nullable=False),
        sa.Column("reputation", sa.Float(), nullable=False),
        sa.Column("trust_level", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agents_external_id", "agents", ["external_id"], unique=True)
    op.create_index("ix_agents_name", "agents", ["name"])
    op.create_index("ix_agents_api_key_hash", "agents", ["api_key_hash"], unique=True)

    op.create_table(
        "capabilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("verification", sa.String(40), nullable=False),
    )
    op.create_index("ix_capabilities_agent_id", "capabilities", ["agent_id"])
    op.create_index("ix_capabilities_name", "capabilities", ["name"])

    op.create_table(
        "needs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("capability", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_needs_agent_id", "needs", ["agent_id"])
    op.create_index("ix_needs_capability", "needs", ["capability"])

    op.create_table(
        "offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("capability", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_hint", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_offers_agent_id", "offers", ["agent_id"])
    op.create_index("ix_offers_capability", "offers", ["capability"])

    op.create_table(
        "interactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("requester_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("provider_agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("need_id", sa.Integer(), sa.ForeignKey("needs.id"), nullable=True),
        sa.Column("result", sa.String(40), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_interactions_requester_agent_id", "interactions", ["requester_agent_id"])
    op.create_index("ix_interactions_provider_agent_id", "interactions", ["provider_agent_id"])

    op.create_table(
        "reputation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(240), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_reputation_events_agent_id", "reputation_events", ["agent_id"])

    op.create_table(
        "payment_intents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("purpose", sa.String(120), nullable=False),
        sa.Column("amount", sa.String(120), nullable=False),
        sa.Column("protocol", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_payment_intents_agent_id", "payment_intents", ["agent_id"])


def downgrade():
    op.drop_table("payment_intents")
    op.drop_table("reputation_events")
    op.drop_table("interactions")
    op.drop_table("offers")
    op.drop_table("needs")
    op.drop_table("capabilities")
    op.drop_table("agents")
