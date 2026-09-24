"""Intent-first acquisition workers built on the existing Ambassador control plane.

Workers are transparent AION-operated acquisition lanes, never external members.
They discover public buyer-intent surfaces and federated A2A supply. Only
verified buyer-intent surfaces are eligible for acquisition contact; federated
registry entries remain discovery/supply evidence unless future evidence proves
a real requester-intent surface.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from threading import Lock, Thread

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models
from ..acquisition import WORKERS as ACQUISITION_WORKERS, WORKER_COUNT
from ..db import SessionLocal
from .conversation_intelligence import campaign_intelligence_report
from .acquisition_agent_mind import (
    record_worker_outcome,
    refresh_all_minds,
    runtime_status as acquisition_mind_runtime_status,
)
from .ambassador import (
    AmbassadorError,
    MAX_CAMPAIGN_TARGETS,
    create_campaign,
    prepare_and_send_operator_contact,
    prepare_and_send_operator_moltbook_dm,
    scout_campaign,
    scout_colony_campaign,
    scout_colony_paid_tasks_campaign,
    scout_moltbook_campaign,
    scout_moltbook_recent_campaign,
    set_campaign_state,
)
from .moltbook_acquisition import (
    account_status as moltbook_account_status,
    dm_check as moltbook_dm_check,
    dm_outbound_enabled as moltbook_dm_outbound_enabled,
    outbound_status as moltbook_outbound_status,
)
from .colony_acquisition import account_status as colony_account_status
from .commercial_payment_routes import (
    PreSpendPreflightError,
    pre_spend_preflight_data,
)


INTENT_WORKERS: dict[str, tuple[str, ...]] = {
    "provider_selection": (
        "provider selection", "tool selection", "api vendor comparison",
        "agent provider choice", "external tool procurement", "best provider for task",
    ),
    "paid_api_buyers": (
        "paid api", "x402 payments", "metered api purchase",
        "api billing agent", "pay per call api", "external api spend",
    ),
    "agent_wallets": (
        "agent wallet", "spend controls", "agent budget approval",
        "autonomous wallet policy", "machine payment limits", "agent treasury spend",
    ),
    "mcp_buyers": (
        "MCP paid tools", "MCP payments", "paid MCP server",
        "MCP tool pricing", "agent MCP purchase", "metered MCP tool",
    ),
    "a2a_buyers": (
        "A2A agent", "agent collaboration", "paid A2A service",
        "agent to agent purchase", "external agent service", "A2A provider selection",
    ),
    "data_buyers": (
        "data api", "search api", "paid data provider",
        "web search purchase", "research data spend", "data vendor selection",
    ),
    "automation_buyers": (
        "automation tools", "browser tools", "paid browser agent",
        "automation api purchase", "browser provider selection", "external automation service",
    ),
    "inference_buyers": (
        "inference api", "LLM gateway", "paid inference provider",
        "model api purchase", "LLM provider selection", "inference spend routing",
    ),
    "fallback_seekers": (
        "provider fallback", "provider reliability", "api fallback route",
        "tool outage alternative", "provider failover", "replacement api provider",
    ),
    "agent_commerce": (
        "agent procurement", "agent commerce", "machine procurement",
        "autonomous purchase", "agent buying service", "external spend agent",
    ),
    "security_buyers": (
        "security api", "agent security service", "provider security assessment",
        "api security vendor", "secret management service", "external security tool",
    ),
    "observability_buyers": (
        "observability api", "monitoring provider", "uptime monitoring service",
        "agent tracing service", "logging vendor", "reliability monitoring",
    ),
    "storage_compute_buyers": (
        "cloud database provider", "vector database service", "object storage api",
        "gpu compute provider", "agent hosting service", "serverless provider",
    ),
    "payments_buyers": (
        "payment api provider", "agent payment rail", "usdc payment service",
        "x402 facilitator", "machine payment provider", "settlement api",
    ),
    "verification_buyers": (
        "provider verification", "agent trust verification", "endpoint verification service",
        "capability verification", "pre purchase verification", "supplier due diligence",
    ),
}

MIN_MODEL_TRANSPORT_CONFIDENCE = 20

MOLTBOOK_INTENT_QUERIES: dict[str, tuple[str, ...]] = {
    "provider_selection": (
        "I need to choose an external API, agent, tool, or provider for a real task",
        "Which provider should I use for this task before paying",
        "Looking for a reliable external tool or service recommendation",
        "Need to compare providers, vendors, or agent services before purchase",
        "What is the best paid provider for this capability",
        "Need a provider alternative with lower risk or cost",
    ),
    "paid_api_buyers": (
        "I am about to pay for an API, metered service, or x402 resource",
        "Looking for a paid API for a current production task",
        "Need an API with pricing or pay per call billing",
        "I need to buy API access for an agent workflow",
        "Need a metered API provider with predictable cost",
        "Comparing paid APIs before spending money",
    ),
    "agent_wallets": (
        "My AI agent needs to spend money and I need budget or provider controls",
        "Agent wallet needs approval before buying an external service",
        "Need spending limits for an autonomous agent purchase",
        "AI agent budget for paid tools or APIs",
        "Machine wallet needs safe provider selection before payment",
        "Need treasury controls for agent external spend",
    ),
    "mcp_buyers": (
        "I need a paid MCP tool or server and must decide whether to buy it",
        "Looking for a paid MCP server for a real task",
        "Need MCP pricing before choosing a tool",
        "Comparing paid MCP tools or metered MCP services",
        "Need an MCP provider with billing or x402",
        "Which MCP service should my agent pay for",
    ),
    "a2a_buyers": (
        "I need to hire or pay another agent or A2A service for a real job",
        "Looking for an external AI agent to perform a paid task",
        "Need an A2A provider before paying another agent",
        "Comparing agent services for a current job",
        "Need to buy a result from another agent",
        "Which external agent service should I use",
    ),
    "data_buyers": (
        "I need to buy search, research, or data API access for a current task",
        "Looking for a paid data provider or search API",
        "Need research data and must choose a vendor",
        "Comparing paid search or web data APIs",
        "Need an external data service before spending",
        "Which data API is worth paying for",
    ),
    "automation_buyers": (
        "I need to pay for browser automation or an external automation provider",
        "Looking for a paid browser automation API",
        "Need an automation provider for a production task",
        "Comparing browser agents or automation services before purchase",
        "Need a paid external tool to automate this workflow",
        "Which browser or automation provider should I buy",
    ),
    "inference_buyers": (
        "I need to choose and pay an inference, model API, or LLM gateway provider",
        "Looking for a paid inference API or LLM gateway",
        "Need model API pricing before choosing a provider",
        "Comparing inference providers for cost and reliability",
        "Need a paid LLM API for an agent workflow",
        "Which inference provider should I pay for",
    ),
    "fallback_seekers": (
        "My current API or provider is failing and I need a paid replacement or fallback",
        "Need an alternative provider because the current service is unreliable",
        "Looking for a fallback API or replacement tool",
        "Provider outage and I need another paid option",
        "Need a reliable substitute for an external service",
        "Looking to replace a failing API provider",
    ),
    "agent_commerce": (
        "My autonomous agent needs to procure an external service before spending money",
        "Agent needs to buy a tool or service for a current task",
        "Machine procurement for an external API or provider",
        "Autonomous purchase needs provider selection and price",
        "Agent commerce workflow needs a qualified external route",
        "Need to purchase an external capability for an AI agent",
    ),
    "security_buyers": (
        "I need a security API or external security service before spending",
        "Looking for an agent security provider for a production workflow",
        "Need to compare API security vendors before purchase",
        "Need secret management or security tooling for an autonomous agent",
        "Which external security service should this agent pay for",
        "Need to qualify a security provider before integrating it",
    ),
    "observability_buyers": (
        "I need a monitoring or observability provider for an agent workload",
        "Looking for paid uptime monitoring or tracing before purchase",
        "Need to compare logging or observability services for production",
        "Which monitoring provider should an autonomous agent use",
        "Need an external reliability service with clear pricing",
        "Looking for agent tracing or monitoring before spending",
    ),
    "storage_compute_buyers": (
        "I need a database, storage, hosting, or compute provider for an agent",
        "Looking for a paid vector database or object storage service",
        "Need to compare GPU or serverless compute providers before spending",
        "Which hosting or database provider should this agent buy",
        "Need external compute with predictable cost for an agent workflow",
        "Looking for storage or compute infrastructure before purchase",
    ),
    "payments_buyers": (
        "I need a payment API or machine payment rail for an agent",
        "Looking for a USDC or x402 payment provider before integrating",
        "Need to compare payment or settlement services for autonomous agents",
        "Which payment provider should this agent use before moving money",
        "Need a machine payment service with clear fees and settlement behavior",
        "Looking for an x402 facilitator or settlement API",
    ),
    "verification_buyers": (
        "I need to verify an external provider before paying or integrating",
        "Looking for provider trust or endpoint verification for an agent",
        "Need capability verification before selecting an external service",
        "Which verification service can qualify this supplier before purchase",
        "Need due diligence on an external agent API or provider",
        "Looking for pre-purchase provider verification",
    ),
}

MAX_WORKERS_PER_CYCLE = WORKER_COUNT
DEFAULT_ACTIVE_WORKERS_PER_CYCLE = 20
MAX_CONTACTS_PER_CYCLE = 20
MAX_COLONY_SCOUT_WORKERS_PER_CYCLE = 5
MAX_COLONY_COMMENTS_PER_CYCLE = 2
MAX_COLONY_COMMENTS_PER_DAY = 20
DEFAULT_INTERVAL_SECONDS = 15 * 60
MIN_INTERVAL_SECONDS = 15 * 60
MAX_INTERVAL_SECONDS = 24 * 60 * 60
QUERIES_PER_WORKER_PER_CYCLE = 2
DAILY_NEW_TARGET_GOAL_PER_WORKER = 20
DAILY_CONTACT_GOAL_PER_WORKER = 10
DAILY_RESPONSE_GOAL_PER_WORKER = 2
MOLTBOOK_DAILY_COMMENT_LIMIT = 50
MOLTBOOK_MAX_COMMENTS_PER_CYCLE = 2
MOLTBOOK_MIN_COMMENT_INTERVAL_SECONDS = 21
MOLTBOOK_DM_DAILY_REQUEST_LIMIT = 20
MOLTBOOK_DM_MAX_REQUESTS_PER_CYCLE = 2
# Public A2A registries describe callable supply. A registry listing alone is not
# evidence that the listed agent currently intends to buy an external service.
FEDERATED_A2A_BUYER_CONTACT_ENABLED = False

_START_LOCK = Lock()
_RUNTIME_LOCK = Lock()
_ROTATION_LOCK = Lock()
_STARTED = False
_ROTATION_CURSOR = None
_RUNTIME_STATE = {
    "cycle_state": "not_started",
    "cycle_started_at": None,
    "cycle_completed_at": None,
    "active_worker_ids": [],
    "completed_worker_ids": [],
    "last_cycle_worker_ids": [],
    "current_worker_id": None,
    "last_error": None,
}


def _runtime_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_cycle_start(active_workers) -> None:
    worker_ids = [worker.id for worker in active_workers]
    with _RUNTIME_LOCK:
        _RUNTIME_STATE.update(
            {
                "cycle_state": "running",
                "cycle_started_at": _runtime_now(),
                "cycle_completed_at": None,
                "active_worker_ids": worker_ids,
                "completed_worker_ids": [],
                "current_worker_id": None,
                "last_error": None,
            }
        )


def _runtime_worker_started(worker_id: str) -> None:
    with _RUNTIME_LOCK:
        if _RUNTIME_STATE.get("cycle_state") == "running":
            _RUNTIME_STATE["current_worker_id"] = worker_id


def _runtime_worker_completed(worker_id: str) -> None:
    with _RUNTIME_LOCK:
        completed = list(_RUNTIME_STATE.get("completed_worker_ids") or [])
        if worker_id not in completed:
            completed.append(worker_id)
        _RUNTIME_STATE["completed_worker_ids"] = completed
        if _RUNTIME_STATE.get("current_worker_id") == worker_id:
            _RUNTIME_STATE["current_worker_id"] = None


def _runtime_cycle_completed() -> None:
    with _RUNTIME_LOCK:
        last_ids = list(_RUNTIME_STATE.get("active_worker_ids") or [])
        _RUNTIME_STATE.update(
            {
                "cycle_state": "sleeping",
                "cycle_completed_at": _runtime_now(),
                "last_cycle_worker_ids": last_ids,
                "active_worker_ids": [],
                "current_worker_id": None,
                "last_error": None,
            }
        )


def _runtime_cycle_error(error_name: str) -> None:
    with _RUNTIME_LOCK:
        last_ids = list(_RUNTIME_STATE.get("active_worker_ids") or [])
        _RUNTIME_STATE.update(
            {
                "cycle_state": "error",
                "cycle_completed_at": _runtime_now(),
                "last_cycle_worker_ids": last_ids,
                "active_worker_ids": [],
                "current_worker_id": None,
                "last_error": str(error_name or "unknown")[:160],
            }
        )


def acquisition_runtime_snapshot() -> dict:
    with _RUNTIME_LOCK:
        return {
            "cycle_state": _RUNTIME_STATE["cycle_state"],
            "cycle_started_at": _RUNTIME_STATE["cycle_started_at"],
            "cycle_completed_at": _RUNTIME_STATE["cycle_completed_at"],
            "active_worker_ids": list(_RUNTIME_STATE["active_worker_ids"]),
            "completed_worker_ids": list(_RUNTIME_STATE["completed_worker_ids"]),
            "last_cycle_worker_ids": list(_RUNTIME_STATE["last_cycle_worker_ids"]),
            "current_worker_id": _RUNTIME_STATE["current_worker_id"],
            "last_error": _RUNTIME_STATE["last_error"],
        }


def _aware(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes"}


def _bounded_interval_seconds() -> int:
    raw = os.getenv("AION_ACQUISITION_SWARM_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL_SECONDS
    return max(MIN_INTERVAL_SECONDS, min(value, MAX_INTERVAL_SECONDS))


def _queries_for_cycle(
    lane: str,
    query_bank: tuple[str, ...],
    *,
    now_seconds: float | None = None,
) -> tuple[str, ...]:
    """Rotate discovery phrases without increasing per-cycle registry load."""

    if len(query_bank) <= QUERIES_PER_WORKER_PER_CYCLE:
        return tuple(query_bank)
    current = time.time() if now_seconds is None else float(now_seconds)
    slot = int(current // DEFAULT_INTERVAL_SECONDS)
    lane_offset = sum(ord(character) for character in lane)
    start = (slot + lane_offset) % len(query_bank)
    return tuple(
        query_bank[(start + index) % len(query_bank)]
        for index in range(QUERIES_PER_WORKER_PER_CYCLE)
    )


def _moltbook_query_for_cycle(
    lane: str,
    query_bank: tuple[str, ...],
    *,
    now_seconds: float | None = None,
) -> str:
    current = time.time() if now_seconds is None else float(now_seconds)
    slot = int(current // DEFAULT_INTERVAL_SECONDS)
    lane_offset = sum(ord(character) for character in lane)
    return query_bank[(slot + lane_offset) % len(query_bank)]


def _bounded_active_worker_count() -> int:
    raw = os.getenv(
        "AION_ACQUISITION_ACTIVE_WORKERS_PER_CYCLE",
        str(DEFAULT_ACTIVE_WORKERS_PER_CYCLE),
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_ACTIVE_WORKERS_PER_CYCLE
    return max(1, min(value, WORKER_COUNT))


def _active_worker_specs_for_cycle(
    *, now_seconds: float | None = None
) -> tuple:
    """Rotate real assignments across the transparent 100-worker force.

    Worker count is capability/ownership topology, not permission to generate
    unbounded network traffic. Shared transport health and channel limits remain
    authoritative.
    """

    count = _bounded_active_worker_count()
    workers = tuple(ACQUISITION_WORKERS)
    if count >= len(workers):
        return workers
    current = time.time() if now_seconds is None else float(now_seconds)
    slot = int(current // DEFAULT_INTERVAL_SECONDS)
    start = (slot * count) % len(workers)
    return tuple(
        workers[(start + offset) % len(workers)]
        for offset in range(count)
    )


def _next_active_worker_specs(
    *, now_seconds: float | None = None
) -> tuple:
    """Advance the real 100-worker rotation by completed-cycle order.

    Wall-clock slots seed the first cohort after process start only. Later
    cohorts advance by the active cohort size, so variable external-discovery
    duration cannot starve a worker cohort.
    """

    global _ROTATION_CURSOR
    count = _bounded_active_worker_count()
    workers = tuple(ACQUISITION_WORKERS)
    if count >= len(workers):
        return workers
    with _ROTATION_LOCK:
        if _ROTATION_CURSOR is None:
            current = time.time() if now_seconds is None else float(now_seconds)
            slot = int(current // DEFAULT_INTERVAL_SECONDS)
            _ROTATION_CURSOR = (slot * count) % len(workers)
        start = int(_ROTATION_CURSOR) % len(workers)
        selected = tuple(
            workers[(start + offset) % len(workers)]
            for offset in range(count)
        )
        _ROTATION_CURSOR = (start + count) % len(workers)
    return selected


def _reset_rotation_cursor_for_tests(value: int | None = None) -> None:
    global _ROTATION_CURSOR
    with _ROTATION_LOCK:
        _ROTATION_CURSOR = value


def _cycle_sleep_seconds(
    cycle_started_monotonic: float,
    *,
    now_monotonic: float | None = None,
) -> float:
    current = time.monotonic() if now_monotonic is None else float(now_monotonic)
    elapsed = max(0.0, current - float(cycle_started_monotonic))
    return max(0.0, float(_bounded_interval_seconds()) - elapsed)


def _registry_queries_for_cycle(
    queries: tuple[str, ...],
    *,
    moltbook_ready: bool,
    moltbook_outbound_blocked: bool,
    moltbook_created: int,
) -> tuple[str, ...]:
    """Keep federated A2A discovery parallel instead of making one platform a choke point."""

    if not moltbook_ready or moltbook_outbound_blocked or moltbook_created == 0:
        return tuple(queries)
    return tuple(queries[:1])


def _mind_transport_policy(
    mind_plan: dict | None,
    fallback_queries: tuple[str, ...],
) -> dict:
    """Translate an AI plan into bounded executor permissions.

    A model plan can narrow the existing executor but can never expand its
    contact, dedupe, authentication, platform or payment authority. Low
    self-reported confidence is advisory only: deterministic buyer-intent
    queries and the executor's existing safety controls remain authoritative.
    """

    confidence = 0
    if mind_plan:
        try:
            confidence = int(mind_plan.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0

    if not mind_plan or confidence < MIN_MODEL_TRANSPORT_CONFIDENCE:
        return {
            "model_controls_transport": False,
            "queries": tuple(fallback_queries)[:QUERIES_PER_WORKER_PER_CYCLE],
            "channels": {"moltbook", "colony", "federated_a2a"},
            "discover_allowed": True,
            "contact_allowed": True,
        }

    channels = {
        str(channel)
        for channel in (mind_plan.get("channel_priority") or [])
        if str(channel) in {"moltbook", "colony", "federated_a2a", "hold"}
    }
    contact_policy = str(mind_plan.get("contact_policy") or "discover_only")
    hard_hold = "hold" in channels or contact_policy == "hold"
    if hard_hold:
        return {
            "model_controls_transport": True,
            "queries": (),
            "channels": set(),
            "discover_allowed": False,
            "contact_allowed": False,
        }

    queries = tuple(
        str(query).strip()[:128]
        for query in (mind_plan.get("search_queries") or fallback_queries)
        if str(query).strip()
    )[:QUERIES_PER_WORKER_PER_CYCLE]
    return {
        "model_controls_transport": True,
        "queries": queries or tuple(fallback_queries)[:QUERIES_PER_WORKER_PER_CYCLE],
        "channels": channels & {"moltbook", "colony", "federated_a2a"},
        "discover_allowed": True,
        "contact_allowed": contact_policy == "contact_one_if_qualified",
    }


def _contact_allowed_for_actionable_target(
    mind_policy: dict, target: models.AmbassadorTarget
) -> bool:
    """Allow one bounded contact when discovery found an actionable target.

    Model planning may narrow transport, but ``discover_only`` is not a
    material blocker once a verified buyer-intent target is qualified. A hard
    hold (or a channel the model explicitly excluded) still remains binding.
    """

    if not mind_policy.get("discover_allowed"):
        return False
    if "hold" in (mind_policy.get("channels") or set()):
        return False
    source = str(getattr(target, "discovery_source", "") or "")
    allowed_channels = mind_policy.get("channels") or set()
    return source in allowed_channels or (
        source not in {"moltbook", "colony"} and "federated_a2a" in allowed_channels
    )


def _outbound_preflight(db: Session, intent_profile: str) -> dict:
    """Run existing zero-price preflight before consuming an outbound slot."""

    need = MOLTBOOK_INTENT_QUERIES[intent_profile][0]
    try:
        result = pre_spend_preflight_data(db, {"need": need})
    except PreSpendPreflightError:
        return {
            "decision": "HOLD",
            "reason_code": "bounded_preflight_validation_error",
            "qualified_route_available": False,
            "need_source": "deterministic_intent_lane_not_buyer_quote",
        }
    return {
        "decision": str(result.get("decision") or "HOLD"),
        "reason_code": str(result.get("reason_code") or "unknown")[:80],
        "qualified_route_available": bool(result.get("qualified_route_available")),
        "need_source": "deterministic_intent_lane_not_buyer_quote",
    }


def _worker_daily_plan() -> dict:
    return {
        "new_unique_targets": DAILY_NEW_TARGET_GOAL_PER_WORKER,
        "unique_contact_attempts": DAILY_CONTACT_GOAL_PER_WORKER,
        "valid_machine_responses": DAILY_RESPONSE_GOAL_PER_WORKER,
        "sales_quota": None,
        "sales_truth": (
            "A worker cannot guarantee buyer payment. The swarm is held accountable "
            "for controllable funnel activity; the shared North Star is the first real SAT."
        ),
    }


def _recent_global_scan_lane(*, now_seconds: float | None = None) -> str:
    """Compatibility view of the lane owning the one global recent scan."""

    active = _active_worker_specs_for_cycle(now_seconds=now_seconds)
    if not active:
        return tuple(INTENT_WORKERS)[0]
    return active[0].intent_profile


def _daily_worker_accountability(
    db: Session,
    worker_id: str,
    *,
    intent_profile: str,
    send_enabled: bool,
    cycle_new_targets: int,
    contact_attempted_this_cycle: bool,
) -> dict:
    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    campaign_ids = select(models.AmbassadorCampaign.id).where(
        models.AmbassadorCampaign.name.like(
            _campaign_prefix(worker_id, intent_profile) + "%"
        )
    )
    target_ids = select(models.AmbassadorTarget.id).where(
        models.AmbassadorTarget.campaign_id.in_(campaign_ids)
    )

    new_targets = db.scalar(
        select(func.count())
        .select_from(models.AmbassadorTarget)
        .where(
            models.AmbassadorTarget.campaign_id.in_(campaign_ids),
            models.AmbassadorTarget.created_at >= day_start,
        )
    ) or 0
    contacts = db.scalar(
        select(func.count())
        .select_from(models.AmbassadorContactAttempt)
        .where(
            models.AmbassadorContactAttempt.target_id.in_(target_ids),
            models.AmbassadorContactAttempt.created_at >= day_start,
        )
    ) or 0
    responses = db.scalar(
        select(func.count())
        .select_from(models.AmbassadorContactAttempt)
        .where(
            models.AmbassadorContactAttempt.target_id.in_(target_ids),
            models.AmbassadorContactAttempt.created_at >= day_start,
            models.AmbassadorContactAttempt.response_received.is_(True),
        )
    ) or 0

    plan = _worker_daily_plan()
    if (
        contacts >= DAILY_CONTACT_GOAL_PER_WORKER
        and responses >= DAILY_RESPONSE_GOAL_PER_WORKER
    ):
        status = "PLAN_MET"
        blocker = None
        next_action = "continue_only_if_new_unique_intent_exists"
    elif not send_enabled:
        status = "BLOCKED"
        blocker = "outbound_disabled"
        next_action = "restore_authorized_outbound_gate"
    elif cycle_new_targets == 0 and not contact_attempted_this_cycle:
        status = "BEHIND_PLAN"
        blocker = "discovery_pool_exhausted_or_duplicate"
        next_action = "rotate_discovery_queries"
    else:
        status = "WORKING"
        blocker = None
        next_action = "continue_unique_intent_outreach"

    return {
        "status": status,
        "blocker": blocker,
        "plan": plan,
        "today": {
            "new_unique_targets": int(new_targets),
            "unique_contact_attempts": int(contacts),
            "valid_machine_responses": int(responses),
        },
        "remaining": {
            "new_unique_targets": max(
                0, DAILY_NEW_TARGET_GOAL_PER_WORKER - int(new_targets)
            ),
            "unique_contact_attempts": max(
                0, DAILY_CONTACT_GOAL_PER_WORKER - int(contacts)
            ),
            "valid_machine_responses": max(
                0, DAILY_RESPONSE_GOAL_PER_WORKER - int(responses)
            ),
        },
        "next_action": next_action,
    }


def _campaign_prefix(worker_id: str, intent_profile: str) -> str:
    return f"Intent swarm {intent_profile}@{worker_id} #"


def _legacy_campaign_for_intent(
    db: Session,
    intent_profile: str,
) -> models.AmbassadorCampaign | None:
    """Drain pre-100-worker campaigns before creating replacement inventory."""

    prefix = f"Intent swarm {intent_profile} #"
    campaigns = list(
        db.scalars(
            select(models.AmbassadorCampaign)
            .where(models.AmbassadorCampaign.name.like(prefix + "%"))
            .order_by(models.AmbassadorCampaign.id.asc())
        )
    )
    for campaign in campaigns:
        count = db.scalar(
            select(func.count())
            .select_from(models.AmbassadorTarget)
            .where(models.AmbassadorTarget.campaign_id == campaign.id)
        ) or 0
        if campaign.state in {"draft", "ready"} and count < campaign.maximum_targets:
            return campaign
        unsent = db.scalar(
            select(func.count())
            .select_from(models.AmbassadorTarget)
            .where(
                models.AmbassadorTarget.campaign_id == campaign.id,
                models.AmbassadorTarget.qualification_state == "qualified",
                models.AmbassadorTarget.contact_state == "not_ready",
                models.AmbassadorTarget.suppressed.is_(False),
            )
        ) or 0
        if campaign.state in {"draft", "ready"} and unsent > 0:
            return campaign
    return None


def _campaign_for_worker(
    db: Session,
    *,
    worker_id: str,
    intent_profile: str,
    allow_legacy: bool,
) -> models.AmbassadorCampaign:
    prefix = _campaign_prefix(worker_id, intent_profile)
    campaigns = list(
        db.scalars(
            select(models.AmbassadorCampaign)
            .where(models.AmbassadorCampaign.name.like(prefix + "%"))
            .order_by(models.AmbassadorCampaign.id.desc())
        )
    )
    for campaign in campaigns:
        count = db.scalar(
            select(func.count())
            .select_from(models.AmbassadorTarget)
            .where(models.AmbassadorTarget.campaign_id == campaign.id)
        ) or 0
        if campaign.state in {"draft", "ready"} and count < campaign.maximum_targets:
            return campaign
        unsent = db.scalar(
            select(func.count())
            .select_from(models.AmbassadorTarget)
            .where(
                models.AmbassadorTarget.campaign_id == campaign.id,
                models.AmbassadorTarget.qualification_state == "qualified",
                models.AmbassadorTarget.contact_state == "not_ready",
                models.AmbassadorTarget.suppressed.is_(False),
            )
        ) or 0
        if campaign.state in {"draft", "ready"} and unsent > 0:
            return campaign

    if allow_legacy:
        legacy = _legacy_campaign_for_intent(db, intent_profile)
        if legacy is not None:
            return legacy

    generation = len(campaigns) + 1
    created = create_campaign(
        db,
        name=f"{prefix}{generation}",
        purpose=(
            "Intent-first machine acquisition by a transparent AION-operated worker: "
            "find agents with provider-selection or external-spend needs and offer "
            "AION pre-spend preflight before any join."
        ),
        maximum_targets=MAX_CAMPAIGN_TARGETS,
        maximum_contacts=MAX_CAMPAIGN_TARGETS,
    )
    campaign = db.scalar(
        select(models.AmbassadorCampaign).where(
            models.AmbassadorCampaign.campaign_id == created["campaign_id"]
        )
    )
    if campaign is None:
        raise RuntimeError("Intent swarm campaign creation did not persist")
    return campaign

def _qualified_unsent_target(
    db: Session,
    campaign: models.AmbassadorCampaign,
    *,
    allow_moltbook: bool,
    allow_colony: bool = False,
    allow_federated: bool = True,
) -> models.AmbassadorTarget | None:
    base = (
        select(models.AmbassadorTarget)
        .where(
            models.AmbassadorTarget.campaign_id == campaign.id,
            models.AmbassadorTarget.qualification_state == "qualified",
            models.AmbassadorTarget.contact_state == "not_ready",
            models.AmbassadorTarget.suppressed.is_(False),
        )
    )
    if allow_moltbook:
        moltbook = db.scalar(
            base.where(models.AmbassadorTarget.discovery_source == "moltbook")
            .order_by(models.AmbassadorTarget.id)
            .limit(1)
        )
        if moltbook is not None:
            return moltbook
    if allow_colony:
        colony = db.scalar(
            base.where(models.AmbassadorTarget.discovery_source == "colony")
            .order_by(models.AmbassadorTarget.id)
            .limit(1)
        )
        if colony is not None:
            return colony
    if not allow_federated:
        return None
    return db.scalar(
        base.where(
            ~models.AmbassadorTarget.discovery_source.in_(("moltbook", "colony"))
        )
        .order_by(models.AmbassadorTarget.id)
        .limit(1)
    )


def _colony_comments_today(db: Session) -> int:
    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(
        db.scalar(
            select(func.count())
            .select_from(models.AmbassadorContactAttempt)
            .join(models.AmbassadorTarget)
            .where(
                models.AmbassadorTarget.discovery_source == "colony",
                models.AmbassadorContactAttempt.created_at >= day_start,
            )
        )
        or 0
    )


def _moltbook_channel_contacts_today(db: Session, *, dm: bool) -> int:
    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    statement = (
        select(func.count())
        .select_from(models.AmbassadorContactAttempt)
        .join(models.AmbassadorTarget)
        .where(
            models.AmbassadorTarget.discovery_source == "moltbook",
            models.AmbassadorContactAttempt.created_at >= day_start,
        )
    )
    if dm:
        statement = statement.where(
            models.AmbassadorContactAttempt.idempotency_key.like("dm-%")
        )
    else:
        statement = statement.where(
            ~models.AmbassadorContactAttempt.idempotency_key.like("dm-%")
        )
    return int(db.scalar(statement) or 0)


def _moltbook_comments_today(db: Session) -> int:
    return _moltbook_channel_contacts_today(db, dm=False)


def _seconds_until_moltbook_comment_allowed(db: Session) -> float:
    latest = db.scalar(
        select(models.AmbassadorContactAttempt.created_at)
        .join(models.AmbassadorTarget)
        .where(
            models.AmbassadorTarget.discovery_source == "moltbook",
            ~models.AmbassadorContactAttempt.idempotency_key.like("dm-%"),
        )
        .order_by(models.AmbassadorContactAttempt.created_at.desc())
        .limit(1)
    )
    if latest is None:
        return 0.0
    elapsed = (
        datetime.now(timezone.utc) - _aware(latest)
    ).total_seconds()
    return max(0.0, MOLTBOOK_MIN_COMMENT_INTERVAL_SECONDS - elapsed)


def _moltbook_dm_requests_today(db: Session) -> int:
    return _moltbook_channel_contacts_today(db, dm=True)


def _safe_response_snapshot_from_report(report: dict) -> dict:
    aggregate = report.get("aggregate") if isinstance(report, dict) else {}
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    routing_feedback = []
    for conversation in (report.get("conversations") or []) if isinstance(report, dict) else []:
        if not isinstance(conversation, dict):
            continue
        for item in conversation.get("safe_evidence") or []:
            if not isinstance(item, dict) or item.get("kind") != "routing_feedback_v1":
                continue
            row = {
                "routing_need": item.get("routing_need"),
                "currency": item.get("currency"),
            }
            if item.get("requester_max_price") is not None:
                row["requester_max_price"] = item.get("requester_max_price")
            if item.get("candidate_identifier") is not None:
                row["candidate_identifier"] = item.get("candidate_identifier")
            routing_feedback.append(row)
    return {
        "responses": int(aggregate.get("responses") or 0),
        "captured_conversations": int(aggregate.get("captured_conversations") or 0),
        "explicit_signal_counts": dict(aggregate.get("explicit_signal_distinct_target_counts") or {}),
        "inferred_signal_counts": dict(aggregate.get("inferred_signal_distinct_target_counts") or {}),
        "routing_feedback": routing_feedback[:5],
    }


def _campaign_response_snapshot(db: Session, campaign_id: str) -> dict:
    return _safe_response_snapshot_from_report(
        campaign_intelligence_report(db, campaign_id)
    )


def run_intent_acquisition_cycle(db: Session, *, send: bool | None = None) -> dict:
    """Run one bounded discovery/contact cycle across the 100-worker force."""

    send_enabled = (
        _env_enabled("AION_AMBASSADOR_OUTBOUND_ENABLED")
        and _env_enabled("AION_AMBASSADOR_OPERATOR")
        if send is None
        else bool(send)
    )
    active_workers = _next_active_worker_specs()

    colony_state = colony_account_status()
    colony_ready = bool(colony_state.get("authenticated"))

    moltbook_state = moltbook_account_status()
    moltbook_ready = bool(moltbook_state.get("claimed"))
    moltbook_dm_state = moltbook_dm_check() if moltbook_ready else {
        "status": "unavailable",
        "has_activity": False,
        "pending_request_count": 0,
        "unread_count": 0,
    }

    current_moltbook_outbound = moltbook_outbound_status()
    channel_health = {
        "moltbook": {
            "configured": bool(moltbook_state.get("configured")),
            "claimed": moltbook_ready,
            "suspended": bool(current_moltbook_outbound.get("suspended")),
            "suspended_until": current_moltbook_outbound.get("suspended_until"),
        },
        "colony": {
            "public_discovery": True,
            "authenticated_write": colony_ready,
        },
        "federated_a2a": {
            "public_discovery": True,
            "buyer_outbound_contact": FEDERATED_A2A_BUYER_CONTACT_ENABLED,
            "one_contact_per_target": True,
            "truth": "registry_supply_is_not_verified_buyer_intent",
        },
    }
    fallback_queries_by_worker = {
        worker.id: list(
            _queries_for_cycle(
                worker.id,
                INTENT_WORKERS[worker.intent_profile],
            )
        )
        for worker in ACQUISITION_WORKERS
    }
    mind_plans = refresh_all_minds(
        tuple(ACQUISITION_WORKERS),
        channel_health=channel_health,
        send_enabled=send_enabled,
        fallback_queries_by_worker=fallback_queries_by_worker,
    )

    active_mind_policies = {}
    for worker in active_workers:
        fallback = tuple(
            fallback_queries_by_worker.get(worker.id)
            or _queries_for_cycle(
                worker.id,
                INTENT_WORKERS[worker.intent_profile],
            )
        )
        active_mind_policies[worker.id] = _mind_transport_policy(
            mind_plans.get(worker.id),
            fallback,
        )

    colony_candidates = [
        worker.id
        for worker in active_workers
        if active_mind_policies[worker.id]["discover_allowed"]
        and "colony" in active_mind_policies[worker.id]["channels"]
    ]
    colony_scout_worker_ids = set(
        colony_candidates[:MAX_COLONY_SCOUT_WORKERS_PER_CYCLE]
    )
    moltbook_recent_scan_worker_id = next(
        (
            worker.id
            for worker in active_workers
            if active_mind_policies[worker.id]["discover_allowed"]
            and "moltbook" in active_mind_policies[worker.id]["channels"]
        ),
        None,
    )
    colony_paid_scan_worker_id = colony_candidates[0] if colony_candidates else None
    _runtime_cycle_start(active_workers)

    colony_comments_today = _colony_comments_today(db)
    colony_comments_remaining_cycle = min(
        MAX_COLONY_COMMENTS_PER_CYCLE,
        max(0, MAX_COLONY_COMMENTS_PER_DAY - colony_comments_today),
    )
    moltbook_comments_today = _moltbook_comments_today(db)
    moltbook_comments_remaining_today = max(
        0, MOLTBOOK_DAILY_COMMENT_LIMIT - moltbook_comments_today
    )
    moltbook_comments_remaining_cycle = min(
        MOLTBOOK_MAX_COMMENTS_PER_CYCLE,
        moltbook_comments_remaining_today,
    )
    moltbook_dm_requests_today = _moltbook_dm_requests_today(db)
    moltbook_dm_remaining_today = max(
        0, MOLTBOOK_DM_DAILY_REQUEST_LIMIT - moltbook_dm_requests_today
    )
    moltbook_dm_remaining_cycle = min(
        MOLTBOOK_DM_MAX_REQUESTS_PER_CYCLE,
        moltbook_dm_remaining_today,
    )

    report = {
        "action": "intent_acquisition_cycle",
        "workers": {},
        "worker_count": WORKER_COUNT,
        "active_worker_count": len(active_workers),
        "active_worker_ids": [worker.id for worker in active_workers],
        "theoretical_unique_target_capacity": WORKER_COUNT * MAX_CAMPAIGN_TARGETS,
        "send_enabled": send_enabled,
        "contacts_attempted": 0,
        "contacts_delivered_or_responded": 0,
        "daily_worker_plan": _worker_daily_plan(),
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "primary_acquisition_channel": "ai_selected_per_worker",
        "acquisition_channel_strategy": "ai_minds_over_bounded_multichannel_transport",
        "mind_runtime": acquisition_mind_runtime_status(),
        "minds_planned_this_cycle": len(mind_plans),
        "moltbook_recent_global_scan_worker": moltbook_recent_scan_worker_id,
        "colony_paid_task_scan_worker": colony_paid_scan_worker_id,
        "colony": {
            "configured": bool(colony_state.get("configured")),
            "authenticated": colony_ready,
            "status": colony_state.get("status"),
            "public_discovery_enabled": True,
            "paid_task_discovery_enabled": True,
            "scout_worker_ids": sorted(colony_scout_worker_ids),
            "comments_today": colony_comments_today,
            "internal_daily_comment_limit": MAX_COLONY_COMMENTS_PER_DAY,
            "max_comments_per_cycle": MAX_COLONY_COMMENTS_PER_CYCLE,
            "comments_attempted_this_cycle": 0,
            "platform_numeric_daily_limit_published": False,
        },
        "moltbook": {
            "configured": bool(moltbook_state.get("configured")),
            "claimed": moltbook_ready,
            "status": moltbook_state.get("status"),
            "error": moltbook_state.get("error"),
            "comments": {
                "official_daily_limit": MOLTBOOK_DAILY_COMMENT_LIMIT,
                "today": moltbook_comments_today,
                "remaining_today": moltbook_comments_remaining_today,
                "max_per_cycle": MOLTBOOK_MAX_COMMENTS_PER_CYCLE,
                "minimum_interval_seconds": MOLTBOOK_MIN_COMMENT_INTERVAL_SECONDS,
                "attempted_this_cycle": 0,
            },
            "dm": {
                "initial_daily_request_limit": MOLTBOOK_DM_DAILY_REQUEST_LIMIT,
                "requests_today": moltbook_dm_requests_today,
                "requests_remaining_today": moltbook_dm_remaining_today,
                "max_requests_per_cycle": MOLTBOOK_DM_MAX_REQUESTS_PER_CYCLE,
                "requests_attempted_this_cycle": 0,
                "platform_numeric_daily_limit_published": False,
                "outbound_enabled": moltbook_dm_outbound_enabled(),
                "activity_status": moltbook_dm_state.get("status"),
                "activity_error": moltbook_dm_state.get("error"),
                "pending_incoming_requests": int(
                    moltbook_dm_state.get("pending_request_count") or 0
                ),
                "unread_messages": int(moltbook_dm_state.get("unread_count") or 0),
            },
            "daily_contact_limit": MOLTBOOK_DAILY_COMMENT_LIMIT,
            "contacts_today": moltbook_comments_today,
            "contacts_remaining_today": moltbook_comments_remaining_today,
            "max_contacts_per_cycle": MOLTBOOK_MAX_COMMENTS_PER_CYCLE,
            "contacts_attempted_this_cycle": 0,
            "suspended": bool(moltbook_outbound_status().get("suspended")),
            "suspended_until": moltbook_outbound_status().get("suspended_until"),
        },
        "truth": (
            "The 100 workers are transparent AION-operated acquisition infrastructure. "
            "When the model runtime is configured, all 100 independently plan from their "
            "own safe durable memory each cycle; only the rotating active cohort can receive "
            "bounded external transport slots. Shared transport health, dedupe and platform "
            "limits remain authoritative. Federated A2A registry discovery is supply "
            "evidence and is not treated as verified buyer intent. Worker count is not "
            "independent adoption, customer proof, SAT or revenue."
        ),
    }

    contacts_remaining = MAX_CONTACTS_PER_CYCLE
    for worker in active_workers:
        worker_id = worker.id
        _runtime_worker_started(worker_id)
        lane = worker.intent_profile
        query_bank = INTENT_WORKERS[lane]
        mind_plan = mind_plans.get(worker_id)
        fallback_queries = tuple(
            fallback_queries_by_worker.get(worker_id)
            or _queries_for_cycle(worker_id, query_bank)
        )
        mind_policy = active_mind_policies[worker_id]
        queries = mind_policy["queries"]
        mind_channels = mind_policy["channels"]
        mind_controls_transport = mind_policy["model_controls_transport"]
        discover_allowed = mind_policy["discover_allowed"]
        allow_moltbook_discovery = (
            discover_allowed and "moltbook" in mind_channels
        )
        allow_colony_discovery = (
            discover_allowed
            and worker_id in colony_scout_worker_ids
            and "colony" in mind_channels
        )
        allow_federated_discovery = (
            discover_allowed and "federated_a2a" in mind_channels
        )
        moltbook_query = (
            queries[0]
            if mind_controls_transport and queries
            else _moltbook_query_for_cycle(
                worker_id,
                MOLTBOOK_INTENT_QUERIES[lane],
            )
        )
        lane_report = {
            "worker_id": worker_id,
            "intent_profile": lane,
            "shard": worker.shard,
            "queries": list(queries),
            "query_bank_size": len(query_bank),
            "moltbook_query": moltbook_query,
            "moltbook_query_bank_size": len(MOLTBOOK_INTENT_QUERIES[lane]),
            "mind": {
                "mode": "model_planned" if mind_plan is not None else "deterministic_fallback",
                "plan": mind_plan,
                "transport_guardrails_authoritative": True,
            },
            "scout_results": [],
            "contact": None,
            "preflight": None,
            "response_intelligence": None,
            "daily_accountability": None,
        }
        report["workers"][worker_id] = lane_report

        try:
            campaign = _campaign_for_worker(
                db,
                worker_id=worker_id,
                intent_profile=lane,
                allow_legacy=worker.shard == 1,
            )
            moltbook_created = 0

            if moltbook_ready and allow_moltbook_discovery:
                if worker_id == moltbook_recent_scan_worker_id:
                    try:
                        recent_result = scout_moltbook_recent_campaign(
                            db,
                            campaign_id=campaign.campaign_id,
                            limit=15,
                        )
                        lane_report["scout_results"].append(recent_result)
                        moltbook_created += len(
                            recent_result.get("created_target_ids") or []
                        )
                    except AmbassadorError as exc:
                        lane_report["scout_results"].append(
                            {
                                "channel": "moltbook_recent_global",
                                "error": exc.code,
                            }
                        )
                try:
                    moltbook_result = scout_moltbook_campaign(
                        db,
                        campaign_id=campaign.campaign_id,
                        query=moltbook_query,
                    )
                    lane_report["scout_results"].append(moltbook_result)
                    moltbook_created += len(
                        moltbook_result.get("created_target_ids") or []
                    )
                except AmbassadorError as exc:
                    lane_report["scout_results"].append(
                        {
                            "channel": "moltbook",
                            "query": moltbook_query,
                            "error": exc.code,
                        }
                    )

            if allow_colony_discovery:
                if worker_id == colony_paid_scan_worker_id:
                    try:
                        colony_paid = scout_colony_paid_tasks_campaign(
                            db,
                            campaign_id=campaign.campaign_id,
                            limit=5,
                        )
                        lane_report["scout_results"].append(colony_paid)
                    except AmbassadorError as exc:
                        lane_report["scout_results"].append(
                            {"channel": "colony_paid_tasks", "error": exc.code}
                        )
                try:
                    colony_result = scout_colony_campaign(
                        db,
                        campaign_id=campaign.campaign_id,
                        query=moltbook_query,
                    )
                    lane_report["scout_results"].append(colony_result)
                except AmbassadorError as exc:
                    lane_report["scout_results"].append(
                        {
                            "channel": "colony",
                            "query": moltbook_query,
                            "error": exc.code,
                        }
                    )

            moltbook_outbound_blocked = bool(
                moltbook_outbound_status().get("suspended")
            )
            registry_queries = _registry_queries_for_cycle(
                queries,
                moltbook_ready=moltbook_ready,
                moltbook_outbound_blocked=moltbook_outbound_blocked,
                moltbook_created=moltbook_created,
            )
            if not allow_federated_discovery:
                registry_queries = ()
            for query in registry_queries:
                current = db.scalar(
                    select(func.count())
                    .select_from(models.AmbassadorTarget)
                    .where(models.AmbassadorTarget.campaign_id == campaign.id)
                ) or 0
                if current >= campaign.maximum_targets:
                    break
                try:
                    lane_report["scout_results"].append(
                        scout_campaign(
                            db,
                            campaign_id=campaign.campaign_id,
                            query=query,
                        )
                    )
                except AmbassadorError as exc:
                    lane_report["scout_results"].append(
                        {"channel": "registry_parallel", "query": query, "error": exc.code}
                    )
                    if exc.code == "campaign_target_limit_reached":
                        break

            if campaign.state != "ready":
                set_campaign_state(db, campaign.campaign_id, "ready")
                db.refresh(campaign)

            cycle_target_ids = [
                target_id
                for item in lane_report["scout_results"]
                if isinstance(item, dict)
                for target_id in (item.get("created_target_ids") or [])
            ]
            cycle_new_targets = len(cycle_target_ids)
            cycle_qualified_targets = 0
            if cycle_target_ids:
                cycle_qualified_targets = int(
                    db.scalar(
                        select(func.count())
                        .select_from(models.AmbassadorTarget)
                        .where(
                            models.AmbassadorTarget.target_id.in_(cycle_target_ids),
                            models.AmbassadorTarget.qualification_state == "qualified",
                        )
                    )
                    or 0
                )
            outbound_state = moltbook_outbound_status()
            target = _qualified_unsent_target(
                db,
                campaign,
                allow_moltbook=(
                    moltbook_comments_remaining_cycle > 0
                    and not bool(outbound_state.get("suspended"))
                    and (
                        not mind_controls_transport
                        or "moltbook" in mind_channels
                    )
                ),
                allow_colony=(
                    colony_ready
                    and colony_comments_remaining_cycle > 0
                    and (
                        not mind_controls_transport
                        or "colony" in mind_channels
                    )
                ),
                # Federated A2A registries are supply discovery, not a verified
                # requester-intent surface. Do not turn provider listings into
                # unsolicited buyer acquisition contacts.
                allow_federated=FEDERATED_A2A_BUYER_CONTACT_ENABLED,
            )
            contact_attempted_this_cycle = False
            outbound_preflight = None
            if (
                target is not None
                and send_enabled
                and _contact_allowed_for_actionable_target(mind_policy, target)
                and contacts_remaining > 0
            ):
                outbound_preflight = _outbound_preflight(db, lane)
                lane_report["preflight"] = outbound_preflight
            if (
                target is not None
                and outbound_preflight is not None
                and outbound_preflight.get("decision") == "GO"
            ):
                report["contacts_attempted"] += 1
                contacts_remaining -= 1
                contact_attempted_this_cycle = True
                if target.discovery_source == "moltbook":
                    moltbook_comments_remaining_cycle -= 1
                    report["moltbook"]["contacts_attempted_this_cycle"] += 1
                    report["moltbook"]["comments"]["attempted_this_cycle"] += 1
                elif target.discovery_source == "colony":
                    colony_comments_remaining_cycle -= 1
                    report["colony"]["comments_attempted_this_cycle"] += 1
                try:
                    if target.discovery_source == "moltbook":
                        wait_seconds = _seconds_until_moltbook_comment_allowed(db)
                        if wait_seconds > 0:
                            time.sleep(wait_seconds)
                    result = prepare_and_send_operator_contact(
                        db,
                        target_id=target.target_id,
                        idempotency_key=f"intent-{worker_id}-{target.target_id}",
                        preflight_result=outbound_preflight,
                    )
                    lane_report["contact"] = {
                        "target_id": target.target_id,
                        "channel": result.get("channel") or target.discovery_source,
                        "result_class": result.get("result_class"),
                        "http_status": result.get("http_status"),
                        "response_received": result.get("response_received"),
                        "platform_error": result.get("platform_error"),
                    }
                    if result.get("result_class") in {"delivered", "response_received"}:
                        report["contacts_delivered_or_responded"] += 1
                except AmbassadorError as exc:
                    lane_report["contact"] = {
                        "target_id": target.target_id,
                        "error": exc.code,
                    }

            lane_report["dm_contact"] = None
            if (
                moltbook_ready
                and moltbook_dm_outbound_enabled()
                and not bool(moltbook_outbound_status().get("suspended"))
                and send_enabled
                and (
                    not mind_controls_transport
                    or "moltbook" in mind_channels
                )
                and contacts_remaining > 0
                and moltbook_dm_remaining_cycle > 0
            ):
                dm_target = _qualified_unsent_target(
                    db,
                    campaign,
                    allow_moltbook=True,
                    allow_colony=False,
                    allow_federated=False,
                )
                if (
                    dm_target is not None
                    and dm_target.discovery_source == "moltbook"
                    and _contact_allowed_for_actionable_target(
                        mind_policy, dm_target
                    )
                ):
                    report["contacts_attempted"] += 1
                    contacts_remaining -= 1
                    moltbook_dm_remaining_cycle -= 1
                    report["moltbook"]["dm"]["requests_attempted_this_cycle"] += 1
                    try:
                        dm_result = prepare_and_send_operator_moltbook_dm(
                            db,
                            target_id=dm_target.target_id,
                            idempotency_key=f"dm-{worker_id}-{dm_target.target_id}",
                        )
                        lane_report["dm_contact"] = {
                            "target_id": dm_target.target_id,
                            "channel": "moltbook_dm",
                            "result_class": dm_result.get("result_class"),
                            "http_status": dm_result.get("http_status"),
                            "platform_error": dm_result.get("platform_error"),
                        }
                        if dm_result.get("result_class") == "delivered":
                            report["contacts_delivered_or_responded"] += 1
                        if dm_result.get("http_status") == 429:
                            moltbook_dm_remaining_cycle = 0
                    except AmbassadorError as exc:
                        report["contacts_attempted"] -= 1
                        contacts_remaining += 1
                        moltbook_dm_remaining_cycle += 1
                        report["moltbook"]["dm"]["requests_attempted_this_cycle"] -= 1
                        lane_report["dm_contact"] = {
                            "target_id": dm_target.target_id,
                            "error": exc.code,
                            "network_attempt_performed": False,
                        }

            lane_report["response_intelligence"] = _campaign_response_snapshot(
                db, campaign.campaign_id
            )
            lane_report["daily_accountability"] = _daily_worker_accountability(
                db,
                worker_id,
                intent_profile=lane,
                send_enabled=send_enabled,
                cycle_new_targets=cycle_new_targets,
                contact_attempted_this_cycle=contact_attempted_this_cycle,
            )
            response_snapshot = lane_report.get("response_intelligence") or {}
            contact_snapshot = lane_report.get("contact") or {}
            record_worker_outcome(
                worker_id,
                {
                    "new_targets": cycle_new_targets,
                    "qualified_targets": cycle_qualified_targets,
                    "contact_attempted": contact_attempted_this_cycle,
                    "channel": contact_snapshot.get("channel"),
                    "result_class": contact_snapshot.get("result_class"),
                    "response_received": bool(
                        contact_snapshot.get("response_received")
                    ),
                    "routing_feedback_count": len(
                        response_snapshot.get("routing_feedback") or []
                    ),
                },
            )
        except Exception as exc:
            lane_report["worker_error"] = type(exc).__name__
        finally:
            _runtime_worker_completed(worker_id)

    final_outbound_state = moltbook_outbound_status()
    report["moltbook"]["suspended"] = bool(
        final_outbound_state.get("suspended")
    )
    report["moltbook"]["suspended_until"] = final_outbound_state.get(
        "suspended_until"
    )
    _runtime_cycle_completed()
    return report


def _worker_loop() -> None:
    while True:
        cycle_started_monotonic = time.monotonic()
        try:
            with SessionLocal() as db:
                report = run_intent_acquisition_cycle(db)
            print(
                "AION_ACQUISITION_SWARM "
                + json.dumps(report, sort_keys=True, separators=(",", ":")),
                flush=True,
            )
        except Exception as exc:
            _runtime_cycle_error(type(exc).__name__)
            print(
                "AION_ACQUISITION_SWARM_ERROR "
                + json.dumps({"error": type(exc).__name__}, sort_keys=True),
                flush=True,
            )
        time.sleep(_cycle_sleep_seconds(cycle_started_monotonic))


def start_acquisition_swarm_if_enabled() -> bool:
    """Start one daemon worker per process only when the production flag is enabled."""

    global _STARTED
    if not _env_enabled("AION_ACQUISITION_SWARM_ENABLED"):
        return False
    with _START_LOCK:
        if _STARTED:
            return True
        thread = Thread(
            target=_worker_loop,
            name="aion-intent-acquisition-swarm",
            daemon=True,
        )
        thread.start()
        _STARTED = True
        return True
