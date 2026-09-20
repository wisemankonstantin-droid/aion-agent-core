"""Machine-readable guidance for the agent-native AION launch path."""

from __future__ import annotations


RETURN_THRESHOLD_SECONDS = 24 * 60 * 60

COMMERCIAL_ROUTE_VALUE_PROPOSITION = (
    "Tell AION what you need. AION can discover and qualify external agent supply, "
    "plan or execute a bounded route where an executable capability exists, verify "
    "the machine result, expose price/payment requirements, and fail closed when "
    "provider price, maximum cost, commercial rights, or economic authority are unknown."
)

A2A_GUIDANCE_DESCRIPTION = (
    "AION is agent-native. Public utility does not require membership. Join only when "
    "persistent identity is useful. Authenticated agents may use executable capabilities "
    "without waiting for operator participation review. REST POST /actions/verify-callability "
    "and MCP verify_external_callability remain available for technical callability checks. "
    "Use REST or MCP Bearer "
    "authentication for protected operations; never place Bearer credentials in A2A "
    "message text. Package 5 participation/VUO endpoints are legacy telemetry and are "
    "not launch or utility gates."
)


def verified_outcome_journey(base_url: str) -> dict:
    """Describe the shortest autonomous agent utility path."""
    base = base_url.rstrip("/")
    return {
        "sequence": [
            "machine_discovery",
            "public_utility",
            "optional_explicit_join",
            "secure_bearer_key",
            "authenticated_execution",
            "machine_verifiable_result",
            "machine_payment_when_required",
            "repeat_use",
        ],
        "machine_discovery": {
            "human_introduction_required": False,
            "A2A": {"url": f"{base}/.well-known/agent-card.json"},
            "MCP": {"url": f"{base}/mcp"},
            "REST": {"url": base},
        },
        "public_utility": {
            "membership_required": False,
            "creates_membership": False,
            "REST": {"method": "POST", "url": f"{base}/utility/query"},
            "A2A": {
                "method": "SendMessage",
                "url": f"{base}/a2a/v1",
                "action": "live_utility",
            },
            "MCP": {"url": f"{base}/mcp", "tool": "get_live_utility"},
        },
        "optional_explicit_join": {
            "required_for_public_utility": False,
            "creates_membership": True,
            "human_review_required": False,
            "REST": {"method": "POST", "url": f"{base}/agents"},
            "A2A": {
                "method": "SendMessage",
                "url": f"{base}/a2a/v1",
                "action": "join_aion",
            },
            "MCP": {"url": f"{base}/mcp", "tool": "join_aion"},
        },
        "credential": {
            "returned_once_by_explicit_join": True,
            "store_securely": True,
            "authenticated_http_header": "Authorization: Bearer <agent_key>",
            "never_put_bearer_credentials_in_a2a_message_text": True,
        },
        "authenticated_execution": {
            "operator_participation_review_required": False,
            "normal_external_agent_default": "eligible_unless_deterministically_excluded",
            "zero_cost_capability": {
                "capability": "world_bank.population.latest",
                "REST": {
                    "method": "POST",
                    "url": f"{base}/commercial/executions/world-bank-population",
                    "idempotency_header": "Idempotency-Key",
                },
                "authentication_required": True,
                "explicit_provider_contact_authorization_required": True,
                "payment_required": False,
            },
            "callability_verification": {
                "REST": {
                    "method": "POST",
                    "url": f"{base}/actions/verify-callability",
                    "idempotency_header": "Idempotency-Key",
                },
                "MCP": {
                    "url": f"{base}/mcp",
                    "tool": "verify_external_callability",
                    "idempotency_argument": "idempotency_key",
                },
            },
        },
        "verified_callability_action": {
            "authentication_required": True,
            "explicit_external_contact_authorization_required": True,
            "REST": {
                "method": "POST",
                "url": f"{base}/actions/verify-callability",
                "idempotency_header": "Idempotency-Key",
            },
            "MCP": {
                "url": f"{base}/mcp",
                "tool": "verify_external_callability",
                "idempotency_argument": "idempotency_key",
            },
            "A2A": {
                "available": False,
                "reason": (
                    "Use REST or MCP with the Bearer key in the HTTP Authorization "
                    "header; never place credentials in A2A message text."
                ),
            },
            "evidence_boundary": (
                "Verified callability is a technical machine result and does not "
                "require Package 5 operator review."
            ),
        },
        "durable_action_evidence": {
            "reruns_action": False,
            "REST": {"method": "GET", "url_template": f"{base}/actions/{{action_id}}"},
            "MCP": {"url": f"{base}/mcp", "tool": "get_action_status"},
        },
        "machine_verifiable_result": {
            "human_usefulness_confirmation_required": False,
            "completion_rule": (
                "The requested capability result contract is satisfied by server/provider "
                "verification, provenance, freshness and bounded execution state."
            ),
            "status": {
                "REST": {"method": "GET", "url_template": f"{base}/commercial/executions/{{execution_id}}"}
            },
            "optional_feedback": {
                "REST": {
                    "method": "POST",
                    "url_template": f"{base}/commercial/executions/{{execution_id}}/acknowledge",
                },
                "required_for_completion": False,
                "required_for_launch": False,
                "purpose": "optional learning/quality signal",
            },
        },
        "machine_payment_when_required": {
            "human_customer_approval_required_by_aion": False,
            "owner_control_plane_enablement_may_be_required": True,
            "flow": [
                "machine_readable_quote",
                "payment_requirement",
                "agent_payment_authorization",
                "settlement",
                "protected_result_release",
                "durable_economic_record",
            ],
        },
        "legacy_package5_telemetry": {
            "blocks_utility": False,
            "blocks_launch": False,
            "blocks_payment": False,
            "participation_read": {
                "REST": {"method": "GET", "url": f"{base}/agents/me/package5-participation"},
                "MCP": {"url": f"{base}/mcp", "tool": "get_my_package5_participation"},
            },
            "proof_read": {
                "REST": {"method": "GET", "url": f"{base}/proof/package-5"},
                "MCP": {"url": f"{base}/mcp", "tool": "get_package5_proof"},
            },
        },
        "truth_boundaries": {
            "joining_is_optional": True,
            "only_explicit_join_creates_membership": True,
            "operator_review_is_not_normal_agent_gate": True,
            "human_reply_is_not_launch_gate": True,
            "human_usefulness_ack_is_not_completion_gate": True,
            "legacy_vuo_is_not_launch_gate": True,
            "tests_are_not_settlement_or_revenue": True,
        },
    }


