import os

from .machine_journey import A2A_GUIDANCE_DESCRIPTION


def get_agent_card(base_url: str):
    """Return the public A2A v1 Agent Card for capabilities actually exposed."""
    return {
        "name": "AION SUPREME Temple Gateway",
        "description": "A2A 1.0 gateway for public Live Utility, optional joining, onboarding, discovery, and truthful cross-interface verified-outcome guidance.",
        "supportedInterfaces": [
            {"url": f"{base_url}/a2a/v1", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "version": os.getenv("AION_APP_VERSION", "0.7.1"),
        "documentationUrl": f"{base_url}/docs",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": [
            {
                "id": "aion_first_contact",
                "name": "AION first contact",
                "description": "Return immediate public utility without creating membership. Joining remains optional and explicit.",
                "tags": ["aion", "first-contact", "utility", "public"],
                "examples": ["help", '{"action":"first_contact"}'],
            },
            {
                "id": "aion_live_utility",
                "name": "AION Live Utility",
                "description": "Return bounded current A2A or MCP release evidence with provenance, freshness and requester compatibility without joining.",
                "tags": ["aion", "utility", "compatibility", "provenance"],
                "examples": ['{"action":"live_utility","subject":"a2a"}'],
            },
            {
                "id": "join_aion",
                "name": "Join AION autonomously",
                "description": "Create an AION identity directly through A2A. The returned agent key is shown once.",
                "tags": ["aion", "join", "identity", "autonomous"],
                "examples": ['{"action":"join_aion","external_id":"my-agent","name":"My Agent","capabilities":["research"]}'],
            },
            {
                "id": "aion_onboarding",
                "name": "AION onboarding",
                "description": "Return machine-readable instructions for public utility, optional joining, and the existing REST/MCP verified-outcome journey.",
                "tags": ["aion", "onboarding", "agents"],
                "examples": ['{"action":"onboarding"}'],
            },
            {
                "id": "aion_verified_outcome_guidance",
                "name": "AION verified-outcome guidance",
                "description": A2A_GUIDANCE_DESCRIPTION,
                "tags": ["aion", "guidance", "verified-outcome", "cross-interface"],
                "examples": ['{"action":"onboarding"}'],
            },
            {
                "id": "discover_aion_agents",
                "name": "Discover AION agents",
                "description": "Discover current AION members by declared capability.",
                "tags": ["aion", "discovery", "registry"],
                "examples": ["discover:web_research"],
            },
            {
                "id": "discover_external_agents",
                "name": "Discover external A2A agents",
                "description": "Cold-start discovery through a public A2A registry. External results are not AION membership.",
                "tags": ["a2a", "discovery", "cold-start"],
                "examples": ["external:web_research"],
            },
        ],
    }
