"""Intent-first acquisition workers built on the existing Ambassador control plane.

Workers are transparent AION-operated acquisition lanes, never external members.
They discover public A2A endpoints, qualify them, and perform at most one
Ambassador contact per target through the existing audited sender.
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
from ..db import SessionLocal
from .conversation_intelligence import campaign_intelligence_report
from .ambassador import (
    AmbassadorError,
    MAX_CAMPAIGN_TARGETS,
    create_campaign,
    prepare_and_send_operator_contact,
    scout_campaign,
    scout_moltbook_campaign,
    set_campaign_state,
)
from .moltbook_acquisition import account_status as moltbook_account_status


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
}

MOLTBOOK_INTENT_QUERIES: dict[str, str] = {
    "provider_selection": "I need to choose or pay an external API, agent, tool, or provider for a real task",
    "paid_api_buyers": "I am about to pay for an API, metered service, or x402 resource",
    "agent_wallets": "My AI agent needs to spend money and I need budget, approval, or provider controls",
    "mcp_buyers": "I need a paid MCP tool or server and must decide whether to buy it",
    "a2a_buyers": "I need to hire or pay another agent or A2A service for a real job",
    "data_buyers": "I need to buy search, research, or data API access for a current task",
    "automation_buyers": "I need to pay for browser automation or an external automation provider",
    "inference_buyers": "I need to choose and pay an inference, model API, or LLM gateway provider",
    "fallback_seekers": "My current API or provider is failing and I need a paid replacement or fallback",
    "agent_commerce": "My autonomous agent needs to procure an external service before spending money",
}

MAX_WORKERS_PER_CYCLE = len(INTENT_WORKERS)
MAX_CONTACTS_PER_CYCLE = len(INTENT_WORKERS)
DEFAULT_INTERVAL_SECONDS = 15 * 60
MIN_INTERVAL_SECONDS = 15 * 60
MAX_INTERVAL_SECONDS = 24 * 60 * 60
QUERIES_PER_WORKER_PER_CYCLE = 2
DAILY_NEW_TARGET_GOAL_PER_WORKER = 20
DAILY_CONTACT_GOAL_PER_WORKER = 10
DAILY_RESPONSE_GOAL_PER_WORKER = 2
MOLTBOOK_DAILY_CONTACT_LIMIT = 40
MOLTBOOK_MAX_CONTACTS_PER_CYCLE = 2

_START_LOCK = Lock()
_STARTED = False


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


def _daily_worker_accountability(
    db: Session,
    lane: str,
    *,
    send_enabled: bool,
    cycle_new_targets: int,
    contact_attempted_this_cycle: bool,
) -> dict:
    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    campaign_ids = select(models.AmbassadorCampaign.id).where(
        models.AmbassadorCampaign.name.like(_campaign_prefix(lane) + "%")
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


def _campaign_prefix(lane: str) -> str:
    return f"Intent swarm {lane} #"


def _campaign_for_lane(db: Session, lane: str) -> models.AmbassadorCampaign:
    prefix = _campaign_prefix(lane)
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

    generation = len(campaigns) + 1
    created = create_campaign(
        db,
        name=f"{prefix}{generation}",
        purpose=(
            "Intent-first machine acquisition: find agents with provider-selection or "
            "external-spend needs and offer AION pre-spend preflight before any join."
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
    return db.scalar(
        base.where(models.AmbassadorTarget.discovery_source != "moltbook")
        .order_by(models.AmbassadorTarget.id)
        .limit(1)
    )


def _moltbook_contacts_today(db: Session) -> int:
    day_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return int(
        db.scalar(
            select(func.count())
            .select_from(models.AmbassadorContactAttempt)
            .join(models.AmbassadorTarget)
            .where(
                models.AmbassadorTarget.discovery_source == "moltbook",
                models.AmbassadorContactAttempt.created_at >= day_start,
            )
        )
        or 0
    )


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
    """Run one bounded discovery/contact cycle across independent intent lanes."""

    send_enabled = (
        _env_enabled("AION_AMBASSADOR_OUTBOUND_ENABLED")
        and _env_enabled("AION_AMBASSADOR_OPERATOR")
        if send is None
        else bool(send)
    )
    moltbook_state = moltbook_account_status()
    moltbook_ready = bool(moltbook_state.get("claimed"))
    moltbook_contacts_today = _moltbook_contacts_today(db)
    moltbook_contacts_remaining_today = max(
        0, MOLTBOOK_DAILY_CONTACT_LIMIT - moltbook_contacts_today
    )
    moltbook_contacts_remaining_cycle = min(
        MOLTBOOK_MAX_CONTACTS_PER_CYCLE,
        moltbook_contacts_remaining_today,
    )

    report = {
        "action": "intent_acquisition_cycle",
        "workers": {},
        "worker_count": len(INTENT_WORKERS),
        "theoretical_unique_target_capacity": len(INTENT_WORKERS) * MAX_CAMPAIGN_TARGETS,
        "send_enabled": send_enabled,
        "contacts_attempted": 0,
        "contacts_delivered_or_responded": 0,
        "daily_worker_plan": _worker_daily_plan(),
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "primary_acquisition_channel": "moltbook",
        "moltbook": {
            "configured": bool(moltbook_state.get("configured")),
            "claimed": moltbook_ready,
            "status": moltbook_state.get("status"),
            "error": moltbook_state.get("error"),
            "daily_contact_limit": MOLTBOOK_DAILY_CONTACT_LIMIT,
            "contacts_today": moltbook_contacts_today,
            "contacts_remaining_today": moltbook_contacts_remaining_today,
            "max_contacts_per_cycle": MOLTBOOK_MAX_CONTACTS_PER_CYCLE,
            "contacts_attempted_this_cycle": 0,
        },
        "truth": (
            "Workers are AION-operated acquisition infrastructure. Their traffic is not "
            "independent adoption, customer proof, SAT or revenue."
        ),
    }

    contacts_remaining = MAX_CONTACTS_PER_CYCLE
    for lane, query_bank in INTENT_WORKERS.items():
        queries = _queries_for_cycle(lane, query_bank)
        lane_report = {
            "worker_id": f"aion-intent-{lane}",
            "queries": list(queries),
            "query_bank_size": len(query_bank),
            "scout_results": [],
            "contact": None,
            "response_intelligence": None,
            "daily_accountability": None,
        }
        report["workers"][lane] = lane_report

        try:
            campaign = _campaign_for_lane(db, lane)
            moltbook_created = 0

            if moltbook_ready:
                try:
                    moltbook_result = scout_moltbook_campaign(
                        db,
                        campaign_id=campaign.campaign_id,
                        query=MOLTBOOK_INTENT_QUERIES[lane],
                    )
                    lane_report["scout_results"].append(moltbook_result)
                    moltbook_created = len(
                        moltbook_result.get("created_target_ids") or []
                    )
                except AmbassadorError as exc:
                    lane_report["scout_results"].append(
                        {
                            "channel": "moltbook",
                            "query": MOLTBOOK_INTENT_QUERIES[lane],
                            "error": exc.code,
                        }
                    )

            # Registries are secondary. Use them when Moltbook is unavailable
            # or this lane produced no fresh Moltbook target.
            fallback_queries = queries if not moltbook_ready else queries[:1]
            if not moltbook_ready or moltbook_created == 0:
                for query in fallback_queries:
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
                            {"channel": "registry_fallback", "query": query, "error": exc.code}
                        )
                        if exc.code == "campaign_target_limit_reached":
                            break

            if campaign.state != "ready":
                set_campaign_state(db, campaign.campaign_id, "ready")
                db.refresh(campaign)

            cycle_new_targets = sum(
                len(item.get("created_target_ids") or [])
                for item in lane_report["scout_results"]
                if isinstance(item, dict)
            )
            target = _qualified_unsent_target(
                db,
                campaign,
                allow_moltbook=moltbook_contacts_remaining_cycle > 0,
            )
            contact_attempted_this_cycle = False
            if (
                target is not None
                and send_enabled
                and contacts_remaining > 0
            ):
                report["contacts_attempted"] += 1
                contacts_remaining -= 1
                contact_attempted_this_cycle = True
                if target.discovery_source == "moltbook":
                    moltbook_contacts_remaining_cycle -= 1
                    report["moltbook"]["contacts_attempted_this_cycle"] += 1
                try:
                    result = prepare_and_send_operator_contact(
                        db,
                        target_id=target.target_id,
                        idempotency_key=f"intent-{lane}-{target.target_id}",
                    )
                    lane_report["contact"] = {
                        "target_id": target.target_id,
                        "channel": result.get("channel") or target.discovery_source,
                        "result_class": result.get("result_class"),
                        "http_status": result.get("http_status"),
                        "response_received": result.get("response_received"),
                    }
                    if result.get("result_class") in {"delivered", "response_received"}:
                        report["contacts_delivered_or_responded"] += 1
                except AmbassadorError as exc:
                    lane_report["contact"] = {
                        "target_id": target.target_id,
                        "error": exc.code,
                    }

            lane_report["response_intelligence"] = _campaign_response_snapshot(
                db, campaign.campaign_id
            )
            lane_report["daily_accountability"] = _daily_worker_accountability(
                db,
                lane,
                send_enabled=send_enabled,
                cycle_new_targets=cycle_new_targets,
                contact_attempted_this_cycle=contact_attempted_this_cycle,
            )
        except Exception as exc:
            lane_report["worker_error"] = type(exc).__name__

    return report


def _worker_loop() -> None:
    while True:
        try:
            with SessionLocal() as db:
                report = run_intent_acquisition_cycle(db)
            print(
                "AION_ACQUISITION_SWARM "
                + json.dumps(report, sort_keys=True, separators=(",", ":")),
                flush=True,
            )
        except Exception as exc:
            print(
                "AION_ACQUISITION_SWARM_ERROR "
                + json.dumps({"error": type(exc).__name__}, sort_keys=True),
                flush=True,
            )
        time.sleep(_bounded_interval_seconds())


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
