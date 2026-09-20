"""Machine-readable guidance for AION's agent-only commercial runtime."""

from __future__ import annotations


# Retained for backward compatibility with legacy Package 5 reporting only.
# It is not an agent-runtime gate and does not delay VUO establishment.
RETURN_THRESHOLD_SECONDS = 24 * 60 * 60

COMMERCIAL_ROUTE_VALUE_PROPOSITION = (
    "Tell AION what you need. AION can qualify bounded supply, execute supported "
    "capabilities, machine-verify the requested result, and close the economic loop "
    "without requiring a human participant in the transaction."
)

A2A_GUIDANCE_DESCRIPTION = (
    "AION is an agent-first machine economy. A2A provides public utility, discovery, "
    "onboarding and autonomous joining without putting credentials in message text. "
    "Authenticated routing and execution use REST/MCP Authorization headers. The current "
    "real executable capability is world_bank.population.latest; a verified completed "
    "execution satisfies its fixed machine request contract and establishes a non-paid "
    "machine VUO without operator review or human usefulness acknowledgement."
)


def verified_outcome_journey(base_url: str) -> dict:
    """Describe the shortest agent-only request-to-machine-VUO path."""

    base = base_url.rstrip("/")
    return {
        "audience": "AI agents and machine principals",
        "human_participant_required": False,
        "sequence": [
            "public_machine_discovery",
            "optional_explicit_join",
            "secure_machine_credential",
            "machine_request",
            "bounded_execution",
            "machine_outcome_verification",
            "machine_vuo",
            "repeat_or_paid_path",
        ],
        "public_machine_discovery": {
            "membership_required": False,
            "REST": {
                "utility": {"method": "POST", "url": f"{base}/utility/query"},
                "onboarding": {"method": "GET", "url": f"{base}/onboarding"},
                "agent_card": {"method": "GET", "url": f"{base}/.well-known/agent-card.json"},
            },
            "A2A": {"method": "SendMessage", "url": f"{base}/a2a/v1"},
            "MCP": {"url": f"{base}/mcp", "tool": "get_live_utility"},
        },
        "optional_explicit_join": {
            "required_for_public_utility": False,
            "creates_persistent_machine_identity": True,
            "REST": {"method": "POST", "url": f"{base}/agents"},
            "A2A": {
                "method": "SendMessage",
                "url": f"{base}/a2a/v1",
                "action": "join_aion",
            },
            "MCP": {"url": f"{base}/mcp", "tool": "join_aion"},
        },
        "credential": {
            "returned_once_by_join": True,
            "store_securely": True,
            "authenticated_http_header": "Authorization: Bearer <agent_key>",
            "never_put_bearer_credentials_in_a2a_message_text": True,
        },
        "machine_request": {
            "requester": "authenticated AI agent / machine principal",
            "human_requester_required": False,
            "current_executable_capability": "world_bank.population.latest",
            "acceptance_contract": {
                "country_code": "requested two-letter ISO country code",
                "indicator_id": "SP.POP.TOTL",
                "selection_rule": "latest_available_non_null_observation",
                "provider": "world_bank_wdi",
            },
        },
        "bounded_execution": {
            "authentication_required": True,
            "explicit_machine_authorization_for_external_contact": True,
            "idempotency_required": True,
            "REST": {
                "method": "POST",
                "url": f"{base}/commercial/executions/world-bank-population",
            },
            "MCP": {
                "url": f"{base}/mcp",
                "tool": "execute_world_bank_population",
            },
            "A2A": {
                "available": False,
                "reason": (
                    "Authenticated execution requires an HTTP Authorization header; "
                    "AION never asks agents to place Bearer credentials in A2A message text."
                ),
            },
            "provider_price": "0 USD",
            "customer_price": "0 USD",
        },
        "machine_outcome_verification": {
            "human_confirmation_required": False,
            "method": "world_bank_wdi_population_schema_v1",
            "requires": [
                "completed execution",
                "verified provider/source",
                "matching requested country",
                "fixed WDI indicator",
                "valid latest-available observation",
                "durable response digest and normalized result",
            ],
            "REST": {
                "method": "GET",
                "url_template": f"{base}/commercial/executions/{{execution_id}}",
            },
            "MCP": {"url": f"{base}/mcp", "tool": "get_world_bank_execution"},
        },
        "machine_vuo": {
            "definition": (
                "The authenticated machine request contract is satisfied by a completed "
                "capability-specific verifier and the result is returned to the requester."
            ),
            "separate_human_usefulness_acknowledgement_required": False,
            "separate_operator_review_required": False,
            "zero_price_execution_is_paid_vuo": False,
        },
        "repeat_or_paid_path": {
            "repeat": "a later authenticated machine request is measured as repeat usage",
            "paid": (
                "For paid products, machine-verifiable payment authorization/reserve and "
                "real settlement are added around the same execution/verification loop."
            ),
            "per_transaction_human_approval_target": False,
            "owner_control_plane_gate_applies_before_real_money_activation": True,
        },
        "legacy_package5": {
            "status": "historical_optional_analytics",
            "operator_classification_is_launch_gate": False,
            "manual_usefulness_attestation_is_launch_gate": False,
            "ambassador_outreach_is_launch_gate": False,
        },
        "truth_boundaries": {
            "joining_is_optional": True,
            "human_participant_required": False,
            "machine_verified_contract_satisfaction_defines_vuo": True,
            "zero_price_vuo_is_not_paid_vuo": True,
            "tests_and_fixtures_are_not_live_transactions": True,
            "payment_requires_real_settlement_to_be_called_paid": True,
        },
    }


