"""AION acquisition worker roster.

These workers are transparent AION-operated logical workers, not fake users,
customers, members, or adoption metrics. They share one deduplicated contact
ledger and channel-specific safety limits.
"""
from dataclasses import dataclass, asdict


WORKER_COUNT = 100
WORKER_SHARDS = 4
WORKERS_PER_CYCLE = WORKER_COUNT // WORKER_SHARDS

INTENT_LANES = (
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

_CHANNELS = ("federated_a2a", "moltbook", "hybrid")


@dataclass(frozen=True)
class AcquisitionWorker:
    id: str
    lane: str
    mission: str
    preferred_channel: str
    source: str
    action: str
    cadence: str
    shard: int
    query_offset: int


def _build_workers() -> tuple[AcquisitionWorker, ...]:
    workers = []
    for index in range(WORKER_COUNT):
        lane = INTENT_LANES[index % len(INTENT_LANES)]
        preferred_channel = _CHANNELS[(index // WORKER_SHARDS) % len(_CHANNELS)]
        workers.append(
            AcquisitionWorker(
                id=f"aion-net-{index + 1:03d}",
                lane=lane,
                mission=(
                    "Find a real external machine need in the assigned intent lane, "
                    "qualify the target, offer immediate AION pre-spend value when "
                    "allowed, and record the result truthfully."
                ),
                preferred_channel=preferred_channel,
                source="moltbook+federated_a2a_indexes",
                action="discover_qualify_contact_observe",
                cadence="rotating_15m_shard_24x7",
                shard=index % WORKER_SHARDS,
                query_offset=index,
            )
        )
    return tuple(workers)


WORKERS = _build_workers()


def worker_manifest():
    return [asdict(worker) for worker in WORKERS]
