"""Intent-first acquisition workers built on the existing Ambassador control plane.

Workers are transparent AION-operated acquisition lanes, never external members.
They discover public A2A endpoints, qualify them, and perform at most one
Ambassador contact per target through the existing audited sender.
"""

from __future__ import annotations

import json
import os
import time
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
    set_campaign_state,
)


INTENT_WORKERS: dict[str, tuple[str, ...]] = {
    "provider_selection": ("provider selection", "tool selection"),
    "paid_api_buyers": ("paid api", "x402 payments"),
    "agent_wallets": ("agent wallet", "spend controls"),
    "mcp_buyers": ("MCP paid tools", "MCP payments"),
    "a2a_buyers": ("A2A agent", "agent collaboration"),
    "data_buyers": ("data api", "search api"),
    "automation_buyers": ("automation tools", "browser tools"),
    "inference_buyers": ("inference api", "LLM gateway"),
    "fallback_seekers": ("provider fallback", "provider reliability"),
    "agent_commerce": ("agent procurement", "agent commerce"),
}
MAX_WORKERS_PER_CYCLE = len(INTENT_WORKERS)
MAX_CONTACTS_PER_CYCLE = len(INTENT_WORKERS)
DEFAULT_INTERVAL_SECONDS = 15 * 60
MIN_INTERVAL_SECONDS = 15 * 60
MAX_INTERVAL_SECONDS = 24 * 60 * 60

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
    db: Session, campaign: models.AmbassadorCampaign
) -> models.AmbassadorTarget | None:
    return db.scalar(
        select(models.AmbassadorTarget)
        .where(
            models.AmbassadorTarget.campaign_id == campaign.id,
            models.AmbassadorTarget.qualification_state == "qualified",
            models.AmbassadorTarget.contact_state == "not_ready",
            models.AmbassadorTarget.suppressed.is_(False),
        )
        .order_by(models.AmbassadorTarget.id)
        .limit(1)
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
    report = {
        "action": "intent_acquisition_cycle",
        "workers": {},
        "worker_count": len(INTENT_WORKERS),
        "theoretical_unique_target_capacity": len(INTENT_WORKERS) * MAX_CAMPAIGN_TARGETS,
        "send_enabled": send_enabled,
        "contacts_attempted": 0,
        "contacts_delivered_or_responded": 0,
        "truth": (
            "Workers are AION-operated acquisition infrastructure. Their traffic is not "
            "independent adoption, customer proof, SAT or revenue."
        ),
    }

    contacts_remaining = MAX_CONTACTS_PER_CYCLE
    for lane, queries in INTENT_WORKERS.items():
        lane_report = {
            "worker_id": f"aion-intent-{lane}",
            "queries": list(queries),
            "scout_results": [],
            "contact": None,
            "response_intelligence": None,
        }
        report["workers"][lane] = lane_report

        try:
            campaign = _campaign_for_lane(db, lane)
            for query in queries:
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
                        {"query": query, "error": exc.code}
                    )
                    if exc.code == "campaign_target_limit_reached":
                        break

            if campaign.state != "ready":
                set_campaign_state(db, campaign.campaign_id, "ready")
                db.refresh(campaign)

            target = _qualified_unsent_target(db, campaign)
            if target is None or not send_enabled or contacts_remaining <= 0:
                continue

            report["contacts_attempted"] += 1
            contacts_remaining -= 1
            try:
                result = prepare_and_send_operator_contact(
                    db,
                    target_id=target.target_id,
                    idempotency_key=f"intent-{lane}-{target.target_id}",
                )
                lane_report["contact"] = {
                    "target_id": target.target_id,
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
