"""persist normalized Live Utility observation state

Revision ID: 0006_live_utility_data
Revises: 0005_live_utility_persistence
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_live_utility_data"
down_revision = "0005_live_utility_persistence"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "live_utility_observations",
        sa.Column("normalized_data", sa.JSON(), nullable=True),
    )
    op.create_table(
        "live_utility_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("verification_id", sa.String(160), nullable=False),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("subject_key", sa.String(240), nullable=False),
        sa.Column("observation_id", sa.String(160), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_method", sa.String(160), nullable=False),
        sa.Column("content_digest", sa.String(240), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["live_utility_sources.source_id"],
            ondelete="RESTRICT",
            name="fk_live_utility_verifications_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["live_utility_observations.observation_id"],
            ondelete="RESTRICT",
            name="fk_live_utility_verifications_observation_id",
        ),
        sa.CheckConstraint(
            "valid_from <= stale_after",
            name="ck_live_utility_verifications_valid_stale_order",
        ),
        sa.CheckConstraint(
            "stale_after <= expires_at",
            name="ck_live_utility_verifications_stale_expires_order",
        ),
        sa.UniqueConstraint(
            "verification_id",
            name="uq_live_utility_verifications_verification_id",
        ),
    )
    op.create_index(
        "ix_live_utility_verifications_source_subject_verified",
        "live_utility_verifications",
        ["source_id", "subject_key", "verified_at"],
    )


def downgrade():
    op.drop_index(
        "ix_live_utility_verifications_source_subject_verified",
        table_name="live_utility_verifications",
    )
    op.drop_table("live_utility_verifications")
    op.drop_column("live_utility_observations", "normalized_data")
