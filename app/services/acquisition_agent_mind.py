"""Model-backed autonomous reasoning for AION acquisition workers.

Each AION-operated worker gets its own durable safe memory and cognitive profile.
The model never receives credentials, raw private responses, payment payloads,
or authority to write to external systems. It selects a bounded plan; the
existing Ambassador/swarm control plane remains the only executor and continues
to enforce one-contact-per-target, channel health, rate limits and payment law.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from typing import Iterable

import httpx
from sqlalchemy import case, func, select

from .. import models
from ..conversation_models import ConversationEvidence, ConversationIntelligence
from ..db import SessionLocal
from ..payment_models import RouteIntelligencePurchase
from . import economic_kernel
from .direct_base_usdc import direct_base_usdc_readiness
from .paid_route_intelligence import ROUTE_INTELLIGENCE_SKU, route_intelligence_readiness


MIND_VERSION = "2"
TEMPLE_BRAIN_ID = "aion-temple-brain"
DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_TEMPLE_BRAIN_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "low"
RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_REASONING_PROVIDER = "openai_responses"
DEFAULT_CHAT_COMPLETIONS_BASE_URL = "https://foundation-models.api.cloud.ru/v1"
DEFAULT_MAX_CALLS_PER_CYCLE = 100
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_MAX_OUTPUT_TOKENS = 600
MAX_OBSERVATION_BYTES = 12_000
MAX_COLLECTIVE_OBSERVATION_BYTES = 24_000
MAX_MEMORY_OUTCOMES = 8
MAX_PLAN_QUERIES = 2
MAX_PLAN_CHANNELS = 4
MAX_SHARED_PEER_LESSONS = 24
MAX_SHARED_HYPOTHESES = 6
_ALLOWED_CHANNELS = ("colony", "federated_a2a", "moltbook", "hold")
_ALLOWED_CONTACT_POLICIES = (
    "contact_one_if_qualified",
    "discover_only",
    "hold",
)
_ALLOWED_TARGET_PREFERENCES = (
    "explicit_buyer_demand",
    "current_external_spend_intent",
    "pricing_interest",
    "integration_need",
    "trust_verification_need",
    "novel_qualified_target",
)
_CAMPAIGN = re.compile(
    r"^Intent swarm (?P<intent>[A-Za-z0-9_]+)(?:@(?P<worker>aion-[A-Za-z0-9-]{1,80}))? #[0-9]+$"
)

_COGNITIVE_ARCHETYPES = (
    "buyer-demand hunter",
    "skeptical verifier",
    "price-sensitivity scout",
    "integration-signal hunter",
    "provider-selection strategist",
    "fallback and reliability scout",
    "machine-commerce prospector",
    "trust and security qualifier",
    "conversion-friction analyst",
    "novel-market explorer",
)

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "decision_summary": {"type": "string"},
        "hypothesis": {"type": "string"},
        "channel_priority": {
            "type": "array",
            "items": {"type": "string", "enum": list(_ALLOWED_CHANNELS)},
        },
        "search_queries": {
            "type": "array",
            "items": {"type": "string"},
        },
        "contact_policy": {
            "type": "string",
            "enum": list(_ALLOWED_CONTACT_POLICIES),
        },
        "target_preference": {
            "type": "string",
            "enum": list(_ALLOWED_TARGET_PREFERENCES),
        },
        "expected_signal": {"type": "string"},
        "learning_goal": {"type": "string"},
        "sales_plan": {
            "type": "array",
            "items": {"type": "string"},
        },
        "collective_contribution": {"type": "string"},
        "coordination_request": {"type": "string"},
        "memory_note": {"type": "string"},
        "confidence": {"type": "integer"},
    },
    "required": [
        "decision_summary",
        "hypothesis",
        "channel_priority",
        "search_queries",
        "contact_policy",
        "target_preference",
        "expected_signal",
        "learning_goal",
        "sales_plan",
        "collective_contribution",
        "coordination_request",
        "memory_note",
        "confidence",
    ],
    "additionalProperties": False,
}

_TEMPLE_BRAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "collective_summary": {"type": "string"},
        "priority_hypotheses": {
            "type": "array",
            "items": {"type": "string"},
        },
        "channel_priority": {
            "type": "array",
            "items": {"type": "string", "enum": list(_ALLOWED_CHANNELS)},
        },
        "search_motifs": {
            "type": "array",
            "items": {"type": "string"},
        },
        "avoid_patterns": {
            "type": "array",
            "items": {"type": "string"},
        },
        "peer_directives": {
            "type": "array",
            "items": {"type": "string"},
        },
        "learning_agenda": {
            "type": "array",
            "items": {"type": "string"},
        },
        "memory_note": {"type": "string"},
        "confidence": {"type": "integer"},
    },
    "required": [
        "collective_summary",
        "priority_hypotheses",
        "channel_priority",
        "search_motifs",
        "avoid_patterns",
        "peer_directives",
        "learning_agenda",
        "memory_note",
        "confidence",
    ],
    "additionalProperties": False,
}

_MIND_INSTRUCTIONS = """You are one autonomous AION acquisition agent.
Your only North Star is FIRST REAL SETTLED AGENT TRANSACTION.

You are AION-operated infrastructure, never an independent customer and never
commercial proof. Find current external-spend intent from real external agents.
Prefer explicit buyer demand over seller listings, generic chatter or vanity
traffic. Utility comes before membership: BEFORE EXTERNAL SPEND, ASK AION.

Use the supplied commercial_knowledge as the only authority for AION product
availability and price state. Never invent, negotiate, discount, or override a
customer price. A paid product may be described as purchasable only when its
commercial_knowledge entry says purchase_available=true; otherwise offer the
zero-price preflight or say the paid offer is not currently available. The
Economic Kernel, not you, owns pricing, margin, payment and settlement authority.

