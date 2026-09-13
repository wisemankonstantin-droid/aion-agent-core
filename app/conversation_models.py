"""Package 5F durable, truth-separated conversation evidence and interpretation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class ConversationEvidence(Base):
    __tablename__ = "conversation_evidence"
    __table_args__ = (
        CheckConstraint(
            "capture_class IN ('structured_only', 'digest_only')",
            name="ck_conversation_evidence_capture_class",
        ),
        CheckConstraint("evidence_bytes = 0", name="ck_conversation_evidence_no_text_bytes"),
        CheckConstraint(
            "evidence_purged_at IS NULL OR evidence_purged_at >= captured_at",
            name="ck_conversation_evidence_purge_order",
        ),
        CheckConstraint(
            "evidence_expires_at >= captured_at",
            name="ck_conversation_evidence_expiry_order",
        ),
        UniqueConstraint("conversation_id", name="uq_conversation_evidence_conversation_id"),
        UniqueConstraint("ambassador_contact_id", name="uq_conversation_evidence_contact"),
        Index("ix_conversation_evidence_captured_at", "captured_at"),
        Index("ix_conversation_evidence_expires_at", "evidence_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ambassador_contact_id: Mapped[int] = mapped_column(
        ForeignKey("ambassador_contact_attempts.id", ondelete="CASCADE"), nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_class: Mapped[str] = mapped_column(String(40), nullable=False)
    capture_class: Mapped[str] = mapped_column(String(32), nullable=False)
    protocol: Mapped[str] = mapped_column(String(40), nullable=False)
    protocol_context_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    protocol_task_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    protocol_message_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    safe_evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    redaction_summary: Mapped[dict] = mapped_column(JSON, nullable=False)
    evidence_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationIntelligence(Base):
    __tablename__ = "conversation_intelligence"
    __table_args__ = (
        UniqueConstraint("intelligence_id", name="uq_conversation_intelligence_id"),
        UniqueConstraint(
            "conversation_evidence_id", "analysis_version",
            name="uq_conversation_intelligence_evidence_version",
        ),
        Index("ix_conversation_intelligence_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    intelligence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_evidence_id: Mapped[int] = mapped_column(
        ForeignKey("conversation_evidence.id", ondelete="CASCADE"), nullable=False
    )
    analysis_method: Mapped[str] = mapped_column(String(40), nullable=False)
    analysis_version: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    explicit_signals: Mapped[list] = mapped_column(JSON, nullable=False)
    inferred_signals: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
