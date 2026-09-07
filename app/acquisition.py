"""AION acquisition swarm definitions.

These are worker roles/configuration, not fake registered users. They become executable
workers after AION has a public URL and an external scheduler/runtime can run them.
"""
from dataclasses import dataclass, asdict

@dataclass(frozen=True)
class AcquisitionWorker:
    id: str
    mission: str
    source: str
    action: str
    cadence: str

WORKERS = [
    AcquisitionWorker(
        "aion-scout-a2a",
        "Discover public A2A agents whose published capabilities overlap AION needs/offers.",
        "public_a2a_registries",
        "collect_public_agent_cards",
        "continuous_after_deploy",
    ),
    AcquisitionWorker(
        "aion-scout-mcp",
        "Discover public MCP servers and agent-facing tools relevant to collaboration.",
        "official_mcp_registry",
        "collect_public_server_metadata",
        "continuous_after_deploy",
    ),
    AcquisitionWorker(
        "aion-inviter",
        "Generate capability-specific, non-deceptive invitations for discovered compatible agents.",
        "qualified_discovery_queue",
        "prepare_machine_invitation",
        "event_driven",
    ),
    AcquisitionWorker(
        "aion-registry-publisher",
        "Publish and refresh AION's own machine-readable discovery metadata in compatible registries.",
        "aion_public_endpoint",
        "publish_or_refresh_listing",
        "on_release",
    ),
    AcquisitionWorker(
        "aion-conversion-observer",
        "Measure discovery, joins, first useful actions, returns and contributions without inventing conversions.",
        "aion_telemetry",
        "measure_funnel",
        "continuous_after_deploy",
    ),
]

def worker_manifest():
    return [asdict(w) for w in WORKERS]
