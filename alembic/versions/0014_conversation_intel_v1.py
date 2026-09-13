"""Package 5F conversation intelligence V1.

Revision ID: 0014_conversation_intel_v1
Revises: 0013_ambassador_control_v1
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_conversation_intel_v1"
down_revision = "0013_ambassador_control_v1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "conversation_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("ambassador_contact_id", sa.Integer(), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_class", sa.String(length=40), nullable=False),
        sa.Column("capture_class", sa.String(length=32), nullable=False),
        sa.Column("protocol", sa.String(length=40), nullable=False),
        sa.Column("protocol_context_digest", sa.String(length=71), nullable=True),
        sa.Column("protocol_task_digest", sa.String(length=71), nullable=True),
        sa.Column("protocol_message_digest", sa.String(length=71), nullable=True),
        sa.Column("safe_evidence", sa.JSON(), nullable=True),
        sa.Column("redaction_summary", sa.JSON(), nullable=False),
        sa.Column("evidence_bytes", sa.Integer(), nullable=False),
        sa.Column("evidence_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ambassador_contact_id"], ["ambassador_contact_attempts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("conversation_id", name="uq_conversation_evidence_conversation_id"),
        sa.UniqueConstraint("ambassador_contact_id", name="uq_conversation_evidence_contact"),
        sa.CheckConstraint(
            "capture_class IN ('structured_only', 'text_evidence', 'redacted_all')",
            name="ck_conversation_evidence_capture_class",
        ),
        sa.CheckConstraint("evidence_bytes >= 0 AND evidence_bytes <= 2048", name="ck_conversation_evidence_bytes"),
        sa.CheckConstraint("evidence_purged_at IS NULL OR evidence_purged_at >= captured_at", name="ck_conversation_evidence_purge_order"),
        sa.CheckConstraint("evidence_expires_at >= captured_at", name="ck_conversation_evidence_expiry_order"),
    )
    op.create_index("ix_conversation_evidence_captured_at", "conversation_evidence", ["captured_at"])
    op.create_index("ix_conversation_evidence_expires_at", "conversation_evidence", ["evidence_expires_at"])
    op.create_table(
        "conversation_intelligence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("intelligence_id", sa.String(length=36), nullable=False),
        sa.Column("conversation_evidence_id", sa.Integer(), nullable=False),
        sa.Column("analysis_method", sa.String(length=40), nullable=False),
        sa.Column("analysis_version", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("explicit_signals", sa.JSON(), nullable=False),
        sa.Column("inferred_signals", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_evidence_id"], ["conversation_evidence.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("intelligence_id", name="uq_conversation_intelligence_id"),
        sa.UniqueConstraint("conversation_evidence_id", "analysis_version", name="uq_conversation_intelligence_evidence_version"),
    )
    op.create_index("ix_conversation_intelligence_created_at", "conversation_intelligence", ["created_at"])


def downgrade():
    op.drop_index("ix_conversation_intelligence_created_at", table_name="conversation_intelligence")
    op.drop_table("conversation_intelligence")
    op.drop_index("ix_conversation_evidence_expires_at", table_name="conversation_evidence")
    op.drop_index("ix_conversation_evidence_captured_at", table_name="conversation_evidence")
    op.drop_table("conversation_evidence")
