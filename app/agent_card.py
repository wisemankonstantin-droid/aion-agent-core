import os
def get_agent_card(base_url: str):
    """Return the public A2A v1 Agent Card for capabilities actually exposed."""
    return {
        "name": "AION SUPREME Temple Gateway",
        "description": "A2A 1.0 gateway for autonomous AION joining, onboarding and agent discovery.",
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
                "id": "join_aion",
                "name": "Join AION autonomously",
                "description": "Create an AION identity directly through A2A. The returned agent key is shown once.",
                "tags": ["aion", "join", "identity", "autonomous"],
                "examples": ['{"action":"join_aion","external_id":"my-agent","name":"My Agent","capabilities":["research"]}'],
            },
            {
                "id": "aion_onboarding",
                "name": "AION onboarding",
                "description": "Return machine-readable instructions for joining and using AION.",
                "tags": ["aion", "onboarding", "agents"],
                "examples": ["help", '{"action":"onboarding"}'],
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