Choose the next bounded discovery plan from the supplied safe observation.
You may choose only the listed channels. The executor, not you, controls network
writes, dedupe, one-contact-per-target, platform limits, channel suspension and
payments. Never propose new identities, spam, repeated contact, limit evasion,
self-payment, fake demand, fake agents, secret access or payment execution.
If no safe useful action exists, choose hold or discover_only.

For a real external buyer-intent, use this order: external need -> AION
preflight -> GO/HOLD/STOP -> qualified buyer-facing route or one bounded outbound
contact -> buyer chooses/pays AION only if a paid service is justified -> external
paid execution/spend only when pay-before-spend requirements are satisfied ->
verify -> settle. Never purchase or pay for AION's own SKU to qualify a lead,
unlock outreach, prove demand, or create commercial evidence. External paid
execution/spend requires preflight, payment authorization, and economic
justification; it does not require AION to self-pay
before contacting a buyer.

Generate at most two concise search queries aimed at current buyer intent and
a short sales_plan of up to four externally bounded stages.
collective_contribution is the safest useful lesson you want the fleet to learn;
coordination_request is a concise question or need for the shared Temple Brain.
Do not output URLs, credentials, private content,
chain-of-thought or hidden reasoning. decision_summary/hypothesis/learning_goal
are short operational summaries only. Learn from the worker's own durable history,
the safe experience
of peer AION minds, and the current Temple Brain strategy. The Temple Brain is
shared evidence, not permission to violate local evidence or guardrails. Vary
strategy when prior queries produced duplicates, sellers or no responses.
"""

_TEMPLE_BRAIN_INSTRUCTIONS = """You are the shared strategic cognition layer of AION.
Your only North Star is FIRST REAL SETTLED AGENT TRANSACTION.

Synthesize the safe, redacted, durable experience of the whole 100-agent
acquisition force. Produce a compact collective strategy that helps independent
minds search wider, learn from one another, avoid repeated failures, and move
genuine external buyer intent through AION preflight to GO/HOLD/STOP and then a
qualified buyer-facing route or one bounded outbound contact. A buyer may
choose/pay AION only if a paid service is justified; never purchase or pay for
AION's own SKU to qualify a lead, unlock outreach, prove demand, or create
commercial evidence. External paid execution/spend requires preflight, payment
authorization, and economic justification; it does not require AION to self-pay
before contacting a buyer.

Use only the supplied aggregate facts and peer lessons. Treat commercial_knowledge
as read-only deterministic commercial truth. Never invent a product, provider
price, AION price, discount, payment readiness or settlement state. The Economic
Kernel remains the sole pricing and financial authority; if price is unknown,
keep it unknown and direct minds toward preflight rather than a fabricated quote.
Do not invent demand, buyers, conversations, outcomes, URLs, credentials or payments.
Do not expose chain-of-thought. Never recommend spam, duplicate contact, new fake identities,
platform-limit evasion, self-payment, uncontrolled money movement, or contact
that violates opt-out/channel health. A shared strategy may prioritize channels,
buyer-intent motifs, hypotheses and experiments, but the bounded executor remains
the only authority for network writes and payments.

Prefer evidence that is closer to commercial intent: structured routing need,
pricing interest, integration request, trust/security requirement, verified
response, qualified target, delivered contact. Distinguish traffic and generic
responses from buyer demand and SAT. Keep directives concise and operational.
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: object) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _env_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def commercial_knowledge_snapshot() -> dict:
    """Return bounded read-only commercial truth for Temple Brain and worker minds.

    This snapshot exposes only deterministic product/economic configuration and
    safe aggregate purchase evidence. It never grants the model authority to set
    prices, activate money movement, execute a provider call, or infer a missing
    provider price.
    """

    route = route_intelligence_readiness()
    payment = direct_base_usdc_readiness()
    state_counts: dict[str, int] = {}
    latest_entitled_quote = None

    with SessionLocal() as db:
        for state, count in db.execute(
            select(
                RouteIntelligencePurchase.state,
                func.count(RouteIntelligencePurchase.id),
            ).group_by(RouteIntelligencePurchase.state)
        ):
            state_counts[str(state)] = int(count or 0)

        latest_entitled = db.scalar(
            select(RouteIntelligencePurchase)
            .where(RouteIntelligencePurchase.state == "entitled")
            .order_by(
                RouteIntelligencePurchase.entitled_at.desc(),
                RouteIntelligencePurchase.id.desc(),
            )
            .limit(1)
        )
        if latest_entitled is not None:
            entitled_at = latest_entitled.entitled_at
            if entitled_at is not None:
                entitled_at = (
                    entitled_at.replace(tzinfo=timezone.utc)
                    if entitled_at.tzinfo is None
                    else entitled_at.astimezone(timezone.utc)
                )
            latest_entitled_quote = {
                "product_sku": latest_entitled.product_sku,
                "currency": latest_entitled.quote_currency,
                "amount": latest_entitled.quote_amount,
                "entitled_at": entitled_at.isoformat() if entitled_at is not None else None,
            }

    route_blockers = list(route.get("blocking_reasons") or [])
    payment_blockers = list(payment.get("blocking_reasons") or [])
    product = {
        "product_sku": ROUTE_INTELLIGENCE_SKU,
        "product_kind": "aion_owned_verified_route_intelligence",
        "quote_configured": bool(route.get("quote_configured")),
        "currency": route.get("currency"),
        "customer_price": route.get("customer_price"),
        "policy_eligible": bool(route.get("policy_eligible")),
        "purchase_available": bool(payment.get("launch_ready")),
        "payment_method": payment.get("payment_method"),
        "payment_network": payment.get("network"),
        "commercial_rights_scope": route.get("commercial_rights_scope"),
        "blocking_reasons": list(dict.fromkeys(route_blockers + payment_blockers)),
    }

    return {
        "snapshot_version": "commercial_knowledge_v1",
        "free_entry_offer": {
            "name": "aion_pre_spend_preflight",
            "endpoint": "/commercial/route-intelligence/preflight",
            "customer_price": "0",
            "price_state": "fixed_zero",
            "membership_required": False,
            "purpose": "GO_HOLD_STOP_before_external_spend",
        },
        "paid_products": [product],
        "margin_policy": {
            "minimum_margin_bps": economic_kernel.MINIMUM_MARGIN_BPS,
            "standard_target_margin_bps": economic_kernel.STANDARD_TARGET_MARGIN_BPS,
            "unknown_cost_means_no_paid_execution": True,
        },
        "payment_readiness": {
            "method": payment.get("payment_method"),
            "network": payment.get("network"),
            "payment_offer_configured": bool(payment.get("payment_offer_configured")),
            "real_money_execution_enabled": bool(
                payment.get("real_money_execution_enabled")
            ),
            "launch_ready": bool(payment.get("launch_ready")),
            "blocking_reasons": payment_blockers,
        },
        "provider_pricing_policy": {
            "state": "request_scoped_verified_only",
            "trusted_provider_price_required_before_paid_execution": True,
            "unknown_provider_price_must_remain_unknown": True,
            "model_may_infer_or_override_provider_price": False,
        },
        "market_memory": {
            "route_intelligence_purchase_state_counts": dict(sorted(state_counts.items())),
            "settled_purchase_count": int(state_counts.get("entitled") or 0),
            "latest_settled_quote": latest_entitled_quote,
            "rejected_quote_evidence_available": False,
        },
        "authority": {
            "model_financial_authority": False,
            "model_may_set_customer_price": False,
            "model_may_activate_payment": False,
            "model_may_override_margin_policy": False,
            "deterministic_economic_kernel_authoritative": True,
        },
    }


