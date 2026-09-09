from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
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
        UniqueConstraint("source_id", name="uq_live_utility_sources_source_id"),
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
        UniqueConstraint(
            "observation_id",
            name="uq_live_utility_observations_observation_id",
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
    normalized_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LiveUtilityVerification(Base):
    __tablename__ = "live_utility_verifications"
    __table_args__ = (
        CheckConstraint(
            "valid_from <= stale_after",
            name="ck_live_utility_verifications_valid_stale_order",
        ),
        CheckConstraint(
            "stale_after <= expires_at",
            name="ck_live_utility_verifications_stale_expires_order",
        ),
        UniqueConstraint(
            "verification_id",
            name="uq_live_utility_verifications_verification_id",
        ),
        Index(
            "ix_live_utility_verifications_source_subject_verified",
            "source_id",
            "subject_key",
            "verified_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verification_id: Mapped[str] = mapped_column(String(160), nullable=False)
    source_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("live_utility_sources.source_id", ondelete="RESTRICT"),
        nullable=False,
    )
    subject_key: Mapped[str] = mapped_column(String(240), nullable=False)
    observation_id: Mapped[str] = mapped_column(
        String(160),
        ForeignKey("live_utility_observations.observation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stale_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verification_method: Mapped[str] = mapped_column(String(160), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(240), nullable=False)


class AgentUtilityCheckpoint(Base):
    __tablename__ = "agent_utility_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "agent_id",
            "subject_key",
            name="uq_agent_utility_checkpoints_agent_subject",
        ),
        Index(
            "ix_agent_utility_checkpoints_agent_checked",
            "agent_id",
            "checked_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_key: Mapped[str] = mapped_column(String(240), nullable=False)
    observation_id: Mapped[str | None] = mapped_column(
        String(160),
        ForeignKey("live_utility_observations.observation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    source_revision: Mapped[str | None] = mapped_column(String(240), nullable=True)
    freshness_state: Mapped[str] = mapped_column(String(40), nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActionRun(Base):
    __tablename__ = "action_runs"
    __table_args__ = (
        UniqueConstraint(
            "requester_agent_id",
            "idempotency_key",
            name="uq_action_runs_requester_idempotency",
        ),
        UniqueConstraint("action_id", name="uq_action_runs_action_id"),
        Index("ix_action_runs_requester_created", "requester_agent_id", "created_at"),
        CheckConstraint("action_attempt_count >= 0", name="ck_action_runs_attempts_nonnegative"),
        CheckConstraint("discovery_attempt_count >= 0", name="ck_action_runs_discovery_nonnegative"),
        CheckConstraint("request_bytes >= 0", name="ck_action_runs_request_bytes_nonnegative"),
        CheckConstraint(
            "response_bytes IS NULL OR response_bytes >= 0",
            name="ck_action_runs_response_bytes_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requester_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    requested_query: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_candidate_identifier: Mapped[str | None] = mapped_column(String(240), nullable=True)
    authorize_external_contact: Mapped[bool] = mapped_column(Boolean, nullable=False)
    selected_provider_identifier: Mapped[str | None] = mapped_column(String(240), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    agent_card_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    interaction_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    discovery_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    protocol_binding: Mapped[str | None] = mapped_column(String(40), nullable=True)
    protocol_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discovery_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_amount: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)


class ActionAttempt(Base):
    __tablename__ = "action_attempts"
    __table_args__ = (
        UniqueConstraint(
            "action_run_id", "attempt_number", name="uq_action_attempts_run_number"
        ),
        CheckConstraint("attempt_number = 1", name="ck_action_attempts_one_post_v1"),
        CheckConstraint("request_bytes >= 0", name="ck_action_attempts_request_bytes_nonnegative"),
        CheckConstraint(
            "response_bytes IS NULL OR response_bytes >= 0",
            name="ck_action_attempts_response_bytes_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_run_id: Mapped[int] = mapped_column(
        ForeignKey("action_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    delivery_state: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transport_error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    response_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    protocol_response_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ActionOutcome(Base):
    __tablename__ = "action_outcomes"
    __table_args__ = (
        UniqueConstraint("action_run_id", name="uq_action_outcomes_run"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_run_id: Mapped[int] = mapped_column(
        ForeignKey("action_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    outcome_type: Mapped[str] = mapped_column(String(80), nullable=False)
    protocol_response_received: Mapped[bool] = mapped_column(Boolean, nullable=False)
    callability_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    capability_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verified_outcome: Mapped[bool] = mapped_column(Boolean, nullable=False)
    normalized_result_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    response_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    protocol_task_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    protocol_message_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    proof_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ActionVerification(Base):
    __tablename__ = "action_verifications"
    __table_args__ = (
        UniqueConstraint("action_run_id", name="uq_action_verifications_run"),
        UniqueConstraint("action_outcome_id", name="uq_action_verifications_outcome"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_run_id: Mapped[int] = mapped_column(
        ForeignKey("action_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action_outcome_id: Mapped[int] = mapped_column(
        ForeignKey("action_outcomes.id", ondelete="CASCADE"), nullable=False
    )
    verification_method: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    challenge_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    proof_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
