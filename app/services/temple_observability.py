"""Read-only live observability for the AION Temple.

The live view is deliberately derived from durable production truth. It never
creates contacts, mutates campaigns, exposes credentials, returns raw private
responses, or upgrades an attempt into a delivery/SAT.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import re

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .. import models
from ..acquisition import worker_manifest
from ..conversation_models import ConversationEvidence, ConversationIntelligence
from ..payment_models import RouteIntelligencePurchase
from ..public_origin import canonical_public_origin
from ..release_identity import release_identity
from .acquisition_swarm import acquisition_runtime_snapshot
from .acquisition_agent_mind import runtime_status as acquisition_mind_runtime_status
from .moltbook_acquisition import (
    build_outreach_comment,
    outbound_status as moltbook_outbound_status,
)
from .colony_acquisition import (
    configured as colony_configured,
    build_outreach_comment as build_colony_outreach_comment,
)


_CAMPAIGN = re.compile(
    r"^Intent swarm (?P<intent>[A-Za-z0-9_]+)(?:@(?P<worker>aion-[A-Za-z0-9-]{1,80}))? #[0-9]+$"
)
_RECENT_EVENT_LIMIT = 120
_RECENT_TARGET_LIMIT = 240
_MAX_CAMPAIGNS = 1200


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _campaign_identity(name: str | None) -> tuple[str | None, str | None]:
    match = _CAMPAIGN.fullmatch(str(name or ""))
    if match is None:
        return None, None
    return match.group("intent"), match.group("worker")


def _safe_target_url(target: models.AmbassadorTarget) -> str | None:
    value = str(target.agent_card_url or "").strip()
    return value if value.startswith("https://") else None


def _message_preview(
    target: models.AmbassadorTarget,
    intent_profile: str | None,
) -> tuple[str | None, str]:
    if target.discovery_source in {"moltbook", "colony"}:
        prefix = "moltbook:" if target.discovery_source == "moltbook" else "colony:"
        recipient = (
            target.source_identifier.split(":", 1)[1]
            if target.source_identifier.startswith(prefix)
            else None
        )
        try:
            builder = (
                build_outreach_comment
                if target.discovery_source == "moltbook"
                else build_colony_outreach_comment
            )
            return (
                builder(
                    public_base_url=canonical_public_origin(),
                    recipient=recipient,
                    intent=intent_profile,
                ),
                "deterministic_current_template",
            )
        except Exception:
            return None, "unavailable"
    if intent_profile:
        return (
            "AION A2A invitation: contextual pre-spend utility for "
            f"{intent_profile}; one-contact-per-target; route a real need to "
            "/commercial/route-intelligence/preflight before external spend.",
            "safe_semantic_summary",
        )
    return None, "unavailable"


def _recent_intelligence(
    db: Session,
    contact_ids: list[int],
) -> dict[int, dict]:
    if not contact_ids:
        return {}
    evidence_rows = list(
        db.scalars(
            select(ConversationEvidence).where(
                ConversationEvidence.ambassador_contact_id.in_(contact_ids)
            )
        )
    )
    if not evidence_rows:
        return {}
    by_evidence = {
        row.id: row
        for row in evidence_rows
    }
    intelligence_rows = list(
        db.scalars(
            select(ConversationIntelligence)
            .where(ConversationIntelligence.conversation_evidence_id.in_(by_evidence))
            .order_by(ConversationIntelligence.id.desc())
        )
    )
    latest_by_evidence: dict[int, ConversationIntelligence] = {}
    for row in intelligence_rows:
        latest_by_evidence.setdefault(row.conversation_evidence_id, row)

    result = {}
    for evidence in evidence_rows:
        intelligence = latest_by_evidence.get(evidence.id)
        result[evidence.ambassador_contact_id] = {
            "capture_class": evidence.capture_class,
            "safe_evidence": list(evidence.safe_evidence or [])[:5],
            "summary": intelligence.summary if intelligence is not None else None,
            "explicit_signals": (
                list(intelligence.explicit_signals or []) if intelligence is not None else []
            ),
            "inferred_signals": (
                list(intelligence.inferred_signals or []) if intelligence is not None else []
            ),
            "raw_response_persisted": False,
        }
    return result


def build_temple_live_state(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    workers = worker_manifest()
    worker_ids = {worker["id"] for worker in workers}
    runtime = acquisition_runtime_snapshot()
    active_ids = set(runtime.get("active_worker_ids") or [])
    completed_ids = set(runtime.get("completed_worker_ids") or [])
    current_worker_id = runtime.get("current_worker_id")
    mind_rows = {
        row.worker_id: row
        for row in db.scalars(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id.in_(worker_ids)
            )
        )
    }
    mind_state_counts = Counter(
        row.last_state or "unknown" for row in mind_rows.values()
    )
    mind_runtime = {
        **acquisition_mind_runtime_status(),
        "initialized_minds": len(mind_rows),
        "state_counts": dict(sorted(mind_state_counts.items())),
        "reasoning_calls_total": sum(
            int(row.total_reasoning_calls or 0) for row in mind_rows.values()
        ),
        "reasoning_failures_total": sum(
            int(row.reasoning_failures or 0) for row in mind_rows.values()
        ),
    }

    campaigns = list(
        db.scalars(
            select(models.AmbassadorCampaign)
            .where(models.AmbassadorCampaign.name.like("Intent swarm %"))
            .order_by(models.AmbassadorCampaign.id.desc())
            .limit(_MAX_CAMPAIGNS)
        )
    )
    campaign_meta = {}
    campaign_ids_by_worker: dict[str, list[int]] = defaultdict(list)
    latest_campaign_by_worker = {}
    legacy_campaigns = 0
    for campaign in campaigns:
        intent, worker_id = _campaign_identity(campaign.name)
        campaign_meta[campaign.id] = {
            "intent_profile": intent,
            "worker_id": worker_id,
            "campaign_id": campaign.campaign_id,
            "state": campaign.state,
        }
        if worker_id in worker_ids:
            campaign_ids_by_worker[worker_id].append(campaign.id)
            latest_campaign_by_worker.setdefault(worker_id, campaign)
        elif intent is not None:
            legacy_campaigns += 1

    all_campaign_ids = list(campaign_meta)
    target_counts_by_campaign = {}
    qualified_counts_by_campaign = {}
    if all_campaign_ids:
        for campaign_id, total, qualified in db.execute(
            select(
                models.AmbassadorTarget.campaign_id,
                func.count(models.AmbassadorTarget.id),
                func.sum(
                    case(
                        (models.AmbassadorTarget.qualification_state == "qualified", 1),
                        else_=0,
                    )
                ),
            )
            .where(models.AmbassadorTarget.campaign_id.in_(all_campaign_ids))
            .group_by(models.AmbassadorTarget.campaign_id)
        ):
            target_counts_by_campaign[campaign_id] = int(total or 0)
            qualified_counts_by_campaign[campaign_id] = int(qualified or 0)

    contact_counts_by_campaign = {}
    response_counts_by_campaign = {}
    delivered_counts_by_campaign = {}
    if all_campaign_ids:
        for campaign_id, total, responses, delivered in db.execute(
            select(
                models.AmbassadorTarget.campaign_id,
                func.count(models.AmbassadorContactAttempt.id),
                func.sum(
                    case(
                        (models.AmbassadorContactAttempt.response_received.is_(True), 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (
                            models.AmbassadorContactAttempt.result_class.in_(
                                ("delivered", "response_received")
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ),
            )
            .join(
                models.AmbassadorContactAttempt,
                models.AmbassadorContactAttempt.target_id == models.AmbassadorTarget.id,
            )
            .where(models.AmbassadorTarget.campaign_id.in_(all_campaign_ids))
            .group_by(models.AmbassadorTarget.campaign_id)
        ):
            contact_counts_by_campaign[campaign_id] = int(total or 0)
            response_counts_by_campaign[campaign_id] = int(responses or 0)
            delivered_counts_by_campaign[campaign_id] = int(delivered or 0)

    recent_target_rows = list(
        db.execute(
            select(models.AmbassadorTarget, models.AmbassadorCampaign)
            .join(
                models.AmbassadorCampaign,
                models.AmbassadorCampaign.id == models.AmbassadorTarget.campaign_id,
            )
            .where(models.AmbassadorCampaign.name.like("Intent swarm %"))
            .order_by(models.AmbassadorTarget.updated_at.desc(), models.AmbassadorTarget.id.desc())
            .limit(_RECENT_TARGET_LIMIT)
        )
    )
    latest_target_by_worker = {}
    for target, campaign in recent_target_rows:
        intent, worker_id = _campaign_identity(campaign.name)
        if worker_id in worker_ids and worker_id not in latest_target_by_worker:
            latest_target_by_worker[worker_id] = (target, intent)

    recent_contact_rows = list(
        db.execute(
            select(
                models.AmbassadorContactAttempt,
                models.AmbassadorTarget,
                models.AmbassadorCampaign,
            )
            .join(
                models.AmbassadorTarget,
                models.AmbassadorTarget.id == models.AmbassadorContactAttempt.target_id,
            )
            .join(
                models.AmbassadorCampaign,
                models.AmbassadorCampaign.id == models.AmbassadorTarget.campaign_id,
            )
            .where(models.AmbassadorCampaign.name.like("Intent swarm %"))
            .order_by(
                models.AmbassadorContactAttempt.created_at.desc(),
                models.AmbassadorContactAttempt.id.desc(),
            )
            .limit(_RECENT_EVENT_LIMIT)
        )
    )
    intelligence_by_contact = _recent_intelligence(
        db, [contact.id for contact, _, _ in recent_contact_rows]
    )

    latest_contact_by_worker = {}
    recent_events = []
    for contact, target, campaign in recent_contact_rows:
        intent, worker_id = _campaign_identity(campaign.name)
        if worker_id in worker_ids and worker_id not in latest_contact_by_worker:
            latest_contact_by_worker[worker_id] = (contact, target, intent)
        intelligence = intelligence_by_contact.get(contact.id) or {}
        preview, preview_kind = _message_preview(target, intent)
        recent_events.append(
            {
                "event": "contact",
                "worker_id": worker_id or f"legacy:{intent or 'unknown'}",
                "intent_profile": intent,
                "channel": target.discovery_source,
                "target_id": target.target_id,
                "target_identity": target.source_identifier,
                "target_url": _safe_target_url(target),
                "result_class": contact.result_class,
                "http_status": contact.http_status,
                "response_received": bool(contact.response_received),
                "created_at": _iso(contact.created_at),
                "completed_at": _iso(contact.completed_at),
                "outbound_message_preview": preview,
                "outbound_message_preview_kind": preview_kind,
                "conversation": intelligence or None,
            }
        )

    worker_states = []
    for worker in workers:
        worker_id = worker["id"]
        campaign_ids = campaign_ids_by_worker.get(worker_id, [])
        total_targets = sum(target_counts_by_campaign.get(cid, 0) for cid in campaign_ids)
        qualified_targets = sum(
            qualified_counts_by_campaign.get(cid, 0) for cid in campaign_ids
        )
        contacts = sum(contact_counts_by_campaign.get(cid, 0) for cid in campaign_ids)
        delivered = sum(delivered_counts_by_campaign.get(cid, 0) for cid in campaign_ids)
        responses = sum(response_counts_by_campaign.get(cid, 0) for cid in campaign_ids)

        current_target = None
        last_activity = None
        current_channel = None
        current_result = None
        response_summary = None
        response_signals = []

        contact_row = latest_contact_by_worker.get(worker_id)
        if contact_row is not None:
            contact, target, intent = contact_row
            current_channel = target.discovery_source
            current_result = contact.result_class
            last_activity = contact.completed_at or contact.created_at
            intelligence = intelligence_by_contact.get(contact.id) or {}
            response_summary = intelligence.get("summary")
            response_signals = sorted(
                set(
                    (intelligence.get("explicit_signals") or [])
                    + (intelligence.get("inferred_signals") or [])
                )
            )
            preview, preview_kind = _message_preview(target, intent)
            current_target = {
                "target_id": target.target_id,
                "identity": target.source_identifier,
                "url": _safe_target_url(target),
                "qualification_state": target.qualification_state,
                "contact_state": target.contact_state,
                "message_preview": preview,
                "message_preview_kind": preview_kind,
            }
        else:
            target_row = latest_target_by_worker.get(worker_id)
            if target_row is not None:
                target, intent = target_row
                current_channel = target.discovery_source
                last_activity = target.updated_at
                current_target = {
                    "target_id": target.target_id,
                    "identity": target.source_identifier,
                    "url": _safe_target_url(target),
                    "qualification_state": target.qualification_state,
                    "contact_state": target.contact_state,
                    "message_preview": None,
                    "message_preview_kind": "not_contacted",
                }

        if worker_id == current_worker_id:
            state = "working_currently"
        elif worker_id in active_ids and worker_id in completed_ids:
            state = "completed_this_cycle"
        elif worker_id in active_ids:
            state = "assigned_waiting_turn"
        else:
            state = "queued_rotation"
        if current_target and current_target["contact_state"] == "blocked":
            state = "target_blocked_continue_search"

        mind_row = mind_rows.get(worker_id)
        mind_view = {
            "state": "not_initialized",
            "model": acquisition_mind_runtime_status().get("model"),
            "profile": None,
            "plan": None,
            "memory": None,
            "total_reasoning_calls": 0,
            "reasoning_failures": 0,
            "last_reasoned_at": None,
            "last_error": None,
        }
        if mind_row is not None:
            profile = dict(mind_row.cognitive_profile or {})
            plan = dict(mind_row.last_plan or {}) if mind_row.last_plan else None
            memory = dict(mind_row.safe_memory or {})
            mind_view = {
                "state": mind_row.last_state,
                "model": mind_row.model,
                "profile": {
                    "archetype": profile.get("archetype"),
                    "exploration_bias": profile.get("exploration_bias"),
                    "verification_bias": profile.get("verification_bias"),
                    "conversion_bias": profile.get("conversion_bias"),
                    "strategy_fingerprint": profile.get("strategy_fingerprint"),
                },
                "plan": plan,
                "memory": {
                    "recent_outcomes": list(memory.get("recent_outcomes") or [])[-5:],
                    "channel_performance": dict(
                        memory.get("channel_performance") or {}
                    ),
                    "lessons": list(memory.get("lessons") or [])[-5:],
                },
                "total_reasoning_calls": int(
                    mind_row.total_reasoning_calls or 0
                ),
                "reasoning_failures": int(mind_row.reasoning_failures or 0),
                "last_reasoned_at": _iso(mind_row.last_reasoned_at),
                "last_error": mind_row.last_error,
            }

        latest_campaign = latest_campaign_by_worker.get(worker_id)
        worker_states.append(
            {
                **worker,
                "scheduled_now": worker_id in active_ids,
                "state": state,
                "latest_campaign_id": (
                    latest_campaign.campaign_id if latest_campaign is not None else None
                ),
                "latest_campaign_state": (
                    latest_campaign.state if latest_campaign is not None else None
                ),
                "targets_discovered": total_targets,
                "targets_qualified": qualified_targets,
                "contact_attempts": contacts,
                "delivered_contacts": delivered,
                "machine_responses": responses,
                "last_activity_at": _iso(last_activity),
                "current_channel": current_channel,
                "current_result": current_result,
                "current_target": current_target,
                "response_summary": response_summary,
                "response_signals": response_signals,
                "mind": mind_view,
            }
        )

    channel_targets = Counter(
        row[0] or "unknown"
        for row in db.execute(
            select(models.AmbassadorTarget.discovery_source)
        )
    )
    channel_contacts = Counter()
    channel_responses = Counter()
    for source, contacts, responses in db.execute(
        select(
            models.AmbassadorTarget.discovery_source,
            func.count(models.AmbassadorContactAttempt.id),
            func.sum(
                case(
                    (models.AmbassadorContactAttempt.response_received.is_(True), 1),
                    else_=0,
                )
            ),
        )
        .join(
            models.AmbassadorContactAttempt,
            models.AmbassadorContactAttempt.target_id == models.AmbassadorTarget.id,
        )
        .group_by(models.AmbassadorTarget.discovery_source)
    ):
        key = source or "unknown"
        channel_contacts[key] = int(contacts or 0)
        channel_responses[key] = int(responses or 0)

    channel_names = sorted(set(channel_targets) | set(channel_contacts))
    channels = [
        {
            "name": name,
            "targets_discovered": int(channel_targets.get(name, 0)),
            "contact_attempts": int(channel_contacts.get(name, 0)),
            "machine_responses": int(channel_responses.get(name, 0)),
        }
        for name in channel_names
    ]

    inbound_sources = {
        source: int(count)
        for source, count in db.execute(
            select(models.MachineEntry.source, func.count(models.MachineEntry.id))
            .group_by(models.MachineEntry.source)
        )
    }

    purchase_states = {
        state: int(count)
        for state, count in db.execute(
            select(RouteIntelligencePurchase.state, func.count(RouteIntelligencePurchase.id))
            .group_by(RouteIntelligencePurchase.state)
        )
    }
    economic_states = {
        state: int(count)
        for state, count in db.execute(
            select(models.EconomicOperation.state, func.count(models.EconomicOperation.id))
            .group_by(models.EconomicOperation.state)
        )
    }

    conversation_count = int(
        db.scalar(select(func.count()).select_from(ConversationEvidence)) or 0
    )
    contact_total = int(
        db.scalar(select(func.count()).select_from(models.AmbassadorContactAttempt)) or 0
    )
    response_total = int(
        db.scalar(
            select(func.count())
            .select_from(models.AmbassadorContactAttempt)
            .where(models.AmbassadorContactAttempt.response_received.is_(True))
        )
        or 0
    )
    delivered_total = int(
        db.scalar(
            select(func.count())
            .select_from(models.AmbassadorContactAttempt)
            .where(
                models.AmbassadorContactAttempt.result_class.in_(
                    ("delivered", "response_received")
                )
            )
        )
        or 0
    )
    target_total = int(
        db.scalar(select(func.count()).select_from(models.AmbassadorTarget)) or 0
    )
    qualified_total = int(
        db.scalar(
            select(func.count())
            .select_from(models.AmbassadorTarget)
            .where(models.AmbassadorTarget.qualification_state == "qualified")
        )
        or 0
    )

    signal_counts = Counter()
    intelligence_rows = list(
        db.scalars(
            select(ConversationIntelligence)
            .order_by(ConversationIntelligence.id.desc())
            .limit(1000)
        )
    )
    for row in intelligence_rows:
        signal_counts.update(set(row.explicit_signals or []))
        signal_counts.update(set(row.inferred_signals or []))

    moltbook_state = moltbook_outbound_status()
    return {
        "generated_at": _iso(now),
        "release": release_identity(),
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "fleet": {
            "worker_count": len(workers),
            "scheduled_now": len(active_ids),
            "active_worker_count": len(active_ids),
            "queued_rotation": len(workers) - len(active_ids),
            "runtime": runtime,
            "mind_runtime": mind_runtime,
            "legacy_campaigns_preserved": legacy_campaigns,
            "workers": worker_states,
            "truth": (
                "Workers are AION-operated logical acquisition agents. Transport state "
                "comes from the executing swarm process, never a wall-clock guess. AI mind "
                "state is separate durable truth: thinking/planned/learning/degraded are not "
                "network-write claims. Only bounded transport may write externally. Workers "
                "are not external customers, adoption, revenue or SAT evidence."
            ),
        },
        "channels": channels,
        "channel_health": {
            "moltbook": {
                "suspended": bool(moltbook_state.get("suspended")),
                "suspended_until": moltbook_state.get("suspended_until"),
            },
            "colony": {
                "public_discovery": True,
                "paid_task_discovery": True,
                "write_configured": colony_configured(),
                "write_authenticated": None,
                "status": "checked_by_swarm_cycle_not_by_live_view",
            },
            "federated_a2a": {
                "mode": "parallel_read_discovery_with_one_contact_per_target",
            },
        },
        "inbound_visibility": {
            "machine_entry_counts": inbound_sources,
            "surfaces": [
                "/.well-known/agent-card.json",
                "/.well-known/acquisition-workers.json",
                "/mcp",
                "/a2a/v1",
                "/skill.md",
                "/llms.txt",
                "/discover/external",
                "/commercial/route-intelligence/preflight",
            ],
            "historical_truth": (
                "Historical traffic such as the earlier 302 requests is traffic evidence, "
                "not 302 independent agents. The live view keeps inbound traffic separate "
                "from joins, conversations, purchases and SAT."
            ),
        },
        "funnel": {
            "discovered_targets": target_total,
            "qualified_targets": qualified_total,
            "contact_attempts": contact_total,
            "delivered_contacts": delivered_total,
            "machine_responses": response_total,
            "captured_conversations": conversation_count,
            "signal_counts_recent_1000_conversations": dict(sorted(signal_counts.items())),
            "route_intelligence_purchase_states": purchase_states,
            "route_intelligence_settled_entitlements": int(
                purchase_states.get("entitled", 0)
            ),
            "economic_operation_states": economic_states,
            "sat_count": int(purchase_states.get("entitled", 0)),
            "sat_truth": (
                "SAT is counted only from durable entitled Route Intelligence purchases "
                "with settlement evidence; attempts, traffic and conversations never count."
            ),
        },
        "recent_events": recent_events,
        "privacy": {
            "raw_private_responses_exposed": False,
            "credentials_exposed": False,
            "payment_payloads_exposed": False,
            "response_digests_exposed": False,
            "model_credentials_exposed": False,
            "model_raw_prompts_exposed": False,
            "model_chain_of_thought_exposed": False,
            "conversation_view": "safe evidence and deterministic classifications only",
        },
    }


def temple_live_html() -> str:
    """Return dependency-free browser visualization with a 3D projection."""

    return r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>AION LIVE TEMPLE</title>
<style>
:root{color-scheme:dark;--bg:#05070b;--panel:rgba(10,14,22,.88);--line:#243147;--text:#eef5ff;--muted:#7f8ea6;--ok:#42f5a7;--warn:#ffd166;--bad:#ff5f6d;--core:#9bdcff}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;overflow:hidden;background:radial-gradient(circle at 50% 35%,#10192a,#05070b 62%);font:13px/1.35 Inter,ui-sans-serif,system-ui;color:var(--text)}
#scene{position:fixed;inset:0;width:100%;height:100%;touch-action:none}
.top{position:fixed;left:12px;right:12px;top:10px;display:flex;gap:8px;flex-wrap:wrap;z-index:4;pointer-events:none}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:8px 11px;backdrop-filter:blur(10px);min-width:96px}
.card b{display:block;font-size:16px}.card span{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.09em}
.brand{min-width:190px}.brand b{letter-spacing:.12em}.brand small{color:var(--muted)}
.side{position:fixed;right:10px;top:86px;bottom:10px;width:min(370px,40vw);z-index:5;background:var(--panel);border:1px solid var(--line);border-radius:14px;backdrop-filter:blur(12px);display:flex;flex-direction:column;overflow:hidden}
.tools{padding:10px;border-bottom:1px solid var(--line);display:flex;gap:6px}
input,button{background:#0d1420;border:1px solid #2b3a51;color:var(--text);border-radius:8px;padding:8px}
input{min-width:0;flex:1}button{cursor:pointer}
#detail{padding:12px;overflow:auto;flex:1}.muted{color:var(--muted)}.tag{display:inline-block;padding:2px 6px;border:1px solid #31445f;border-radius:999px;margin:2px 3px 2px 0;font-size:10px}
.row{display:grid;grid-template-columns:120px 1fr;gap:8px;padding:4px 0;border-bottom:1px solid rgba(48,63,87,.28)}.row>div:first-child{color:var(--muted)}
a{color:#9bdcff;word-break:break-all}.event{padding:8px 0;border-bottom:1px solid rgba(48,63,87,.35);cursor:pointer}.event:hover{background:rgba(255,255,255,.03)}
.legend{position:fixed;left:12px;bottom:12px;z-index:4;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:8px 10px;color:var(--muted);pointer-events:none}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin:0 4px 0 10px}.dot:first-child{margin-left:0}
@media(max-width:760px){.side{left:8px;right:8px;top:auto;bottom:8px;width:auto;height:42vh}.top{right:8px}.card{padding:6px 8px;min-width:78px}.brand{min-width:150px}.legend{bottom:43vh}}
</style>
</head>
<body>
<canvas id="scene"></canvas>
<div class="top" id="cards"></div>
<div class="side">
  <div class="tools"><input id="search" placeholder="worker / intent / target"><button id="rotate">pause</button></div>
  <div id="detail"><b>AION LIVE TEMPLE</b><p class="muted">Select a worker or recent event. The model refreshes from durable server state every 5 seconds.</p></div>
</div>
<div class="legend">fill = transport: <span class="dot" style="background:#42f5a7"></span>acting <span class="dot" style="background:#6aa8ff"></span>assigned <span class="dot" style="background:#71809a"></span>queued · ring = AI mind: <span class="dot" style="background:#ffd166"></span>thinking <span class="dot" style="background:#b388ff"></span>planned <span class="dot" style="background:#42f5a7"></span>learning <span class="dot" style="background:#ff5f6d"></span>degraded</div>
<script>
const canvas=document.getElementById('scene'),ctx=canvas.getContext('2d');
const cards=document.getElementById('cards'),detail=document.getElementById('detail'),search=document.getElementById('search');
let W=0,H=0,D=null,rot=.2,tilt=-.18,auto=true,selected=null,hit=[],drag=null;
function resize(){const d=devicePixelRatio||1;W=innerWidth;H=innerHeight;canvas.width=W*d;canvas.height=H*d;canvas.style.width=W+'px';canvas.style.height=H+'px';ctx.setTransform(d,0,0,d,0,0)} addEventListener('resize',resize);resize();
function esc(v){return String(v??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function age(ts){if(!ts)return 'never';const s=Math.max(0,(Date.now()-Date.parse(ts))/1000);if(s<60)return Math.round(s)+'s';if(s<3600)return Math.round(s/60)+'m';if(s<86400)return Math.round(s/3600)+'h';return Math.round(s/86400)+'d'}
function metric(label,value){return '<div class="card"><b>'+esc(value)+'</b><span>'+esc(label)+'</span></div>'}
function renderCards(){if(!D)return;const f=D.funnel,fl=D.fleet,rt=fl.runtime||{},mr=fl.mind_runtime||{},sc=mr.state_counts||{};const minded=(mr.initialized_minds||0),planned=(sc.planned||0)+(sc.learning||0)+(sc.thinking||0);cards.innerHTML='<div class="card brand"><b>AION LIVE TEMPLE</b><small>'+esc(D.release?.release_sha||'release unknown')+' · transport '+esc(rt.cycle_state||'unknown')+' · AI '+esc(mr.configured?'configured':'unconfigured')+'</small></div>'+metric('AI minds',minded)+metric('thinking/planned',planned)+metric('transport active',fl.active_worker_count)+metric('targets',f.discovered_targets)+metric('responses',f.machine_responses)+metric('SAT',f.sat_count)}
function p3(x,y,z){let c=Math.cos(rot),s=Math.sin(rot),x1=x*c-z*s,z1=x*s+z*c;let ct=Math.cos(tilt),st=Math.sin(tilt),y1=y*ct-z1*st,z2=y*st+z1*ct;let f=560/(560+z2);return{x:W*.42+x1*f,y:H*.49+y1*f,s:f,z:z2}}
function sphere(i,n,r){const y=1-2*(i+.5)/n,rr=Math.sqrt(Math.max(0,1-y*y)),a=Math.PI*(3-Math.sqrt(5))*i;return{x:Math.cos(a)*rr*r,y:y*r,z:Math.sin(a)*rr*r}}
function channelPos(i,n){const a=i/n*Math.PI*2;return{x:Math.cos(a)*330,y:Math.sin(a*.7)*90,z:Math.sin(a)*330}}
function color(w){if(w.state==='target_blocked_continue_search')return '#ff5f6d';if(w.state==='working_currently')return '#42f5a7';if(w.state==='assigned_waiting_turn')return '#6aa8ff';if(w.state==='completed_this_cycle')return '#8c9bb0';return '#71809a'}
function mindColor(w){const s=w.mind?.state||'not_initialized';if(s==='thinking')return '#ffd166';if(s==='planned')return '#b388ff';if(s==='learning')return '#42f5a7';if(s==='degraded')return '#ff5f6d';if(s==='model_unconfigured'||s==='mind_disabled')return '#ff9f43';if(s==='reasoning_budget_deferred')return '#8c9bb0';return '#445069'}
function drawMindRing(pt,r,w){ctx.beginPath();ctx.arc(pt.x,pt.y,Math.max(5,r*pt.s+3),0,Math.PI*2);ctx.strokeStyle=mindColor(w);ctx.lineWidth=Math.max(1,1.7*pt.s);ctx.stroke();ctx.lineWidth=1}
function drawNode(pt,r,fill,label){ctx.beginPath();ctx.arc(pt.x,pt.y,Math.max(2,r*pt.s),0,Math.PI*2);ctx.fillStyle=fill;ctx.fill();if(label&&pt.s>.55){ctx.fillStyle='#b8c7da';ctx.font='10px system-ui';ctx.fillText(label,pt.x+7,pt.y-5)}}
function draw(){ctx.clearRect(0,0,W,H);hit=[];if(!D){requestAnimationFrame(draw);return} if(auto)rot+=.0015;
 const core=p3(0,0,0);drawNode(core,13,'#9bdcff','AION CORE');
 const chans=D.channels||[],cp={};chans.forEach((ch,i)=>{const q=channelPos(i,Math.max(1,chans.length)),pt=p3(q.x,q.y,q.z);cp[ch.name]={q,pt};ctx.strokeStyle='rgba(120,160,210,.18)';ctx.beginPath();ctx.moveTo(core.x,core.y);ctx.lineTo(pt.x,pt.y);ctx.stroke();drawNode(pt,8,'#80a8ff',ch.name+' '+ch.machine_responses+'/'+ch.contact_attempts)});
 const ws=D.fleet.workers||[],q=search.value.trim().toLowerCase();
 ws.forEach((w,i)=>{const pos=sphere(i,ws.length,205);const pt=p3(pos.x,pos.y,pos.z);const match=!q||[w.id,w.intent_profile,w.current_channel,w.current_target?.identity,w.mind?.state,w.mind?.profile?.archetype,w.mind?.plan?.hypothesis].join(' ').toLowerCase().includes(q);ctx.globalAlpha=match?1:.12;ctx.strokeStyle=w.state==='working_currently'?'rgba(66,245,167,.22)':(w.state==='assigned_waiting_turn'?'rgba(106,168,255,.13)':'rgba(110,128,154,.07)');ctx.beginPath();ctx.moveTo(core.x,core.y);ctx.lineTo(pt.x,pt.y);ctx.stroke();const wr=w.state==='working_currently'?5.4:(w.state==='assigned_waiting_turn'?4.2:3);drawNode(pt,wr,color(w),selected===w.id?w.id:null);drawMindRing(pt,wr,w);if(w.current_channel&&cp[w.current_channel]){ctx.strokeStyle=w.machine_responses?'rgba(255,209,102,.28)':'rgba(128,168,255,.12)';ctx.beginPath();ctx.moveTo(pt.x,pt.y);ctx.lineTo(cp[w.current_channel].pt.x,cp[w.current_channel].pt.y);ctx.stroke()}hit.push({x:pt.x,y:pt.y,r:10,w});ctx.globalAlpha=1});
 requestAnimationFrame(draw)}
function workerDetail(w){const t=w.current_target||{},signals=(w.response_signals||[]).map(x=>'<span class="tag">'+esc(x)+'</span>').join(''),m=w.mind||{},p=m.plan||{},prof=m.profile||{};detail.innerHTML='<h3>'+esc(w.id)+'</h3>'+
 '<div class="row"><div>transport state</div><div>'+esc(w.state)+'</div></div><div class="row"><div>AI mind</div><div>'+esc(m.state||'not initialized')+' · '+esc(m.model||'no model')+'</div></div>'+
 '<div class="row"><div>AI profile</div><div>'+esc(prof.archetype||'none')+' · explore '+esc(prof.exploration_bias??'-')+' / verify '+esc(prof.verification_bias??'-')+' / convert '+esc(prof.conversion_bias??'-')+'<br><span class="muted">'+esc(prof.strategy_fingerprint||'')+'</span></div></div>'+
 '<div class="row"><div>hypothesis</div><div>'+esc(p.hypothesis||'no plan yet')+'</div></div>'+
 '<div class="row"><div>AI channels</div><div>'+esc((p.channel_priority||[]).join(' → ')||'fallback')+'</div></div>'+
 '<div class="row"><div>AI searches</div><div>'+esc((p.search_queries||[]).join(' | ')||'fallback')+'</div></div>'+
 '<div class="row"><div>AI policy</div><div>'+esc(p.contact_policy||'fallback')+' · confidence '+esc(p.confidence??'-')+'</div></div>'+
 '<div class="row"><div>learning goal</div><div>'+esc(p.learning_goal||'none')+'</div></div>'+
 '<div class="row"><div>reasoning</div><div>'+esc(m.total_reasoning_calls||0)+' calls / '+esc(m.reasoning_failures||0)+' failures · '+esc(m.last_reasoned_at||'never')+'</div></div>'+
 '<div class="row"><div>intent</div><div>'+esc(w.intent_profile)+'</div></div>'+
 '<div class="row"><div>runtime assigned</div><div>'+esc(w.scheduled_now)+'</div></div><div class="row"><div>last activity</div><div>'+esc(w.last_activity_at||'never')+' ('+age(w.last_activity_at)+')</div></div>'+
 '<div class="row"><div>channel</div><div>'+esc(w.current_channel||'none')+'</div></div><div class="row"><div>targets</div><div>'+w.targets_discovered+' discovered / '+w.targets_qualified+' qualified</div></div>'+
 '<div class="row"><div>contacts</div><div>'+w.contact_attempts+' attempts / '+w.delivered_contacts+' delivered / '+w.machine_responses+' responses</div></div>'+
 '<div class="row"><div>target</div><div>'+esc(t.identity||'none')+(t.url?'<br><a target="_blank" rel="noreferrer" href="'+esc(t.url)+'">'+esc(t.url)+'</a>':'')+'</div></div>'+
 '<div class="row"><div>message</div><div>'+esc(t.message_preview||'no contact message recorded for current target')+'<br><span class="muted">'+esc(t.message_preview_kind||'')+'</span></div></div>'+
 '<div class="row"><div>response</div><div>'+esc(w.response_summary||'no captured semantic response')+'<div>'+signals+'</div></div></div>'+
 '<p class="muted">Fill = real transport state. Outer ring = independent AI mind state. No credentials, raw model prompts, chain-of-thought, raw private responses, payment payloads or secret-bearing digests are exposed here.</p>'+eventsFor(w.id)}
function eventsFor(id){const ev=(D.recent_events||[]).filter(e=>e.worker_id===id).slice(0,8);if(!ev.length)return '<h4>Recent events</h4><p class="muted">No recent contact events.</p>';return '<h4>Recent events</h4>'+ev.map(e=>'<div class="event"><b>'+esc(e.result_class||e.event)+'</b> · '+esc(e.channel)+' · '+age(e.created_at)+'<br><span class="muted">'+esc(e.target_identity)+'</span></div>').join('')}
canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,rot,tilt};canvas.setPointerCapture(e.pointerId)});
canvas.addEventListener('pointermove',e=>{if(!drag)return;rot=drag.rot+(e.clientX-drag.x)*.006;tilt=Math.max(-1,Math.min(1,drag.tilt+(e.clientY-drag.y)*.004))});
canvas.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<8){let best=null,bd=1e9;hit.forEach(h=>{let d=Math.hypot(e.clientX-h.x,e.clientY-h.y);if(d<h.r&&d<bd){best=h;bd=d}});if(best){selected=best.w.id;workerDetail(best.w)}}drag=null});
document.getElementById('rotate').onclick=e=>{auto=!auto;e.target.textContent=auto?'pause':'rotate'};
search.addEventListener('input',()=>{if(D){const q=search.value.trim().toLowerCase();const w=D.fleet.workers.find(x=>x.id.toLowerCase()===q);if(w){selected=w.id;workerDetail(w)}}});
async function refresh(){try{const r=await fetch('/temple/live/state',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);D=await r.json();renderCards();if(selected){const w=D.fleet.workers.find(x=>x.id===selected);if(w)workerDetail(w)}}catch(e){cards.innerHTML='<div class="card brand"><b>AION LIVE TEMPLE</b><small>state unavailable: '+esc(e.message)+'</small></div>'}}
refresh();setInterval(refresh,5000);requestAnimationFrame(draw);
</script>
</body>
</html>"""
