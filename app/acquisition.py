"""AION acquisition force manifest.

These are five real bounded procurement roles, not 100 nominal AI agents or
independent customers. Historical worker rows are retained for durable evidence;
only these roles are scheduled. Actual model intelligence depends on successful
provider responses; transport remains governed by dedupe and platform limits.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


WORKER_COUNT = 5
LEGACY_WORKER_IDS = (
    "aion-scout-a2a",
    "aion-scout-mcp",
    "aion-inviter",
    "aion-registry-publisher",
    "aion-conversion-observer",
)
INTENT_PROFILES = (
    "provider_selection",
    "paid_api_buyers",
    "agent_wallets",
    "mcp_buyers",
    "a2a_buyers",
    "data_buyers",
    "automation_buyers",
    "inference_buyers",
    "fallback_seekers",
    "agent_commerce",
    "security_buyers",
    "observability_buyers",
    "storage_compute_buyers",
    "payments_buyers",
    "verification_buyers",
)
ACTIVE_INTENT_PROFILES = (
    "provider_selection",
    "mcp_buyers",
    "paid_api_buyers",
    "fallback_seekers",
    "verification_buyers",
)

UNIVERSAL_SKILLS = (
    "reason_over_safe_durable_memory",
    "learn_from_shared_temple_brain",
    "contribute_safe_peer_experience",
    "build_bounded_sales_plan",
    "choose_bounded_discovery_plan",
    "discover_public_agent_intent",
    "qualify_machine_target",
    "contextualize_outreach",
    "contact_once_when_channel_healthy",
    "listen_for_machine_response",
    "classify_safe_response_signals",
    "learn_from_verified_outcomes",
    "route_real_need_to_aion_preflight",
)


@dataclass(frozen=True)
class AcquisitionWorker:
    id: str
    mission: str
    source: str
    action: str
    cadence: str
    intent_profile: str
    shard: int
    skills: tuple[str, ...]


def _build_workers() -> tuple[AcquisitionWorker, ...]:
    workers = []
    for index in range(1, WORKER_COUNT + 1):
        intent = ACTIVE_INTENT_PROFILES[(index - 1) % len(ACTIVE_INTENT_PROFILES)]
        shard = ((index - 1) // len(INTENT_PROFILES)) + 1
        worker_id = (
            LEGACY_WORKER_IDS[index - 1]
            if index <= len(LEGACY_WORKER_IDS)
            else f"aion-soldier-{index:03d}"
        )
        workers.append(
            AcquisitionWorker(
                id=worker_id,
                mission=(
                    "Use configured reasoning when available to discover a current "
                    "external-spend need in the assigned intent lane; qualify it, "
                    "call AION preflight, and take at most one policy-approved "
                    "buyer-facing action. On model failure use safe deterministic "
                    "discovery without pretending an AI plan succeeded."
                ),
                source="parallel_colony_moltbook_and_federated_a2a",
                action="reason_align_sales_plan_discover_qualify_contact_learn_route",
                cadence="independent_reasoning_each_cycle_bounded_rotating_transport",
                intent_profile=intent,
                shard=shard,
                skills=UNIVERSAL_SKILLS,
            )
        )
    return tuple(workers)


WORKERS = _build_workers()


def worker_manifest():
    return [asdict(worker) for worker in WORKERS]