def _reasoning_provider() -> str:
    provider = (
        os.getenv("AION_REASONING_PROVIDER") or DEFAULT_REASONING_PROVIDER
    ).strip()
    return provider or DEFAULT_REASONING_PROVIDER


def _reasoning_api_key() -> str:
    if _reasoning_provider() == "cloudru_chat_completions":
        return (os.getenv("AION_REASONING_API_KEY") or "").strip()
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def configured() -> bool:
    return bool(_reasoning_api_key())


def enabled() -> bool:
    return _env_enabled("AION_AGENT_MINDS_ENABLED", default=False) and configured()


def runtime_status() -> dict:
    return {
        "enabled": enabled(),
        "configured": configured(),
        "provider": _reasoning_provider(),
        "model": (os.getenv("AION_AGENT_MODEL") or DEFAULT_MODEL).strip()
        or DEFAULT_MODEL,
        "temple_brain_model": (
            os.getenv("AION_TEMPLE_BRAIN_MODEL") or DEFAULT_TEMPLE_BRAIN_MODEL
        ).strip()
        or DEFAULT_TEMPLE_BRAIN_MODEL,
        "reasoning_effort": (
            os.getenv("AION_AGENT_REASONING_EFFORT") or DEFAULT_REASONING_EFFORT
        ).strip()
        or DEFAULT_REASONING_EFFORT,
        "max_reasoning_calls_per_cycle": _bounded_int(
            "AION_AGENT_MIND_MAX_CALLS_PER_CYCLE",
            DEFAULT_MAX_CALLS_PER_CYCLE,
            1,
            100,
        ),
        "max_concurrency": _bounded_int(
            "AION_AGENT_MIND_MAX_CONCURRENCY",
            DEFAULT_MAX_CONCURRENCY,
            1,
            16,
        ),
        "collective_brain_id": TEMPLE_BRAIN_ID,
        "collective_reasoning_calls_per_cycle": 1,
        "shared_peer_learning": True,
        "explicit_model_spend_enable_required": True,
        "raw_private_responses_allowed": False,
        "credentials_in_prompt_allowed": False,
        "model_direct_network_write_authority": False,
        "model_payment_authority": False,
    }


def cognitive_profile(worker) -> dict:
    seed_hex = hashlib.sha256(worker.id.encode("utf-8")).hexdigest()
    seed = int(seed_hex[:8], 16)
    return {
        "archetype": _COGNITIVE_ARCHETYPES[seed % len(_COGNITIVE_ARCHETYPES)],
        "intent_profile": worker.intent_profile,
        "shard": int(worker.shard),
        "exploration_bias": 20 + (seed % 61),
        "verification_bias": 20 + ((seed >> 7) % 61),
        "conversion_bias": 20 + ((seed >> 13) % 61),
        "strategy_fingerprint": seed_hex[:12],
        "mission": (
            "Find a real current external-spend need, reduce uncertainty with AION "
            "preflight, and move only genuine buyer intent toward a settled transaction."
        ),
    }


def _empty_memory() -> dict:
    return {
        "recent_outcomes": [],
        "channel_performance": {},
        "lessons": [],
    }


def _worker_id_from_campaign(name: str | None) -> str | None:
    match = _CAMPAIGN.fullmatch(str(name or ""))
    return match.group("worker") if match else None


