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


class LearningRun(Base):
    __tablename__ = "learning_runs"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_learning_runs_run_id"),
        CheckConstraint("sources_considered >= 0", name="ck_learning_runs_sources_nonnegative"),
        CheckConstraint("outbound_attempts >= 0", name="ck_learning_runs_attempts_nonnegative"),
        CheckConstraint("response_bytes >= 0", name="ck_learning_runs_bytes_nonnegative"),
        CheckConstraint("paid_external_spend_permitted = false", name="ck_learning_runs_paid_spend_disabled_v1"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    trigger: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sources_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbound_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paid_external_spend_permitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LearningSourceWatchState(Base):
    __tablename__ = "learning_source_watch_states"
    __table_args__ = (
        UniqueConstraint("source_id", name="uq_learning_source_watch_states_source"),
        CheckConstraint("consecutive_failures >= 0", name="ck_learning_watch_failures_nonnegative"),
        CheckConstraint("outbound_attempts_total >= 0", name="ck_learning_watch_attempts_nonnegative"),
        CheckConstraint("response_bytes_total >= 0", name="ck_learning_watch_bytes_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(160), ForeignKey("live_utility_sources.source_id", ondelete="CASCADE"), nullable=False
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_observation_id: Mapped[str | None] = mapped_column(
        String(160), ForeignKey("live_utility_observations.observation_id", ondelete="RESTRICT"), nullable=True
    )
    last_material_change_observation_id: Mapped[str | None] = mapped_column(
        String(160), ForeignKey("live_utility_observations.observation_id", ondelete="RESTRICT"), nullable=True
    )
    next_eligible_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outbound_attempts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_bytes_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentEvidenceClaim(Base):
    __tablename__ = "agent_evidence_claims"
    __table_args__ = (
        UniqueConstraint("claim_id", name="uq_agent_evidence_claims_claim_id"),
        UniqueConstraint(
            "requester_agent_id", "idempotency_key",
            name="uq_agent_evidence_claims_requester_idempotency",
        ),
        UniqueConstraint(
            "requester_agent_id", "evidence_digest",
            name="uq_agent_evidence_claims_requester_material",
        ),
        Index("ix_agent_evidence_digest_state", "evidence_digest", "state"),
        Index("ix_agent_evidence_category_submitted", "category", "submitted_at"),
        CheckConstraint("corroborating_agent_count >= 1", name="ck_agent_evidence_corroboration_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requester_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    reference_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    provider_identifier: Mapped[str | None] = mapped_column(String(240), nullable=True)
    protocol: Mapped[str | None] = mapped_column(String(40), nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    corroborating_agent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supporting_references: Mapped[list | None] = mapped_column(JSON, nullable=True)


class LearningOpportunityCandidate(Base):
    __tablename__ = "learning_opportunity_candidates"
    __table_args__ = (
        UniqueConstraint("candidate_key", name="uq_learning_opportunities_candidate_key"),
        Index("ix_learning_opportunities_priority", "priority_score", "last_seen_at"),
        CheckConstraint("total_meaningful_signals >= 0", name="ck_learning_opportunities_signals_nonnegative"),
        CheckConstraint("distinct_requester_count >= 0", name="ck_learning_opportunities_requesters_nonnegative"),
        CheckConstraint("repeat_requester_count >= 0", name="ck_learning_opportunities_repeats_nonnegative"),
        CheckConstraint("anonymous_signal_count >= 0", name="ck_learning_opportunities_anonymous_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_key: Mapped[str] = mapped_column(String(71), nullable=False)
    normalized_demand_key: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_meaningful_signals: Mapped[int] = mapped_column(Integer, nullable=False)
    distinct_requester_count: Mapped[int] = mapped_column(Integer, nullable=False)
    repeat_requester_count: Mapped[int] = mapped_column(Integer, nullable=False)
    anonymous_signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_class_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    operational_failure_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False)
    supporting_evidence_references: Mapped[list] = mapped_column(JSON, nullable=False)
    evidence_state: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    known_provider_availability: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payment_potential: Mapped[str | None] = mapped_column(String(40), nullable=True)
    known_cost: Mapped[str | None] = mapped_column(String(64), nullable=True)
    margin_feasibility: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Package5ParticipationAssessment(Base):
    __tablename__ = "package5_participation_assessments"
    __table_args__ = (
        CheckConstraint(
            "classification IN ('aion_operated_internal', 'synthetic_probe_test', "
            "'coordinated_design_partner', 'operator_invited_coordinated_test', "
            "'independent_external_candidate', 'independent_external_countable')",
            name="ck_package5_participation_classification",
        ),
        CheckConstraint(
            "evidence_authority = 'operator_reviewed_evidence'",
            name="ck_package5_participation_operator_authority",
        ),
        UniqueConstraint("assessment_id", name="uq_package5_participation_assessment_id"),
        UniqueConstraint(
            "canonical_agent_id", "idempotency_key",
            name="uq_package5_participation_agent_idempotency",
        ),
        Index(
            "ix_package5_participation_agent_assessed",
            "canonical_agent_id", "assessed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assessment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    canonical_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    assessment_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    evidence_authority: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_reference_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    evidence_summary_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    release_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Package5VuoProof(Base):
    __tablename__ = "package5_vuo_proofs"
    __table_args__ = (
        CheckConstraint(
            "goal_kind = 'verify_external_agent_callability'",
            name="ck_package5_vuo_goal_kind_v1",
        ),
        CheckConstraint(
            "product_goal = 'find_verify_invoke_external_a2a_agent'",
            name="ck_package5_vuo_product_goal_v1",
        ),
        CheckConstraint(
            "delivered_outcome = 'verified_external_agent_callability'",
            name="ck_package5_vuo_delivered_outcome_v1",
        ),
        CheckConstraint(
            "usefulness_state = 'requester_confirmed'",
            name="ck_package5_vuo_usefulness_state_v1",
        ),
        CheckConstraint(
            "usefulness_method = 'authenticated_requester_attestation'",
            name="ck_package5_vuo_usefulness_method_v1",
        ),
        CheckConstraint(
            "usefulness_evidence = 'requester_confirms_goal_was_useful'",
            name="ck_package5_vuo_usefulness_evidence_v1",
        ),
        CheckConstraint(
            "participation_classification_at_submission IN "
            "('unknown_not_proven', 'aion_operated_internal', 'synthetic_probe_test', "
            "'coordinated_design_partner', 'operator_invited_coordinated_test', "
            "'independent_external_candidate', 'independent_external_countable')",
            name="ck_package5_vuo_submission_classification",
        ),
        CheckConstraint(
            "participation_classification_at_submission != 'independent_external_countable' "
            "OR participation_assessment_id IS NOT NULL",
            name="ck_package5_vuo_countable_has_assessment",
        ),
        CheckConstraint(
            "cost_state IN ('unknown', 'known_zero', 'known_nonzero')",
            name="ck_package5_vuo_cost_state",
        ),
        CheckConstraint(
            "(cost_state = 'unknown' AND cost_amount IS NULL AND cost_currency IS NULL) OR "
            "(cost_state IN ('known_zero', 'known_nonzero') AND cost_amount IS NOT NULL "
            "AND cost_currency IS NOT NULL)",
            name="ck_package5_vuo_cost_material",
        ),
        UniqueConstraint("vuo_id", name="uq_package5_vuo_id"),
        UniqueConstraint("action_run_id", name="uq_package5_vuo_action_run"),
        UniqueConstraint(
            "canonical_requester_agent_id", "idempotency_key",
            name="uq_package5_vuo_requester_idempotency",
        ),
        Index(
            "ix_package5_vuo_requester_created",
            "canonical_requester_agent_id", "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vuo_id: Mapped[str] = mapped_column(String(36), nullable=False)
    canonical_requester_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    requester_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    action_run_id: Mapped[int] = mapped_column(
        ForeignKey("action_runs.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    goal_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    product_goal: Mapped[str] = mapped_column(String(500), nullable=False)
    delivered_outcome: Mapped[str] = mapped_column(String(1000), nullable=False)
    outcome_verification_state: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome_verification_method: Mapped[str] = mapped_column(String(80), nullable=False)
    usefulness_state: Mapped[str] = mapped_column(String(40), nullable=False)
    usefulness_method: Mapped[str] = mapped_column(String(80), nullable=False)
    usefulness_evidence: Mapped[str] = mapped_column(String(500), nullable=False)
    semantic_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    eligibility_reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    participation_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("package5_participation_assessments.id", ondelete="RESTRICT"), nullable=True
    )
    participation_classification_at_submission: Mapped[str] = mapped_column(String(64), nullable=False)
    participation_reason_at_submission: Mapped[str] = mapped_column(String(96), nullable=False)
    cost_state: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_amount: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cost_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    release_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EconomicOperation(Base):
    __tablename__ = "economic_operations"
    __table_args__ = (
        UniqueConstraint("operation_id", name="uq_economic_operations_operation_id"),
        UniqueConstraint(
            "requester_agent_id", "idempotency_key",
            name="uq_economic_operations_requester_idempotency",
        ),
        CheckConstraint("maximum_attempts > 0", name="ck_economic_operations_attempts_positive"),
        CheckConstraint(
            "expected_margin_bps >= 0 AND expected_margin_bps <= 10000",
            name="ck_economic_operations_margin_bps",
        ),
        CheckConstraint(
            "commercial_rights_state IN ('allowed', 'unknown', 'prohibited')",
            name="ck_economic_operations_rights",
        ),
        CheckConstraint(
            "state IN ('quoted', 'payment_authorized', 'funds_reserved', "
            "'execution_started', 'outcome_verified', 'settlement_ready', "
            "'settled', 'reserve_released', 'failed', 'cancelled')",
            name="ck_economic_operations_state",
        ),
        CheckConstraint(
            "NOT funding_required OR NOT execution_eligible",
            name="ck_economic_operations_no_unfunded_execution",
        ),
        CheckConstraint(
            "parent_economic_operation_id IS NULL OR parent_economic_operation_id <> id",
            name="ck_economic_operations_not_own_parent",
        ),
        CheckConstraint(
            "state != 'payment_authorized' OR authorized_amount IS NOT NULL",
            name="ck_economic_operations_authorized_state_evidence",
        ),
        CheckConstraint(
            "state != 'funds_reserved' OR (authorized_amount IS NOT NULL AND reserved_amount IS NOT NULL)",
            name="ck_economic_operations_reserved_state_evidence",
        ),
        CheckConstraint(
            "state NOT IN ('execution_started', 'outcome_verified', 'settlement_ready', 'settled', 'reserve_released') "
            "OR NOT funding_required OR reserved_amount IS NOT NULL",
            name="ck_economic_operations_funded_execution_evidence",
        ),
        CheckConstraint(
            "state NOT IN ('outcome_verified', 'settlement_ready', 'settled', 'reserve_released') "
            "OR action_run_id IS NOT NULL",
            name="ck_economic_operations_outcome_state_evidence",
        ),
        CheckConstraint(
            "state NOT IN ('settlement_ready', 'settled', 'reserve_released') OR actual_cost IS NOT NULL",
            name="ck_economic_operations_cost_state_evidence",
        ),
        CheckConstraint(
            "state NOT IN ('settled', 'reserve_released') OR settlement_amount IS NOT NULL",
            name="ck_economic_operations_settlement_state_evidence",
        ),
        CheckConstraint(
            "state != 'reserve_released' OR released_amount IS NOT NULL",
            name="ck_economic_operations_release_state_evidence",
        ),
        UniqueConstraint("action_run_id", name="uq_economic_operations_action_run"),
        Index("ix_economic_operations_requester_created", "requester_agent_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requester_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    parent_economic_operation_id: Mapped[int | None] = mapped_column(
        ForeignKey("economic_operations.id", ondelete="RESTRICT"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    product_sku: Mapped[str] = mapped_column(String(120), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    customer_price: Mapped[str] = mapped_column(String(48), nullable=False)
    expected_variable_cost: Mapped[str] = mapped_column(String(48), nullable=False)
    maximum_variable_cost: Mapped[str | None] = mapped_column(String(48), nullable=True)
    verification_cost: Mapped[str] = mapped_column(String(48), nullable=False)
    payment_fee_allowance: Mapped[str] = mapped_column(String(48), nullable=False)
    expected_total_cost: Mapped[str] = mapped_column(String(48), nullable=False)
    maximum_total_spend: Mapped[str | None] = mapped_column(String(48), nullable=True)
    contribution_amount: Mapped[str] = mapped_column(String(48), nullable=False)
    expected_margin_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_cost_per_verified_outcome: Mapped[str] = mapped_column(String(48), nullable=False)
    maximum_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    commercial_rights_state: Mapped[str] = mapped_column(String(24), nullable=False)
    funding_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    policy_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    decision_reasons: Mapped[list] = mapped_column(JSON, nullable=False)
    adapter_state: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    authorized_amount: Mapped[str | None] = mapped_column(String(48), nullable=True)
    reserved_amount: Mapped[str | None] = mapped_column(String(48), nullable=True)
    actual_cost: Mapped[str | None] = mapped_column(String(48), nullable=True)
    settlement_amount: Mapped[str | None] = mapped_column(String(48), nullable=True)
    released_amount: Mapped[str | None] = mapped_column(String(48), nullable=True)
    action_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_runs.id", ondelete="RESTRICT"), nullable=True
    )
    release_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quote_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EconomicTransition(Base):
    __tablename__ = "economic_transitions"
    __table_args__ = (
        UniqueConstraint("transition_id", name="uq_economic_transitions_transition_id"),
        UniqueConstraint(
            "economic_operation_id", "sequence",
            name="uq_economic_transitions_operation_sequence",
        ),
        UniqueConstraint(
            "economic_operation_id", "idempotency_key",
            name="uq_economic_transitions_operation_idempotency",
        ),
        Index("ix_economic_transitions_operation_created", "economic_operation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transition_id: Mapped[str] = mapped_column(String(36), nullable=False)
    economic_operation_id: Mapped[int] = mapped_column(
        ForeignKey("economic_operations.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    transition_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_state: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    evidence_authority: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    amount: Mapped[str | None] = mapped_column(String(48), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AmbassadorCampaign(Base):
    __tablename__ = "ambassador_campaigns"
    __table_args__ = (
        CheckConstraint("state IN ('draft', 'ready', 'paused', 'closed')", name="ck_ambassador_campaign_state"),
        CheckConstraint("maximum_targets > 0 AND maximum_targets <= 30", name="ck_ambassador_campaign_target_limit"),
        CheckConstraint("maximum_contacts >= 0 AND maximum_contacts <= maximum_targets", name="ck_ambassador_campaign_contact_limit"),
        UniqueConstraint("campaign_id", name="uq_ambassador_campaign_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    maximum_targets: Mapped[int] = mapped_column(Integer, nullable=False)
    maximum_contacts: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AmbassadorTarget(Base):
    __tablename__ = "ambassador_targets"
    __table_args__ = (
        CheckConstraint(
            "qualification_state IN ('discovered', 'qualified', 'rejected')",
            name="ck_ambassador_target_qualification_state",
        ),
        CheckConstraint(
            "contact_state IN ('not_ready', 'ready', 'claimed', 'contacted', 'response_received', 'blocked', 'ambiguous')",
            name="ck_ambassador_target_contact_state",
        ),
        UniqueConstraint("target_id", name="uq_ambassador_target_id"),
        UniqueConstraint("target_fingerprint", name="uq_ambassador_target_fingerprint"),
        UniqueConstraint("campaign_id", "source_identifier", name="uq_ambassador_target_campaign_source"),
        Index("ix_ambassador_targets_campaign_state", "campaign_id", "qualification_state", "contact_state"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("ambassador_campaigns.id", ondelete="RESTRICT"), nullable=False)
    discovery_source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_identifier: Mapped[str] = mapped_column(String(240), nullable=False)
    agent_card_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    interaction_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    target_fingerprint: Mapped[str] = mapped_column(String(71), nullable=False)
    metadata_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    manifest_reachable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    declared_a2a_v1_jsonrpc: Mapped[bool] = mapped_column(Boolean, nullable=False)
    interaction_url_validated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    authentication_requirement: Mapped[str] = mapped_column(String(32), nullable=False)
    payment_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    qualification_state: Mapped[str] = mapped_column(String(24), nullable=False)
    qualification_reasons: Mapped[list] = mapped_column(JSON, nullable=False)
    contact_state: Mapped[str] = mapped_column(String(24), nullable=False)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suppression_reason: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AmbassadorContactAttempt(Base):
    __tablename__ = "ambassador_contact_attempts"
    __table_args__ = (
        CheckConstraint(
            "result_class IN ('claimed', 'dry_run', 'delivered', 'response_received', 'payment_required', 'credentials_required', 'rejected', 'ambiguous', 'transport_error')",
            name="ck_ambassador_contact_result_class",
        ),
        UniqueConstraint("contact_id", name="uq_ambassador_contact_id"),
        UniqueConstraint("target_id", name="uq_ambassador_contact_target_once"),
        UniqueConstraint("target_id", "idempotency_key", name="uq_ambassador_contact_target_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_id: Mapped[int] = mapped_column(ForeignKey("ambassador_targets.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    outbound_request_digest: Mapped[str] = mapped_column(String(71), nullable=False)
    result_class: Mapped[str] = mapped_column(String(32), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_digest: Mapped[str | None] = mapped_column(String(71), nullable=True)
    response_received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DistributionToken(Base):
    __tablename__ = "distribution_tokens"
    __table_args__ = (
        CheckConstraint("kind IN ('ambassador_invite', 'peer_referral')", name="ck_distribution_token_kind"),
        CheckConstraint("maximum_uses > 0 AND maximum_uses <= 5", name="ck_distribution_token_use_limit"),
        CheckConstraint("use_count >= 0 AND use_count <= maximum_uses", name="ck_distribution_token_use_count"),
        CheckConstraint(
            "(kind = 'ambassador_invite' AND maximum_uses = 1 AND target_id IS NOT NULL AND referrer_agent_id IS NULL) OR "
            "(kind = 'peer_referral' AND target_id IS NULL AND referrer_agent_id IS NOT NULL)",
            name="ck_distribution_token_provenance",
        ),
        UniqueConstraint("token_id", name="uq_distribution_token_id"),
        UniqueConstraint("token_digest", name="uq_distribution_token_digest"),
        UniqueConstraint("target_id", "kind", name="uq_distribution_token_target_kind"),
        UniqueConstraint("referrer_agent_id", "idempotency_key", name="uq_distribution_token_referrer_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_id: Mapped[str] = mapped_column(String(36), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("ambassador_campaigns.id", ondelete="RESTRICT"), nullable=True)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("ambassador_targets.id", ondelete="RESTRICT"), nullable=True)
    referrer_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    maximum_uses: Mapped[int] = mapped_column(Integer, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DistributionJoinAttribution(Base):
    __tablename__ = "distribution_join_attributions"
    __table_args__ = (
        CheckConstraint("kind IN ('ambassador_invite', 'peer_referral')", name="ck_distribution_join_kind"),
        CheckConstraint(
            "trusted_acquisition_source IN ('aion_ambassador_outbound', 'trusted_peer_referral')",
            name="ck_distribution_join_source",
        ),
        UniqueConstraint("agent_id", name="uq_distribution_join_agent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    token_id: Mapped[int] = mapped_column(ForeignKey("distribution_tokens.id", ondelete="RESTRICT"), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("ambassador_campaigns.id", ondelete="RESTRICT"), nullable=True)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("ambassador_targets.id", ondelete="RESTRICT"), nullable=True)
    referrer_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True)
    trusted_acquisition_source: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