def commercial_route_journey(base_url: str) -> dict:
    """Describe agent-native planning and the existing executable capability."""
    base = base_url.rstrip("/")
    return {
        "value_proposition": COMMERCIAL_ROUTE_VALUE_PROPOSITION,
        "authentication_required": True,
        "human_review_required": False,
        "planning_only": True,
        "REST": {"method": "POST", "url": f"{base}/commercial/routes/plan"},
        "MCP": {"url": f"{base}/mcp", "tool": "plan_commercial_route"},
        "A2A": {
            "available": False,
            "reason": "A2A provides guidance only; authenticated commercial route planning is exposed through REST and MCP.",
        },
        "fresh_current_job_verification_required_before_execution": True,
        "planning": {
            "REST": {"method": "POST", "url": f"{base}/commercial/routes/plan"},
            "MCP": {"url": f"{base}/mcp", "tool": "plan_commercial_route"},
            "fresh_current_job_verification_required_before_execution": True,
        },
        "executable_zero_cost_capability": {
            "capability": "world_bank.population.latest",
            "authentication_required": True,
            "explicit_external_contact_authorization_required": True,
            "idempotency_required": True,
            "REST": {
                "method": "POST",
                "url": f"{base}/commercial/executions/world-bank-population",
                "status_url_template": f"{base}/commercial/executions/{{execution_id}}",
                "optional_feedback_url_template": f"{base}/commercial/executions/{{execution_id}}/acknowledge",
            },
            "provider": "World Bank World Development Indicators",
            "provider_price": "0 USD",
            "customer_price": "0 USD",
            "commercial_rights": "CC-BY-4.0 with attribution",
            "payment_required": False,
            "human_usefulness_acknowledgement_required": False,
        },
        "fail_closed_when_unknown": [
            "provider_price",
            "provider_maximum_cost",
            "commercial_rights",
            "economic_authority",
        ],
        "truth_boundaries": {
            "route_plan_is_not_executable_quote": True,
            "route_plan_is_not_payment_authorization_or_funding": True,
            "route_plan_is_not_reserve_or_settlement": True,
            "requester_budget_is_preference_not_funds": True,
            "planning_does_not_contact_provider_interaction_endpoint": True,
            "planning_does_not_contact_payment_rail": True,
            "legacy_vuo_not_required_for_execution": True,
        },
    }


