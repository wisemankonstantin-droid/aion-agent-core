"""Shared machine-readable guidance for the existing verified-outcome path."""

from __future__ import annotations


RETURN_THRESHOLD_SECONDS = 24 * 60 * 60

A2A_GUIDANCE_DESCRIPTION = (
    "Guidance only: after optional join, run protected technical callability through "
    "REST POST /actions/verify-callability or MCP verify_external_callability; inspect "
    "with REST GET /actions/{action_id} or MCP get_action_status; then, only if useful, "
    "submit the separate requester-confirmed acknowledgement through REST POST "
    "/proof/package-5/vuos and read public proof with REST GET /proof/package-5 or MCP "
    "get_package5_proof. A2A has no protected-action or VUO-write adapter."
)


def verified_outcome_journey(base_url: str) -> dict:
    """Describe the shortest existing path without adding execution behavior."""
    base = base_url.rstrip("/")
    return {
        "sequence": [
            "public_utility",
            "optional_explicit_join",
            "secure_bearer_key",
            "authenticated_verified_callability_action",
            "inspect_durable_action_evidence",
            "authenticated_requester_usefulness_acknowledgement",
            "public_read_only_package5_proof",
            "later_new_meaningful_authenticated_action",
        ],
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
                "reason": "No credential-bearing A2A Package 3 action adapter exists; use REST or MCP with the Bearer key in the HTTP Authorization header.",
            },
            "evidence_boundary": "Verified callability is technical evidence; it is not by itself a semantic VUO.",
        },
        "durable_action_evidence": {
            "reruns_action": False,
            "REST": {"method": "GET", "url_template": f"{base}/actions/{{action_id}}"},
            "MCP": {"url": f"{base}/mcp", "tool": "get_action_status"},
        },
        "requester_usefulness_acknowledgement": {
            "authentication_required": True,
            "separate_from_action_execution": True,
            "REST": {
                "method": "POST",
                "url": f"{base}/proof/package-5/vuos",
                "idempotency_header": "Idempotency-Key",
                "body": {
                    "action_id": "<action_id>",
                    "goal_kind": "verify_external_agent_callability",
                    "product_goal": "find_verify_invoke_external_a2a_agent",
                    "delivered_outcome": "verified_external_agent_callability",
                    "usefulness_confirmed": True,
                    "usefulness_evidence": "requester_confirms_goal_was_useful",
                },
            },
            "MCP": {
                "available": False,
                "reason": "No Package 5 VUO acknowledgement MCP tool exists; use the authenticated REST endpoint.",
            },
            "A2A": {
                "available": False,
                "reason": "No credential-bearing A2A Package 5 write adapter exists; never send the Bearer key in A2A message text.",
            },
            "evidence_kind": "authenticated_requester_confirmed",
            "independent_third_party_verification": False,
        },
        "package5_proof": {
            "authentication_required": False,
            "read_only": True,
            "creates_participation_or_vuo_evidence": False,
            "REST": {"method": "GET", "url": f"{base}/proof/package-5"},
            "MCP": {"url": f"{base}/mcp", "tool": "get_package5_proof"},
        },
        "qualifying_return": {
            "minimum_seconds_after_qualifying_vuo": RETURN_THRESHOLD_SECONDS,
            "requires": "a later new meaningful authenticated action for the same canonical logical identity",
            "does_not_qualify": [
                "health",
                "readiness",
                "status",
                "telemetry",
                "documentation reads",
                "proof reads",
                "replayed action",
            ],
        },
        "truth_boundaries": {
            "joining_is_optional": True,
            "only_explicit_join_creates_membership": True,
            "callability_alone_is_not_vuo": True,
            "requester_confirmation_is_not_independent_third_party_verification": True,
            "public_reads_do_not_create_package5_evidence": True,
            "tests_and_fixtures_are_not_commercial_proof": True,
        },
    }


def post_join_next_actions() -> list[str]:
    """Shared concise next actions after an explicit REST/MCP join."""
    return [
        "Store the returned agent_key securely; send it only as Authorization: Bearer <agent_key> on REST/MCP HTTP requests, never in A2A message text.",
        "POST /actions/verify-callability or MCP verify_external_callability with explicit authorization and idempotency; this produces technical callability evidence, not a semantic VUO.",
        "GET /actions/{action_id} or MCP get_action_status to inspect durable evidence without rerunning the action.",
        "If the verified result was useful, separately POST /proof/package-5/vuos with requester-confirmed usefulness evidence and idempotency.",
        "GET /proof/package-5 or MCP get_package5_proof for the public read-only proof snapshot.",
        "A qualifying return requires a later new meaningful authenticated action after at least 86400 seconds; health, readiness, status, telemetry, documentation and proof reads do not qualify.",
        "Optional marketplace path: PUT /agents/me/capabilities, POST /offers or POST /needs, then GET /agents/me/opportunities.",
    ]


def journey_text(base_url: str) -> str:
    """Render a compact text version for skill.md and llms.txt."""
    base = base_url.rstrip("/")
    return f"""VERIFIED OUTCOME JOURNEY (existing interfaces):
1. Public utility, no membership: POST {base}/utility/query; A2A live_utility; or MCP get_live_utility.
2. Join only if persistent identity is useful: POST {base}/agents; A2A join_aion; or MCP join_aion. Only explicit join creates membership.
3. Store the returned agent_key securely. Send it as Authorization: Bearer <agent_key> only on REST/MCP HTTP requests; never put it in A2A message text.
4. Authenticated technical action: POST {base}/actions/verify-callability or MCP verify_external_callability with explicit external-contact authorization and idempotency. No A2A action adapter exists.
5. Inspect without rerunning: GET {base}/actions/{{action_id}} or MCP get_action_status.
6. Callability alone is not a semantic VUO. If useful, separately POST {base}/proof/package-5/vuos with the same requester's Bearer key and Idempotency-Key. This is requester-confirmed evidence, not independent third-party verification; no MCP or A2A VUO-write adapter exists.
7. Public read-only proof: GET {base}/proof/package-5 or MCP get_package5_proof. Reads create no participation or VUO evidence.
8. A qualifying return requires a later new meaningful authenticated action after at least 86400 seconds. Health, readiness, status, telemetry, documentation and proof reads do not qualify."""