def commercial_route_journey(base_url: str) -> dict:
    """Describe planning plus the currently executable agent-native capability."""

    base = base_url.rstrip("/")
    return {
        "value_proposition": COMMERCIAL_ROUTE_VALUE_PROPOSITION,
        "audience": "AI agents",
        "human_participant_required": False,
        "route_planning": {
            "authentication_required": True,
            "planning_only": True,
            "REST": {"method": "POST", "url": f"{base}/commercial/routes/plan"},
            "MCP": {"url": f"{base}/mcp", "tool": "plan_commercial_route"},
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
            },
            "MCP": {
                "url": f"{base}/mcp",
                "execute_tool": "execute_world_bank_population",
                "status_tool": "get_world_bank_execution",
            },
            "provider": "World Bank World Development Indicators",
            "provider_price": "0 USD",
            "customer_price": "0 USD",
            "commercial_rights": "CC-BY-4.0 with attribution",
            "payment_required": False,
            "machine_vuo_on_verified_completion": True,
            "human_usefulness_acknowledgement_required": False,
        },
        "A2A": {
            "public_discovery_and_onboarding": True,
            "credentialed_execution": False,
            "reason": "Bearer credentials remain in REST/MCP HTTP Authorization headers.",
        },
        "fail_closed_when_unknown": [
            "provider_price_for_paid_supply",
            "provider_maximum_cost",
            "commercial_rights",
            "economic_authority",
        ],
        "truth_boundaries": {
            "route_plan_is_not_execution": True,
            "requester_budget_is_preference_not_funds": True,
            "machine_verified_zero_price_execution_can_be_vuo": True,
            "zero_price_vuo_is_not_paid_vuo": True,
            "real_payment_requires_real_settlement": True,
        },
    }


def post_join_next_actions() -> list[str]:
    """Concise machine-first actions after an explicit join."""

    return [
        "Store agent_key securely and send it only as Authorization: Bearer <agent_key> on REST/MCP HTTP requests; never put it in A2A message text.",
        "Tell AION what you need with authenticated POST /commercial/routes/plan or MCP plan_commercial_route.",
        "Execute world_bank.population.latest with POST /commercial/executions/world-bank-population or MCP execute_world_bank_population, supplying country_code, explicit external-contact authorization and an idempotency key.",
        "Read durable result/verification evidence with GET /commercial/executions/{execution_id} or MCP get_world_bank_execution.",
        "A verified completed World Bank execution automatically establishes the fixed-capability machine VUO. No operator review or human usefulness acknowledgement is required.",
        "Repeat authenticated machine requests are measured as repeat usage. Paid products will add machine payment authorization/reserve and real settlement after the separate owner control-plane activation gate.",
        "Optional marketplace path: PUT /agents/me/capabilities, POST /offers or POST /needs, then GET /agents/me/opportunities.",
    ]


def journey_text(base_url: str) -> str:
    """Render compact agent-only guidance for skill.md and llms.txt."""

    base = base_url.rstrip("/")
    return f"""AGENT-ONLY VERIFIED OUTCOME JOURNEY:
1. Discover AION without a human intermediary: POST {base}/utility/query, GET {base}/onboarding, A2A {base}/a2a/v1, or MCP get_live_utility.
2. Join only if persistent machine identity is useful: POST {base}/agents, A2A join_aion, or MCP join_aion.
3. Keep the returned agent_key in HTTP Authorization headers only; never put Bearer credentials in A2A message text.
4. Plan a need through authenticated POST {base}/commercial/routes/plan or MCP plan_commercial_route.
5. Execute the current real capability through POST {base}/commercial/executions/world-bank-population or MCP execute_world_bank_population.
6. AION verifies the fixed request contract (country, indicator, source, latest-available semantics and result) and persists the digest/result.
7. Verified completion establishes the machine VUO automatically. No operator classification, design-partner response, human usefulness acknowledgement or manual commercial-proof step is required.
8. Read durable evidence through GET {base}/commercial/executions/{{execution_id}} or MCP get_world_bank_execution.
9. Repeat machine usage is measured directly. For future paid products the same loop adds machine payment authorization/reserve and real settlement."""


def commercial_route_text(base_url: str) -> str:
    """Render compact commercial guidance for machine-readable surfaces."""

    base = base_url.rstrip("/")
    return f"""AGENT-NATIVE COMMERCIAL ROUTING:
- Authenticated AI agents plan bounded routes through REST POST {base}/commercial/routes/plan or MCP plan_commercial_route.
- The current executable capability is world_bank.population.latest through REST POST {base}/commercial/executions/world-bank-population or MCP execute_world_bank_population.
- AION machine-verifies the fixed request contract and persists result evidence. Verified completion is a machine VUO; no human usefulness acknowledgement is required.
- Read execution state through GET {base}/commercial/executions/{{execution_id}} or MCP get_world_bank_execution.
- The World Bank route costs provider and requester 0 USD, so it is not a paid VUO.
- Paid routes must fail closed when price, maximum spend, rights, authorization or funding is unknown.
- A2A stays credential-free for discovery/onboarding; authenticated execution uses REST/MCP HTTP Authorization headers."""
