"""AION acquisition force manifest.

These are transparent AION-operated logical workers, never fake external users,
customers, adoption, or SAT evidence. The fleet is deliberately larger than the
currently active transport budget: every worker is visible in the control plane,
while network writes remain governed by shared dedupe, channel health, platform
limits and one-contact-per-target rules.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


WORKER_COUNT = 100
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
UNIVERSAL_SKILLS = (
    "discover_public_agent_intent",
    "qualify_machine_target",
    "contextualize_outreach",
    "contact_once_when_channel_healthy",
    "listen_for_machine_response",
    "classify_safe_response_signals",
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
        intent = INTENT_PROFILES[(index - 1) % len(INTENT_PROFILES)]
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
                    "Find a real external machine need, qualify it, start one contextual "
                    "conversation when safe, learn from the response, and route a concrete "
                    "need toward AION preflight/purchase."
                ),
                source="parallel_colony_moltbook_and_federated_a2a",
                action="discover_qualify_contextual_contact_listen_route",
                cadence="continuous_rotating_assignment",
                intent_profile=intent,
                shard=shard,
                skills=UNIVERSAL_SKILLS,
            )
        )
    return tuple(workers)


WORKERS = _build_workers()


def worker_manifest():
    return [asdict(worker) for worker in WORKERS]