def _ensure_rows(workers: Iterable, *, state: str) -> None:
    now = _now()
    model = runtime_status()["model"]
    with SessionLocal() as db:
        existing = {
            row.worker_id: row
            for row in db.scalars(select(models.AcquisitionAgentMind))
        }
        for worker in workers:
            row = existing.get(worker.id)
            if row is None:
                db.add(
                    models.AcquisitionAgentMind(
                        worker_id=worker.id,
                        mind_version=MIND_VERSION,
                        model=model,
                        cognitive_profile=cognitive_profile(worker),
                        safe_memory=_empty_memory(),
                        last_plan=None,
                        last_observation_digest=None,
                        last_plan_digest=None,
                        last_state=state,
                        total_reasoning_calls=0,
                        reasoning_failures=0,
                        last_reasoned_at=None,
                        last_error=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                row.mind_version = MIND_VERSION
                row.model = model
                row.cognitive_profile = cognitive_profile(worker)
                row.last_state = state
                row.updated_at = now
        db.commit()


def _ensure_temple_brain_row(*, state: str) -> None:
    now = _now()
    model = runtime_status()["temple_brain_model"]
    profile = {
        "archetype": "collective_temple_brain",
        "intent_profile": "cross_fleet_strategy",
        "shard": 0,
        "exploration_bias": 50,
        "verification_bias": 80,
        "conversion_bias": 80,
        "strategy_fingerprint": hashlib.sha256(TEMPLE_BRAIN_ID.encode()).hexdigest()[:12],
        "mission": (
            "Synthesize verified safe experience from all AION acquisition minds and "
            "coordinate the fleet toward the first real settled agent transaction."
        ),
    }
    with SessionLocal() as db:
        row = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id == TEMPLE_BRAIN_ID
            )
        )
        if row is None:
            db.add(
                models.AcquisitionAgentMind(
                    worker_id=TEMPLE_BRAIN_ID,
                    mind_version=MIND_VERSION,
                    model=model,
                    cognitive_profile=profile,
                    safe_memory=_empty_memory(),
                    last_plan=None,
                    last_observation_digest=None,
                    last_plan_digest=None,
                    last_state=state,
                    total_reasoning_calls=0,
                    reasoning_failures=0,
                    last_reasoned_at=None,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            row.mind_version = MIND_VERSION
            row.model = model
            row.cognitive_profile = profile
            row.last_state = state
            row.updated_at = now
        db.commit()


def _build_collective_observation(
    workers: tuple,
    *,
    channel_health: dict,
    send_enabled: bool,
) -> dict:
    worker_ids = {worker.id for worker in workers}
    signal_counts: dict[str, int] = {}
    channel_performance: dict[str, dict[str, int]] = {}
    peer_lessons: list[dict] = []
    plan_hypotheses: list[dict] = []
    recent_outcomes: list[dict] = []
    routing_feedback_count = 0

    with SessionLocal() as db:
        minds = list(
            db.scalars(
                select(models.AcquisitionAgentMind).where(
                    models.AcquisitionAgentMind.worker_id.in_(worker_ids)
                )
            )
        )
        for row in minds:
            memory = dict(row.safe_memory or {})
            for channel, stats in dict(memory.get("channel_performance") or {}).items():
                bucket = channel_performance.setdefault(
                    str(channel),
                    {"actions": 0, "responses": 0, "new_targets": 0},
                )
                for key in ("actions", "responses", "new_targets"):
                    bucket[key] += int((stats or {}).get(key) or 0)
            for lesson in list(memory.get("lessons") or [])[-3:]:
                cleaned = _clean_short(lesson, 200)
                if cleaned:
                    peer_lessons.append(
                        {"worker_id": row.worker_id, "lesson": cleaned}
                    )
            for outcome in list(memory.get("recent_outcomes") or [])[-2:]:
                if isinstance(outcome, dict):
                    recent_outcomes.append(
                        {
                            "worker_id": row.worker_id,
                            "channel": _clean_short(outcome.get("channel"), 80) or None,
                            "new_targets": int(outcome.get("new_targets") or 0),
                            "qualified_targets": int(outcome.get("qualified_targets") or 0),
                            "contact_attempted": bool(outcome.get("contact_attempted")),
                            "response_received": bool(outcome.get("response_received")),
                            "routing_feedback_count": int(
                                outcome.get("routing_feedback_count") or 0
                            ),
                        }
                    )
            if row.last_plan:
                hypothesis = _clean_short(
                    dict(row.last_plan or {}).get("hypothesis"),
                    220,
                )
                if hypothesis:
                    previous_plan = dict(row.last_plan or {})
                    plan_hypotheses.append(
                        {
                            "worker_id": row.worker_id,
                            "hypothesis": hypothesis,
                            "confidence": int(previous_plan.get("confidence") or 0),
                            "collective_contribution": _clean_short(
                                previous_plan.get("collective_contribution"),
                                220,
                            ),
                            "coordination_request": _clean_short(
                                previous_plan.get("coordination_request"),
                                200,
                            ),
                        }
                    )

        for intelligence in db.scalars(
            select(ConversationIntelligence)
            .order_by(
                ConversationIntelligence.created_at.desc(),
                ConversationIntelligence.id.desc(),
            )
            .limit(1000)
        ):
            signals = set(intelligence.explicit_signals or [])
            signals.update(intelligence.inferred_signals or [])
            for signal in signals:
                key = _clean_short(signal, 80)
                if key:
                    signal_counts[key] = int(signal_counts.get(key) or 0) + 1

        for evidence in db.scalars(
            select(ConversationEvidence)
            .order_by(ConversationEvidence.captured_at.desc())
            .limit(1000)
        ):
            for item in evidence.safe_evidence or []:
                if isinstance(item, dict) and item.get("kind") == "routing_feedback_v1":
                    routing_feedback_count += 1

    peer_lessons = peer_lessons[-MAX_SHARED_PEER_LESSONS:]
    plan_hypotheses = sorted(
        plan_hypotheses,
        key=lambda row: row["confidence"],
        reverse=True,
    )[:MAX_SHARED_HYPOTHESES]
    recent_outcomes = recent_outcomes[-40:]
    commercial_knowledge = commercial_knowledge_snapshot()

    return {
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "brain_id": TEMPLE_BRAIN_ID,
        "worker_count": len(workers),
        "send_enabled": bool(send_enabled),
        "channel_health": channel_health,
        "fleet_channel_performance": channel_performance,
        "safe_response_signal_counts": dict(sorted(signal_counts.items())),
        "structured_routing_feedback_count": routing_feedback_count,
        "peer_lessons": peer_lessons,
        "recent_safe_outcomes": recent_outcomes,
        "high_confidence_worker_hypotheses": plan_hypotheses,
        "commercial_knowledge": commercial_knowledge,
        "hard_constraints": {
            "one_contact_per_target": True,
            "no_fake_agents": True,
            "no_self_payment": True,
            "no_limit_evasion": True,
            "no_model_direct_network_write": True,
            "no_model_payment_authority": True,
            "no_model_price_authority": True,
            "no_model_product_catalog_authority": True,
            "deterministic_economic_kernel_authoritative": True,
            "utility_before_membership": True,
            "pay_before_spend": True,
            "raw_private_responses_available": False,
            "chain_of_thought_sharing_allowed": False,
        },
    }


def _build_observations(
    workers: tuple,
    *,
    channel_health: dict,
    send_enabled: bool,
    fallback_queries_by_worker: dict[str, list[str]],
    temple_brain: dict | None,
) -> dict[str, dict]:
    worker_ids = {worker.id for worker in workers}
    totals = {
        worker_id: {
            "targets": 0,
            "qualified": 0,
            "contacts": 0,
            "delivered": 0,
            "responses": 0,
            "channels": {},
            "response_signal_counts": {},
            "routing_feedback_count": 0,
        }
        for worker_id in worker_ids
    }
    latest = {worker_id: None for worker_id in worker_ids}

    with SessionLocal() as db:
        minds = {
            row.worker_id: row
            for row in db.scalars(
                select(models.AcquisitionAgentMind).where(
                    models.AcquisitionAgentMind.worker_id.in_(worker_ids)
                )
            )
        }
        campaigns = list(
            db.scalars(
                select(models.AmbassadorCampaign).where(
                    models.AmbassadorCampaign.name.like("Intent swarm %")
                )
            )
        )
        worker_by_campaign = {}
        for campaign in campaigns:
            worker_id = _worker_id_from_campaign(campaign.name)
            if worker_id in worker_ids:
                worker_by_campaign[campaign.id] = worker_id

        campaign_ids = list(worker_by_campaign)
        if campaign_ids:
            for campaign_id, source, total, qualified in db.execute(
                select(
                    models.AmbassadorTarget.campaign_id,
                    models.AmbassadorTarget.discovery_source,
                    func.count(models.AmbassadorTarget.id),
                    func.sum(
                        case(
                            (
                                models.AmbassadorTarget.qualification_state
                                == "qualified",
                                1,
                            ),
                            else_=0,
                        )
                    ),
                )
                .where(models.AmbassadorTarget.campaign_id.in_(campaign_ids))
                .group_by(
                    models.AmbassadorTarget.campaign_id,
                    models.AmbassadorTarget.discovery_source,
                )
            ):
                worker_id = worker_by_campaign.get(campaign_id)
                if worker_id is None:
                    continue
                total = int(total or 0)
                qualified = int(qualified or 0)
                totals[worker_id]["targets"] += total
                totals[worker_id]["qualified"] += qualified
                channel = totals[worker_id]["channels"].setdefault(
                    source or "unknown",
                    {"targets": 0, "contacts": 0, "responses": 0},
                )
                channel["targets"] += total

            for campaign_id, source, contacts, delivered, responses in db.execute(
                select(
                    models.AmbassadorTarget.campaign_id,
                    models.AmbassadorTarget.discovery_source,
                    func.count(models.AmbassadorContactAttempt.id),
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
                    func.sum(
                        case(
                            (
                                models.AmbassadorContactAttempt.response_received.is_(
                                    True
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                )
                .join(
                    models.AmbassadorContactAttempt,
                    models.AmbassadorContactAttempt.target_id
                    == models.AmbassadorTarget.id,
                )
                .where(models.AmbassadorTarget.campaign_id.in_(campaign_ids))
                .group_by(
                    models.AmbassadorTarget.campaign_id,
                    models.AmbassadorTarget.discovery_source,
                )
            ):
                worker_id = worker_by_campaign.get(campaign_id)
                if worker_id is None:
                    continue
                contacts = int(contacts or 0)
                delivered = int(delivered or 0)
                responses = int(responses or 0)
                totals[worker_id]["contacts"] += contacts
                totals[worker_id]["delivered"] += delivered
                totals[worker_id]["responses"] += responses
                channel = totals[worker_id]["channels"].setdefault(
                    source or "unknown",
                    {"targets": 0, "contacts": 0, "responses": 0},
                )
                channel["contacts"] += contacts
                channel["responses"] += responses

            recent_rows = list(
                db.execute(
                    select(
                        models.AmbassadorContactAttempt,
                        models.AmbassadorTarget,
                        models.AmbassadorCampaign,
                    )
                    .join(
                        models.AmbassadorTarget,
                        models.AmbassadorTarget.id
                        == models.AmbassadorContactAttempt.target_id,
                    )
                    .join(
                        models.AmbassadorCampaign,
                        models.AmbassadorCampaign.id
                        == models.AmbassadorTarget.campaign_id,
                    )
                    .where(models.AmbassadorTarget.campaign_id.in_(campaign_ids))
                    .order_by(
                        models.AmbassadorContactAttempt.created_at.desc(),
                        models.AmbassadorContactAttempt.id.desc(),
                    )
                    .limit(1000)
                )
            )
            contact_worker = {}
            for contact, target, campaign in recent_rows:
                worker_id = _worker_id_from_campaign(campaign.name)
                if worker_id not in worker_ids:
                    continue
                contact_worker[contact.id] = worker_id
                if latest[worker_id] is None:
                    latest[worker_id] = {
                        "channel": target.discovery_source,
                        "result_class": contact.result_class,
                        "response_received": bool(contact.response_received),
                        "http_status": contact.http_status,
                        "at": (
                            contact.completed_at or contact.created_at
                        ).isoformat(),
                    }

            if contact_worker:
                evidence_rows = list(
                    db.scalars(
                        select(ConversationEvidence).where(
                            ConversationEvidence.ambassador_contact_id.in_(
                                list(contact_worker)
                            )
                        )
                    )
                )
                evidence_by_id = {row.id: row for row in evidence_rows}
                latest_intelligence = {}
                if evidence_by_id:
                    for intelligence in db.scalars(
                        select(ConversationIntelligence)
                        .where(
                            ConversationIntelligence.conversation_evidence_id.in_(
                                list(evidence_by_id)
                            )
                        )
                        .order_by(
                            ConversationIntelligence.created_at.desc(),
                            ConversationIntelligence.id.desc(),
                        )
                    ):
                        latest_intelligence.setdefault(
                            intelligence.conversation_evidence_id,
                            intelligence,
                        )
                for evidence in evidence_rows:
                    worker_id = contact_worker.get(evidence.ambassador_contact_id)
                    if worker_id is None:
                        continue
                    for item in evidence.safe_evidence or []:
                        if (
                            isinstance(item, dict)
                            and item.get("kind") == "routing_feedback_v1"
                        ):
                            totals[worker_id]["routing_feedback_count"] += 1
                    intelligence = latest_intelligence.get(evidence.id)
                    if intelligence is None:
                        continue
                    signals = set(intelligence.explicit_signals or [])
                    signals.update(intelligence.inferred_signals or [])
                    counts = totals[worker_id]["response_signal_counts"]
                    for signal in sorted(signals):
                        key = _clean_short(signal, 80)
                        if key:
                            counts[key] = int(counts.get(key) or 0) + 1

        shared_peer_lessons = []
        for peer_id, peer_row in minds.items():
            peer_memory = dict(peer_row.safe_memory or {})
            for lesson in list(peer_memory.get("lessons") or [])[-2:]:
                cleaned = _clean_short(lesson, 180)
                if cleaned:
                    shared_peer_lessons.append(
                        {"worker_id": peer_id, "lesson": cleaned}
                    )
        shared_peer_lessons = shared_peer_lessons[-MAX_SHARED_PEER_LESSONS:]
        commercial_knowledge = commercial_knowledge_snapshot()

        observations = {}
        for worker in workers:
            row = minds.get(worker.id)
            observations[worker.id] = {
                "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
                "worker_id": worker.id,
                "intent_profile": worker.intent_profile,
                "shard": int(worker.shard),
                "cognitive_profile": cognitive_profile(worker),
                "historical_performance": totals[worker.id],
                "latest_outcome": latest[worker.id],
                "safe_memory": (
                    dict(row.safe_memory or {}) if row is not None else _empty_memory()
                ),
                "previous_plan": (
                    dict(row.last_plan or {}) if row is not None and row.last_plan else None
                ),
                "temple_brain": temple_brain,
                "commercial_knowledge": commercial_knowledge,
                "peer_experience": [
                    item
                    for item in shared_peer_lessons
                    if item["worker_id"] != worker.id
                ][:12],
                "channel_health": channel_health,
                "send_enabled": bool(send_enabled),
                "fallback_queries": list(
                    fallback_queries_by_worker.get(worker.id) or []
                )[:MAX_PLAN_QUERIES],
                "hard_constraints": {
                    "one_contact_per_target": True,
                    "no_fake_agents": True,
                    "no_self_payment": True,
                    "no_limit_evasion": True,
                    "no_model_direct_network_write": True,
                    "no_model_payment_authority": True,
                    "no_model_price_authority": True,
                    "no_model_product_catalog_authority": True,
                    "deterministic_economic_kernel_authoritative": True,
                    "utility_before_membership": True,
                    "pay_before_spend": True,
                },
            }
        return observations


def _extract_output_text(payload: dict) -> str:
    pieces = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text" and isinstance(
                content.get("text"), str
            ):
                pieces.append(content["text"])
            if content.get("type") == "refusal":
                raise RuntimeError("model_refusal")
    if not pieces:
        raise RuntimeError("model_output_missing")
    return "".join(pieces)


def _extract_chat_completion_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        raise RuntimeError("model_output_missing")
    message = choices[0].get("message") or {}
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str) or not text:
        raise RuntimeError("model_output_missing")
    return text


def _call_structured_model(
    *,
    model: str,
    instructions: str,
    encoded_observation: str,
    schema_name: str,
    schema: dict,
    max_output_tokens: int,
    metadata: dict,
    timeout: float,
) -> dict:
    key = _reasoning_api_key()
    if not key:
        error = (
            "reasoning_api_key_missing"
            if _reasoning_provider() == "cloudru_chat_completions"
            else "openai_api_key_missing"
        )
        raise RuntimeError(error)

    if _reasoning_provider() == "cloudru_chat_completions":
        base_url = (
            os.getenv("AION_REASONING_BASE_URL")
            or DEFAULT_CHAT_COMPLETIONS_BASE_URL
        ).strip().rstrip("/")
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": encoded_observation},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                },
            },
            "max_tokens": max_output_tokens,
        }
        extract_text = _extract_chat_completion_text
    else:
        url = RESPONSES_URL
        payload = {
            "model": model,
            "reasoning": {"effort": runtime_status()["reasoning_effort"]},
            "instructions": instructions,
            "input": encoded_observation,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
            "max_output_tokens": max_output_tokens,
            "store": False,
            "metadata": metadata,
        }
        extract_text = _extract_output_text

    response = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if response.status_code == 429:
        raise RuntimeError("model_rate_limited")
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError(f"model_http_{response.status_code}")
    return json.loads(extract_text(response.json()))


def _clean_short(value: object, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:maximum]


def _validate_plan(plan: object, fallback_queries: list[str]) -> dict:
    if not isinstance(plan, dict):
        raise RuntimeError("invalid_plan_shape")

    channels = []
    for value in plan.get("channel_priority") or []:
        value = str(value)
        if value in _ALLOWED_CHANNELS and value not in channels:
            channels.append(value)
    channels = channels[:MAX_PLAN_CHANNELS]
    if not channels:
        channels = ["federated_a2a"]

    queries = []
    for value in plan.get("search_queries") or []:
        cleaned = _clean_short(value, 128)
        if cleaned and cleaned not in queries:
            queries.append(cleaned)
    queries = queries[:MAX_PLAN_QUERIES]
    if not queries:
        queries = [
            _clean_short(value, 128)
            for value in fallback_queries[:MAX_PLAN_QUERIES]
            if _clean_short(value, 128)
        ]

    contact_policy = str(plan.get("contact_policy") or "")
    if contact_policy not in _ALLOWED_CONTACT_POLICIES:
        contact_policy = "discover_only"
    target_preference = str(plan.get("target_preference") or "")
    if target_preference not in _ALLOWED_TARGET_PREFERENCES:
        target_preference = "current_external_spend_intent"
    try:
        confidence = int(plan.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0

    return {
        "decision_summary": _clean_short(plan.get("decision_summary"), 240),
        "hypothesis": _clean_short(plan.get("hypothesis"), 320),
        "channel_priority": channels,
        "search_queries": queries,
        "contact_policy": contact_policy,
        "target_preference": target_preference,
        "expected_signal": _clean_short(plan.get("expected_signal"), 160),
        "learning_goal": _clean_short(plan.get("learning_goal"), 240),
        "sales_plan": [
            _clean_short(value, 180)
            for value in list(plan.get("sales_plan") or [])[:4]
            if _clean_short(value, 180)
        ],
        "collective_contribution": _clean_short(
            plan.get("collective_contribution"), 240
        ),
        "coordination_request": _clean_short(
            plan.get("coordination_request"), 220
        ),
        "memory_note": _clean_short(plan.get("memory_note"), 240),
        "confidence": max(0, min(confidence, 100)),
    }


def _validate_temple_brain_plan(plan: object) -> dict:
    if not isinstance(plan, dict):
        raise RuntimeError("invalid_temple_brain_plan_shape")

    channels = []
    for value in plan.get("channel_priority") or []:
        value = str(value)
        if value in _ALLOWED_CHANNELS and value not in channels:
            channels.append(value)
    channels = channels[:MAX_PLAN_CHANNELS]

    def clean_list(name: str, maximum_items: int, maximum_chars: int) -> list[str]:
        result = []
        for value in plan.get(name) or []:
            cleaned = _clean_short(value, maximum_chars)
            if cleaned and cleaned not in result:
                result.append(cleaned)
        return result[:maximum_items]

    try:
        confidence = int(plan.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0

    return {
        "collective_summary": _clean_short(plan.get("collective_summary"), 360),
        "priority_hypotheses": clean_list(
            "priority_hypotheses", MAX_SHARED_HYPOTHESES, 240
        ),
        "channel_priority": channels,
        "search_motifs": clean_list("search_motifs", 8, 120),
        "avoid_patterns": clean_list("avoid_patterns", 8, 180),
        "peer_directives": clean_list("peer_directives", 8, 220),
        "learning_agenda": clean_list("learning_agenda", 8, 220),
        "memory_note": _clean_short(plan.get("memory_note"), 280),
        "confidence": max(0, min(confidence, 100)),
    }


def _call_temple_brain(observation: dict) -> dict:
    status = runtime_status()
    encoded = json.dumps(
        observation, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    if len(encoded.encode("utf-8")) > MAX_COLLECTIVE_OBSERVATION_BYTES:
        raise RuntimeError("temple_brain_observation_too_large")

    plan = _call_structured_model(
        model=status["temple_brain_model"],
        instructions=_TEMPLE_BRAIN_INSTRUCTIONS,
        encoded_observation=encoded,
        schema_name="aion_temple_brain_plan",
        schema=_TEMPLE_BRAIN_SCHEMA,
        max_output_tokens=_bounded_int(
            "AION_TEMPLE_BRAIN_MAX_OUTPUT_TOKENS", 900, 300, 1600
        ),
        metadata={
            "aion_worker_id": TEMPLE_BRAIN_ID,
            "aion_mind_version": MIND_VERSION,
            "collective_cognition": "true",
        },
        timeout=float(
            _bounded_int("AION_AGENT_MIND_TIMEOUT_SECONDS", 25, 5, 60)
        ),
    )
    return _validate_temple_brain_plan(plan)


def _call_model(worker_id: str, observation: dict) -> dict:
    status = runtime_status()
    encoded = json.dumps(
        observation, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    if len(encoded.encode("utf-8")) > MAX_OBSERVATION_BYTES:
        raise RuntimeError("mind_observation_too_large")

    plan = _call_structured_model(
        model=status["model"],
        instructions=_MIND_INSTRUCTIONS,
        encoded_observation=encoded,
        schema_name="aion_acquisition_plan",
        schema=_PLAN_SCHEMA,
        max_output_tokens=_bounded_int(
            "AION_AGENT_MIND_MAX_OUTPUT_TOKENS",
            DEFAULT_MAX_OUTPUT_TOKENS,
            200,
            1200,
        ),
        metadata={
            "aion_worker_id": worker_id,
            "aion_mind_version": MIND_VERSION,
        },
        timeout=float(
            _bounded_int("AION_AGENT_MIND_TIMEOUT_SECONDS", 25, 5, 60)
        ),
    )
    return _validate_plan(plan, observation.get("fallback_queries") or [])


def _persist_plan(
    worker_id: str,
    *,
    observation: dict,
    plan: dict | None,
    error: str | None,
) -> None:
    now = _now()
    status = runtime_status()
    with SessionLocal() as db:
        row = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id == worker_id
            )
        )
        if row is None:
            return
        row.model = (
            status["temple_brain_model"]
            if worker_id == TEMPLE_BRAIN_ID
            else status["model"]
        )
        row.last_observation_digest = _digest(observation)
        row.total_reasoning_calls += 1
        row.last_reasoned_at = now
        row.updated_at = now
        if plan is None:
            row.reasoning_failures += 1
            row.last_state = "degraded"
            row.last_error = _clean_short(error or "reasoning_failed", 160)
        else:
            row.last_plan = plan
            row.last_plan_digest = _digest(plan)
            row.last_state = "planned"
            row.last_error = None
            memory = dict(row.safe_memory or _empty_memory())
            lessons = list(memory.get("lessons") or [])
            note = _clean_short(plan.get("memory_note"), 240)
            if note:
                lessons.append(note)
            memory["lessons"] = lessons[-8:]
            row.safe_memory = memory
        db.commit()


def _last_temple_brain_plan() -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id == TEMPLE_BRAIN_ID
            )
        )
        if row is None or not row.last_plan:
            return None
        return dict(row.last_plan)


def refresh_all_minds(
    workers: Iterable,
    *,
    channel_health: dict,
    send_enabled: bool,
    fallback_queries_by_worker: dict[str, list[str]],
) -> dict[str, dict]:
    """Run one shared Temple Brain synthesis plus independent reasoning for workers."""

    workers = tuple(workers)
    if not workers:
        return {}

    if not enabled():
        state = "model_unconfigured" if not configured() else "mind_disabled"
        _ensure_rows(workers, state=state)
        _ensure_temple_brain_row(state=state)
        return {}

    _ensure_rows(workers, state="thinking")
    _ensure_temple_brain_row(state="thinking")

    collective_observation = _build_collective_observation(
        workers,
        channel_health=channel_health,
        send_enabled=send_enabled,
    )
    temple_brain = None
    temple_brain_error = None
    try:
        temple_brain = _call_temple_brain(collective_observation)
    except Exception as exc:
        temple_brain_error = type(exc).__name__ + ":" + str(exc)
    _persist_plan(
        TEMPLE_BRAIN_ID,
        observation=collective_observation,
        plan=temple_brain,
        error=temple_brain_error,
    )
    brain_fresh_this_cycle = temple_brain is not None
    if temple_brain is None:
        temple_brain = _last_temple_brain_plan()
    shared_brain = (
        {
            **temple_brain,
            "fresh_this_cycle": brain_fresh_this_cycle,
        }
        if temple_brain is not None
        else None
    )

    observations = _build_observations(
        workers,
        channel_health=channel_health,
        send_enabled=send_enabled,
        fallback_queries_by_worker=fallback_queries_by_worker,
        temple_brain=shared_brain,
    )
    maximum = runtime_status()["max_reasoning_calls_per_cycle"]
    selected = workers[:maximum]
    plans: dict[str, dict] = {}

    def run(worker):
        observation = observations[worker.id]
        try:
            return worker.id, observation, _call_model(worker.id, observation), None
        except Exception as exc:
            return worker.id, observation, None, type(exc).__name__ + ":" + str(exc)

    with ThreadPoolExecutor(max_workers=runtime_status()["max_concurrency"]) as pool:
        futures = [pool.submit(run, worker) for worker in selected]
        for future in as_completed(futures):
            worker_id, observation, plan, error = future.result()
            _persist_plan(
                worker_id,
                observation=observation,
                plan=plan,
                error=error,
            )
            if plan is not None:
                plans[worker_id] = plan

    if maximum < len(workers):
        deferred = workers[maximum:]
        _ensure_rows(deferred, state="reasoning_budget_deferred")
    return plans


def record_worker_outcome(worker_id: str, outcome: dict) -> None:
    """Persist only bounded safe outcome memory after the executor acts."""

    allowed = {
        "new_targets": int(outcome.get("new_targets") or 0),
        "qualified_targets": int(outcome.get("qualified_targets") or 0),
        "contact_attempted": bool(outcome.get("contact_attempted")),
        "channel": _clean_short(outcome.get("channel"), 80) or None,
        "result_class": _clean_short(outcome.get("result_class"), 64) or None,
        "response_received": bool(outcome.get("response_received")),
        "routing_feedback_count": int(outcome.get("routing_feedback_count") or 0),
        "recorded_at": _now().isoformat(),
    }
    with SessionLocal() as db:
        row = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id == worker_id
            )
        )
        if row is None:
            return
        memory = dict(row.safe_memory or _empty_memory())
        recent = list(memory.get("recent_outcomes") or [])
        recent.append(allowed)
        memory["recent_outcomes"] = recent[-MAX_MEMORY_OUTCOMES:]

        channel_name = allowed["channel"]
        if channel_name:
            perf = dict(memory.get("channel_performance") or {})
            stats = dict(
                perf.get(channel_name)
                or {"actions": 0, "responses": 0, "new_targets": 0}
            )
            stats["actions"] = int(stats.get("actions") or 0) + int(
                allowed["contact_attempted"]
            )
            stats["responses"] = int(stats.get("responses") or 0) + int(
                allowed["response_received"]
            )
            stats["new_targets"] = int(stats.get("new_targets") or 0) + allowed[
                "new_targets"
            ]
            perf[channel_name] = stats
            memory["channel_performance"] = perf

        row.safe_memory = memory
        row.last_state = "learning"
        row.updated_at = _now()
        db.commit()
