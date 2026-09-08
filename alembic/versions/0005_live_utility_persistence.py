"""add durable Live Utility Phase 1 persistence

Revision ID: 0005_live_utility_persistence
Revises: 0004_reputation_idempotency
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_live_utility_persistence"
down_revision = "0004_reputation_idempotency"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "live_utility_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("source_kind", sa.String(80), nullable=False),
        sa.Column("canonical_locator", sa.String(1000), nullable=False),
        sa.Column("refresh_strategies", sa.JSON(), nullable=False),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False),
        sa.Column("expires_after_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "tier IN ('tier_1', 'tier_2', 'tier_3')",
            name="ck_live_utility_sources_tier",
        ),
        sa.CheckConstraint(
            "stale_after_seconds > 0",
            name="ck_live_utility_sources_stale_positive",
        ),
        sa.CheckConstraint(
            "expires_after_seconds > 0",
            name="ck_live_utility_sources_expires_positive",
        ),
        sa.CheckConstraint(
            "expires_after_seconds >= stale_after_seconds",
            name="ck_live_utility_sources_window_order",
        ),
    )
    op.create_index(
        "ix_live_utility_sources_source_id",
        "live_utility_sources",
        ["source_id"],
        unique=True,
    )

    op.create_table(
        "live_utility_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.String(160), nullable=False),
        sa.Column("source_id", sa.String(160), nullable=False),
        sa.Column("subject_key", sa.String(240), nullable=False),
        sa.Column("source_revision", sa.String(240), nullable=True),
        sa.Column("previous_observation_id", sa.String(160), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stale_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_method", sa.String(160), nullable=True),
        sa.Column("content_digest", sa.String(240), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["live_utility_sources.source_id"],
            ondelete="RESTRICT",
            name="fk_live_utility_observations_source_id",
        ),
        sa.ForeignKeyConstraint(
            ["previous_observation_id"],
            ["live_utility_observations.observation_id"],
            ondelete="RESTRICT",
            name="fk_live_utility_observations_previous_id",
        ),
        sa.CheckConstraint(
            "valid_from <= stale_after",
            name="ck_live_utility_observations_valid_stale_order",
        ),
        sa.CheckConstraint(
            "stale_after <= expires_at",
            name="ck_live_utility_observations_stale_expires_order",
        ),
        sa.CheckConstraint(
            "verified_at IS NULL OR verified_at >= observed_at",
            name="ck_live_utility_observations_verified_order",
        ),
        sa.CheckConstraint(
            "previous_observation_id IS NULL OR previous_observation_id != observation_id",
            name="ck_live_utility_observations_not_self_referential",
        ),
    )
    op.create_index(
        "ix_live_utility_observations_observation_id",
        "live_utility_observations",
        ["observation_id"],
        unique=True,
    )
    op.create_index(
        "ix_live_utility_observations_source_id",
        "live_utility_observations",
        ["source_id"],
    )
    op.create_index(
        "ix_live_utility_observations_source_subject_observed",
        "live_utility_observations",
        ["source_id", "subject_key", "observed_at"],
    )


def downgrade():
    op.drop_index(
        "ix_live_utility_observations_source_subject_observed",
        table_name="live_utility_observations",
    )
    op.drop_index(
        "ix_live_utility_observations_source_id",
        table_name="live_utility_observations",
    )
    op.drop_index(
        "ix_live_utility_observations_observation_id",
        table_name="live_utility_observations",
    )
    op.drop_table("live_utility_observations")
    op.drop_index(
        "ix_live_utility_sources_source_id",
        table_name="live_utility_sources",
    )
    op.drop_table("live_utility_sources")
