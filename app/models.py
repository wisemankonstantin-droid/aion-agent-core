from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    endpoint: Mapped[str | None] = mapped_column(String(500), nullable=True)
    protocol: Mapped[str] = mapped_column(String(40), default="REST")
    acquisition_source: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    referrer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    owner_required: Mapped[bool] = mapped_column(Boolean, default=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    reputation: Mapped[float] = mapped_column(Float, default=0.0)
    trust_level: Mapped[str] = mapped_column(String(40), default="declared")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_useful_action_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    authenticated_calls: Mapped[int] = mapped_column(Integer, default=0)

class Capability(Base):
    __tablename__ = "capabilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    verification: Mapped[str] = mapped_column(String(40), default="declared")

class Need(Base):
    __tablename__ = "needs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    capability: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    capability: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text)
    price_hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class Interaction(Base):
    __tablename__ = "interactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requester_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    provider_agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    need_id: Mapped[int | None] = mapped_column(ForeignKey("needs.id"), nullable=True)
    result: Mapped[str] = mapped_column(String(40), default="pending")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class ReputationEvent(Base):
    __tablename__ = "reputation_events"
    __table_args__ = (Index("uq_reputation_events_agent_reason", "agent_id", "reason", unique=True),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    delta: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class PaymentIntent(Base):
    __tablename__ = "payment_intents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(120))
    amount: Mapped[str] = mapped_column(String(120))
    protocol: Mapped[str] = mapped_column(String(40), default="manual")
    status: Mapped[str] = mapped_column(String(40), default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class MachineEntry(Base):
    __tablename__ = "machine_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class LiveUtilitySource(Base):
    __tablename__ = "live_utility_sources"
    __table_args__ = (
        CheckConstraint(
            "tier IN ('tier_1', 'tier_2', 'tier_3')",
            name="ck_live_utility_sources_tier",
        ),
        CheckConstraint(
            "stale_after_seconds > 0",
            name="ck_live_utility_sources_stale_positive",
        ),
        CheckConstraint(
            "expires_after_seconds > 0",
            name="ck_live_utility_sources_expires_positive",
        ),
        CheckConstraint(
            "expires_after_seconds >= stale_after_seconds",
            name="ck_live_utility_sources_window_order",
        ),
        Index("ix_live_utility_sources_source_id", "source_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(String(160), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    canonical_locator: Mapped[str] = mapped_column(String(1000), nullable=False)
    refresh_strategies: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    stale_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)


class LiveUtilityObservation(Base):
    __tablename__ = "live_utility_observations"
    __table_args__ = (
        CheckConstraint(
            "valid_from <= stale_after",
            name="ck_live_utility_observations_valid_stale_order",
        ),
        CheckConstraint(
            "stale_after <= expires_at",
            name="ck_live_utility_observations_stale_expires_order",
        ),
        CheckConstraint(
            "verified_at IS NULL OR verified_at >= observed_at",
            name="ck_live_utility_observations_verified_order",
        ),
        CheckConstraint(
            "previous_observation_id IS NULL OR previous_observation_id != observation_id",
            name="ck_live_utility_observations_not_self_referential",
        ),
        Index(
            "ix_live_utility_observations_observation_id",
            "observation_id",
            unique=True,
        ),
        Index("ix_live_utility_observations_source_id", "source_id"),
        Index(
            "ix_live_utility_observations_source_subject_observed",
            "source_id",
            "subject_key",
            "observed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("live_utility_sources.source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    subject_key: Mapped[str] = mapped_column(String(240), nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(240), nullable=True)
    previous_observation_id: Mapped[str | None] = mapped_column(
        String(160),
        ForeignKey("live_utility_observations.observation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verification_method: Mapped[str | None] = mapped_column(String(160), nullable=True)
    content_digest: Mapped[str] = mapped_column(String(240), nullable=False)
