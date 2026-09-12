"""add Package 5D Ambassador pilot v1

Revision ID: 0012_ambassador_pilot_v1
Revises: 0011_economic_kernel_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_ambassador_pilot_v1"
down_revision = "0011_economic_kernel_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ambassador_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("purpose", sa.String(500), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("maximum_targets", sa.Integer(), nullable=False),
        sa.Column("maximum_contacts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('draft', 'ready', 'paused', 'closed')", name="ck_ambassador_campaign_state"),
        sa.CheckConstraint("maximum_targets > 0 AND maximum_targets <= 30", name="ck_ambassador_campaign_target_limit"),
        sa.CheckConstraint("maximum_contacts >= 0 AND maximum_contacts <= maximum_targets", name="ck_ambassador_campaign_contact_limit"),
        sa.UniqueConstraint("campaign_id", name="uq_ambassador_campaign_id"),
    )
    op.create_table(
        "ambassador_targets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("discovery_source", sa.String(80), nullable=False),
        sa.Column("source_identifier", sa.String(240), nullable=False),
        sa.Column("agent_card_url", sa.String(1000), nullable=False),
        sa.Column("interaction_url", sa.String(1000), nullable=True),
        sa.Column("target_fingerprint", sa.String(71), nullable=False),
        sa.Column("metadata_digest", sa.String(71), nullable=False),
        sa.Column("prepared_message_digest", sa.String(71), nullable=True),
        sa.Column("manifest_reachable", sa.Boolean(), nullable=False),
        sa.Column("declared_a2a_v1_jsonrpc", sa.Boolean(), nullable=False),
        sa.Column("interaction_url_validated", sa.Boolean(), nullable=False),
        sa.Column("authentication_requirement", sa.String(32), nullable=False),
        sa.Column("payment_required", sa.Boolean(), nullable=False),
        sa.Column("qualification_state", sa.String(24), nullable=False),
        sa.Column("qualification_reasons", sa.JSON(), nullable=False),
        sa.Column("contact_state", sa.String(24), nullable=False),
        sa.Column("suppressed", sa.Boolean(), nullable=False),
        sa.Column("suppression_reason", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("qualification_state IN ('discovered', 'qualified', 'rejected')", name="ck_ambassador_target_qualification_state"),
        sa.CheckConstraint("contact_state IN ('not_ready', 'ready', 'claimed', 'contacted', 'response_received', 'blocked', 'ambiguous')", name="ck_ambassador_target_contact_state"),
        sa.ForeignKeyConstraint(["campaign_id"], ["ambassador_campaigns.id"], ondelete="RESTRICT", name="fk_ambassador_target_campaign"),
        sa.UniqueConstraint("target_id", name="uq_ambassador_target_id"),
        sa.UniqueConstraint("target_fingerprint", name="uq_ambassador_target_fingerprint"),
        sa.UniqueConstraint("campaign_id", "source_identifier", name="uq_ambassador_target_campaign_source"),
    )
    op.create_index("ix_ambassador_targets_campaign_state", "ambassador_targets", ["campaign_id", "qualification_state", "contact_state"])
    op.create_table(
        "ambassador_contact_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.String(36), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("outbound_request_digest", sa.String(71), nullable=False),
        sa.Column("result_class", sa.String(32), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_digest", sa.String(71), nullable=True),
        sa.Column("response_received", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("result_class IN ('claimed', 'dry_run', 'delivered', 'response_received', 'payment_required', 'credentials_required', 'rejected', 'ambiguous', 'transport_error')", name="ck_ambassador_contact_result_class"),
        sa.ForeignKeyConstraint(["target_id"], ["ambassador_targets.id"], ondelete="RESTRICT", name="fk_ambassador_contact_target"),
        sa.UniqueConstraint("contact_id", name="uq_ambassador_contact_id"),
        sa.UniqueConstraint("target_id", name="uq_ambassador_contact_target_once"),
        sa.UniqueConstraint("target_id", "idempotency_key", name="uq_ambassador_contact_target_idempotency"),
    )
    op.create_table(
        "distribution_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_id", sa.String(36), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("referrer_agent_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("maximum_uses", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("kind IN ('ambassador_invite', 'peer_referral')", name="ck_distribution_token_kind"),
        sa.CheckConstraint("maximum_uses > 0 AND maximum_uses <= 5", name="ck_distribution_token_use_limit"),
        sa.CheckConstraint("use_count >= 0 AND use_count <= maximum_uses", name="ck_distribution_token_use_count"),
        sa.CheckConstraint("(kind = 'ambassador_invite' AND maximum_uses = 1 AND target_id IS NOT NULL AND referrer_agent_id IS NULL) OR (kind = 'peer_referral' AND target_id IS NULL AND referrer_agent_id IS NOT NULL)", name="ck_distribution_token_provenance"),
        sa.ForeignKeyConstraint(["campaign_id"], ["ambassador_campaigns.id"], ondelete="RESTRICT", name="fk_distribution_token_campaign"),
        sa.ForeignKeyConstraint(["target_id"], ["ambassador_targets.id"], ondelete="RESTRICT", name="fk_distribution_token_target"),
        sa.ForeignKeyConstraint(["referrer_agent_id"], ["agents.id"], ondelete="RESTRICT", name="fk_distribution_token_referrer"),
        sa.UniqueConstraint("token_id", name="uq_distribution_token_id"),
        sa.UniqueConstraint("token_digest", name="uq_distribution_token_digest"),
        sa.UniqueConstraint("target_id", "kind", name="uq_distribution_token_target_kind"),
        sa.UniqueConstraint("referrer_agent_id", "idempotency_key", name="uq_distribution_token_referrer_idempotency"),
    )
    op.create_table(
        "distribution_join_attributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("token_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("referrer_agent_id", sa.Integer(), nullable=True),
        sa.Column("trusted_acquisition_source", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('ambassador_invite', 'peer_referral')", name="ck_distribution_join_kind"),
        sa.CheckConstraint("trusted_acquisition_source IN ('aion_ambassador_outbound', 'trusted_peer_referral')", name="ck_distribution_join_source"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT", name="fk_distribution_join_agent"),
        sa.ForeignKeyConstraint(["token_id"], ["distribution_tokens.id"], ondelete="RESTRICT", name="fk_distribution_join_token"),
        sa.ForeignKeyConstraint(["campaign_id"], ["ambassador_campaigns.id"], ondelete="RESTRICT", name="fk_distribution_join_campaign"),
        sa.ForeignKeyConstraint(["target_id"], ["ambassador_targets.id"], ondelete="RESTRICT", name="fk_distribution_join_target"),
        sa.ForeignKeyConstraint(["referrer_agent_id"], ["agents.id"], ondelete="RESTRICT", name="fk_distribution_join_referrer"),
        sa.UniqueConstraint("agent_id", name="uq_distribution_join_agent"),
    )


def downgrade():
    op.drop_table("distribution_join_attributions")
    op.drop_table("distribution_tokens")
    op.drop_table("ambassador_contact_attempts")
    op.drop_index("ix_ambassador_targets_campaign_state", table_name="ambassador_targets")
    op.drop_table("ambassador_targets")
    op.drop_table("ambassador_campaigns")