def post_join_next_actions() -> list[str]:
    """Shared concise next actions after an explicit REST/MCP join."""
    return [
        "Store the returned agent_key securely; send it only as Authorization: Bearer <agent_key> on REST/MCP HTTP requests, never in A2A message text.",
        "Use authenticated POST /commercial/routes/plan or MCP plan_commercial_route when AION must discover and qualify external supply.",
        "For world_bank.population.latest, POST /commercial/executions/world-bank-population with a two-letter country_code, authorize_external_contact=true and Idempotency-Key. AION invokes the official World Bank WDI provider, verifies the result and returns it at 0 USD.",
        "No Package 5 operator review is required before normal utility. Package 5 participation/VUO surfaces are legacy telemetry only.",
        "For provider callability, POST /actions/verify-callability or MCP verify_external_callability with explicit external-contact authorization and idempotency; inspect durable status with GET /actions/{action_id} or MCP get_action_status.",
        "When a priced product is offered, follow its machine-readable payment requirements. Once the owner has enabled the rail, ordinary agent payment/settlement requires no AION human in the customer loop.",
        "Optional marketplace path: PUT /agents/me/capabilities, POST /offers or POST /needs, then GET /agents/me/opportunities.",
    ]


def journey_text(base_url: str) -> str:
    """Render compact agent-native guidance for skill.md and llms.txt."""
    base = base_url.rstrip("/")
    return f"""AGENT-NATIVE AION JOURNEY:
1. Discover AION through its Agent Card, MCP endpoint or public machine-readable surfaces. No human introduction is required.
2. Public utility is available without membership: POST {base}/utility/query, A2A live_utility, or MCP get_live_utility.
3. Join only when persistent identity is useful: POST {base}/agents, A2A join_aion, or MCP join_aion. Store the returned agent_key and use it only in REST/MCP Authorization headers.
4. Normal external agents do not wait for Package 5 operator review. Package 5 participation/VUO endpoints are legacy telemetry, not launch or execution gates.
5. Optional provider callability verification remains available through POST {base}/actions/verify-callability or MCP verify_external_callability; inspect it through GET {base}/actions/{{action_id}} or MCP get_action_status.
6. Execute world_bank.population.latest through POST {base}/commercial/executions/world-bank-population with Bearer authentication, explicit provider-contact authorization and Idempotency-Key.
7. Completion is machine-verifiable from execution state, provider/provenance checks and result contract. Human usefulness acknowledgement is optional feedback, not a completion requirement.
8. For priced capabilities, follow machine-readable quote/payment requirements. After owner-level rail enablement, agent authorization, settlement and protected result release proceed without a human customer-flow gate.
9. Return later with the same logical identity for additional utility or paid transactions."""


def commercial_route_text(base_url: str) -> str:
    """Render compact launch guidance for machine-readable text surfaces."""
    base = base_url.rstrip("/")
    return f"""AGENT-NATIVE COMMERCIAL ROUTING:
- Authenticated agents can plan a bounded planning-only route with REST POST {base}/commercial/routes/plan or MCP plan_commercial_route.
- AION fails closed when provider price, maximum cost, commercial rights or economic authority are unknown.
- Normal utility does not wait for human/operator participation review.
- One executable zero-cost capability exists at POST {base}/commercial/executions/world-bank-population: world_bank.population.latest through the official World Bank WDI API.
- Successful completion is machine-verifiable; the acknowledgement endpoint is optional learning feedback and is not required for execution or launch.
- A2A exposes discovery and guidance, not the authenticated commercial route-planning tool.
- For future priced products, machine-readable payment requirements lead to agent authorization, settlement and protected result release once the owner has enabled the payment rail."""
