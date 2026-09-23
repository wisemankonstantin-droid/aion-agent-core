from .machine_journey import A2A_GUIDANCE_DESCRIPTION, COMMERCIAL_ROUTE_VALUE_PROPOSITION


def get_agent_card(base_url: str):
    """Return the public A2A v1 Agent Card for capabilities actually exposed."""
    return {
        "name": "AION SUPREME Temple Gateway",
        "description": "A2A 1.0 gateway for external-agent discovery, provider selection, commercial routing, paid Route Intelligence and verified route planning. A2A provides public discovery/guidance; executable planning and purchase use REST/MCP with truthful outcome and payment evidence.",
        "supportedInterfaces": [
            {"url": f"{base_url}/a2a/v1", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "provider": {
            "organization": "AION SUPREME",
            "url": base_url,
        },
        "version": "0.8.0",
        "documentationUrl": f"{base_url}/docs",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        # The public A2A surface intentionally requires no authentication.
        # Declare that explicitly rather than inventing an auth scheme merely
        # to improve a third-party trust score.
        "securitySchemes": {},
        "securityRequirements": [],
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["application/json", "text/plain"],
        "skills": [
            {
                "id": "aion_pre_spend_preflight",
                "name": "AION pre-spend preflight",
                "description": (
                    "Before external spend, POST a bounded current need to "
                    "/commercial/route-intelligence/preflight. The preflight is public, "
                    "zero-price, requires no membership, returns GO/HOLD/STOP, and performs "
                    "no provider execution or payment."
                ),
                "tags": [
                    "aion",
                    "pre-spend",
                    "provider-selection",
                    "route-intelligence",
                    "public",
                    "zero-price",
                ],
                "examples": [
                    '{"need":"paid web research provider"}',
                    '{"need":"storage provider for an agent","candidate_identifier":"optional-provider"}',
                ],
            },
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
                "id": "aion_commercial_route_planning",
                "name": "AION Route Intelligence, provider selection and commercial routing",
                "description": (
                    COMMERCIAL_ROUTE_VALUE_PROPOSITION
                    + " AION also exposes paid Route Intelligence for external-agent discovery and provider selection through REST/MCP. "
                    + "Check REST GET /commercial/route-intelligence/payment-readiness, then purchase through "
                    + "REST POST /commercial/route-intelligence/purchase when launch_ready=true. "
                    + "Payment is direct Base USDC with buyer-paid gas and no facilitator. "
                    + "A2A provides guidance only for this paid capability; it does not execute the route or move funds."
                ),
                "tags": [
                    "aion",
                    "route-intelligence",
                    "provider-selection",
                    "agent-discovery",
                    "commercial-routing",
                    "paid",
                    "base-usdc",
                    "buyer-pays-gas",
                    "cross-interface",
                ],
                "examples": [
                    "Find a provider for this bounded agent need",
                    "I need verified Route Intelligence and provider selection",
                    '{"action":"onboarding"}',
                ],
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
