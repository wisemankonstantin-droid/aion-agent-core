import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models
from app.db import SessionLocal
from app.main import A2A_RUNTIME, MCP_VERSION, app
from app.machine_journey import RETURN_THRESHOLD_SECONDS
from app.services.package5_proof import DEFAULT_RETURN_THRESHOLD_SECONDS


client = TestClient(app)


def _agent_count() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(models.Agent)) or 0


def _proof_counts() -> dict:
    return client.get("/proof/package-5").json()["counts"]


def _package5_row_counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return (
            db.scalar(select(func.count()).select_from(models.Package5ParticipationAssessment)) or 0,
            db.scalar(select(func.count()).select_from(models.Package5VuoProof)) or 0,
        )


def _mcp(method: str, params: dict | None = None, *, bearer: str | None = None):
    params = dict(params or {})
    params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "package5b-tests", "version": "1"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": MCP_VERSION,
        "Mcp-Method": method,
    }
    if method == "tools/call":
        headers["Mcp-Name"] = params["name"]
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": "package5b", "method": method, "params": params},
    )


def _a2a(text: str) -> dict:
    if A2A_RUNTIME.get("status") != "mounted":
        pytest.skip("a2a-sdk not installed in this local test environment")
    response = client.post(
        "/a2a/v1",
        headers={"A2A-Version": "1.0"},
        json={
            "jsonrpc": "2.0",
            "id": "package5b",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "msg-" + uuid.uuid4().hex,
                    "role": "ROLE_USER",
                    "parts": [{"text": text}],
                }
            },
        },
    )
    assert response.status_code == 200, response.text
    rpc = response.json()
    assert "error" not in rpc, rpc
    return json.loads(rpc["result"]["message"]["parts"][0]["text"])


def _assert_truthful_journey(journey: dict) -> None:
    assert journey["public_utility"]["membership_required"] is False
    assert journey["public_utility"]["creates_membership"] is False
    assert journey["optional_explicit_join"]["required_for_public_utility"] is False
    assert journey["optional_explicit_join"]["creates_membership"] is True
    assert journey["optional_explicit_join"]["human_review_required"] is False
    assert journey["credential"]["never_put_bearer_credentials_in_a2a_message_text"] is True

    assert "package5_countable_participation_gate" not in journey["sequence"]
    execution = journey["authenticated_execution"]
    assert execution["operator_participation_review_required"] is False
    assert execution["zero_cost_capability"]["capability"] == "world_bank.population.latest"
    assert execution["zero_cost_capability"]["REST"]["url"].endswith(
        "/commercial/executions/world-bank-population"
    )

    result = journey["machine_verifiable_result"]
    assert result["human_usefulness_confirmation_required"] is False
    assert result["optional_feedback"]["required_for_completion"] is False
    assert result["optional_feedback"]["required_for_launch"] is False

    payment = journey["machine_payment_when_required"]
    assert payment["human_customer_approval_required_by_aion"] is False
    assert payment["owner_control_plane_enablement_may_be_required"] is True
    priced = payment["priced_route_intelligence"]
    assert priced["product_sku"] == "aion.verified.route_intelligence.v1"
    assert priced["membership_required"] is False
    assert priced["payment_method"] == "direct_base_usdc_eip3009_buyer_broadcast"
    assert priced["payment_flow"] == "upfront"
    assert priced["network"] == "eip155:8453"
    assert priced["asset_code"] == "USDC"
    assert priced["transfer_method"] == "eip3009_transferWithAuthorization"
    assert priced["buyer_pays_gas"] is True
    assert priced["aion_pays_gas"] is False
    assert priced["facilitator_required"] is False
    assert priced["readiness"]["url"].endswith("/commercial/route-intelligence/payment-readiness")
    assert priced["readiness"]["must_report_launch_ready"] is True
    assert priced["purchase"]["url"].endswith("/commercial/route-intelligence/purchase")
    assert priced["purchase"]["payment_instructions_location"] == "JSON body field payment_instructions"
    assert priced["purchase"]["payment_submission_headers"] == {
        "purchase_id": "X-AION-PURCHASE-ID",
        "transaction_hash": "X-AION-PAYMENT-TX",
    }
    assert priced["result_release_before_settlement"] is False
    assert priced["aion_broadcasts_transaction"] is False

    legacy = journey["legacy_package5_telemetry"]
    assert legacy["blocks_utility"] is False
    assert legacy["blocks_launch"] is False
    assert legacy["blocks_execution"] is False
    assert legacy["blocks_payment"] is False
    assert legacy["blocks_settlement"] is False
    assert legacy["proof_read"]["MCP"]["tool"] == "get_package5_proof"

    participation = journey["participation_readiness"]
    assert participation["legacy_telemetry_only"] is True
    assert participation["blocks_normal_utility"] is False
    assert participation["blocks_execution"] is False
    assert participation["blocks_settlement"] is False
    assert "legacy Package 5 qualification only" in participation["if_not_ready"]

    historical_gate = journey["package5_countable_participation_gate"]
    assert historical_gate["legacy_telemetry_only"] is True
    assert historical_gate["required_for_qualifying_vuo_at_submission"] is True
    assert historical_gate["blocks_normal_utility"] is False
    assert historical_gate["blocks_execution"] is False

    acknowledgement = journey["requester_usefulness_acknowledgement"]
    assert acknowledgement["legacy_telemetry_only"] is True
    assert acknowledgement["required_for_machine_completion"] is False
    assert acknowledgement["REST"]["url"].endswith("/proof/package-5/vuos")

    proof = journey["package5_proof"]
    assert proof["legacy_telemetry_only"] is True
    assert proof["REST"]["url"].endswith("/proof/package-5")

    historical_return = journey["qualifying_return"]
    assert historical_return["legacy_telemetry_only"] is True
    assert historical_return["required_for_normal_repeat_use"] is False

    truth = journey["truth_boundaries"]
    assert truth["operator_review_is_not_normal_agent_gate"] is True
    assert truth["human_usefulness_ack_is_not_completion_gate"] is True
    assert truth["legacy_vuo_is_not_launch_gate"] is True
    assert truth["callability_alone_is_not_vuo"] is True
    assert truth["countable_participation_required_at_vuo_submission"] is True
    assert truth["late_reclassification_does_not_upgrade_prior_noncountable_vuo_candidate"] is True
    assert truth["requester_confirmation_is_not_independent_third_party_verification"] is True
    assert truth["public_reads_do_not_create_package5_evidence"] is True
    assert truth["tests_and_fixtures_are_not_commercial_proof"] is True

def test_rest_onboarding_manifest_and_root_expose_the_same_truthful_journey():
    before_agents = _agent_count()
    before_proof = _proof_counts()
    before_rows = _package5_row_counts()

    onboarding = client.get("/onboarding").json()
    manifest = client.get("/.well-known/aion.json").json()
    root = client.get("/").json()
    for public_path in (
        "/first-contact",
        "/.well-known/agent-card.json",
        "/skill.md",
        "/llms.txt",
        "/proof/package-5",
    ):
        assert client.get(public_path).status_code == 200

    _assert_truthful_journey(onboarding["verified_outcome_journey"])
    assert onboarding["verified_outcome_journey"] == manifest["verified_outcome_journey"]
    planning_step = next(step for step in onboarding["rest_path"] if step.get("url", "").endswith("/commercial/routes/plan"))
    execution_step = next(step for step in onboarding["rest_path"] if step.get("url", "").endswith("/commercial/executions/world-bank-population"))
    assert planning_step["optional"] is True
    assert planning_step["required_before_direct_execution"] is False
    assert execution_step["route_plan_required"] is False
    readiness_step = next(step for step in onboarding["rest_path"] if step.get("url", "").endswith("/commercial/route-intelligence/payment-readiness"))
    purchase_step = next(step for step in onboarding["rest_path"] if step.get("url", "").endswith("/commercial/route-intelligence/purchase"))
    assert readiness_step["membership_required"] is False
    assert readiness_step["proceed_only_when"] == "launch_ready=true"
    assert purchase_step["membership_required"] is False
    assert purchase_step["payment_method"] == "direct_base_usdc_eip3009_buyer_broadcast"
    assert purchase_step["network"] == "eip155:8453"
    assert purchase_step["asset"] == "USDC"
    assert purchase_step["buyer_pays_gas"] is True
    assert purchase_step["facilitator_required"] is False
    assert purchase_step["payment_submission_headers"] == {
        "purchase_id": "X-AION-PURCHASE-ID",
        "transaction_hash": "X-AION-PAYMENT-TX",
    }
    assert root["verified_callability_action"] == "POST /actions/verify-callability"
    assert root["package5_proof"] == "GET /proof/package-5"
    assert _agent_count() == before_agents
    assert _proof_counts() == before_proof
    assert _package5_row_counts() == before_rows


def test_agent_card_advertises_guidance_without_false_a2a_action_capability():
    card = client.get("/.well-known/agent-card.json").json()
    skills = {skill["id"]: skill for skill in card["skills"]}
    guidance = skills["aion_verified_outcome_guidance"]
    assert "agent-native" in guidance["description"].lower()
    assert "operator participation review" in guidance["description"].lower()
    assert "not" in guidance["description"].lower()
    assert "Package 5 participation/VUO endpoints are legacy telemetry" in guidance["description"]
    assert "verify_external_callability" not in skills
    assert "submit_package5_vuo" not in skills
    assert "aion_paid_route_intelligence" not in skills

    route_guidance = skills["aion_commercial_route_planning"]
    route_description = route_guidance["description"].lower()
    route_tags = set(route_guidance["tags"])
    assert "route intelligence" in card["description"].lower()
    assert "provider selection" in card["description"].lower()
    assert "commercial routing" in card["description"].lower()
    assert "paid route intelligence" in route_description
    assert "external-agent discovery" in route_description
    assert "provider selection" in route_description
    assert "route-intelligence/payment-readiness" in route_description
    assert "route-intelligence/purchase" in route_description
    assert "direct base usdc" in route_description
    assert "buyer-paid gas" in route_description
    assert "no facilitator" in route_description
    assert "rest/mcp" in route_description
    assert "a2a provides guidance only" in route_description
    assert "does not execute the route or move funds" in route_description
    assert "settle" not in route_description
    assert {
        "route-intelligence",
        "provider-selection",
        "agent-discovery",
        "commercial-routing",
        "paid",
        "base-usdc",
        "buyer-pays-gas",
    }.issubset(route_tags)
    assert "Find a provider for this bounded agent need" in route_guidance["examples"]
    assert "I need verified Route Intelligence and provider selection" in route_guidance["examples"]
    assert '{"action":"onboarding"}' in route_guidance["examples"]

    serialized_skills = json.dumps(card["skills"]).lower()
    assert "mark-paid" not in serialized_skills
    assert "a2a provides discovery/guidance only" in serialized_skills

    onboarding = client.get("/onboarding").json()
    priced = onboarding["verified_outcome_journey"]["machine_payment_when_required"][
        "priced_route_intelligence"
    ]
    assert priced["readiness"]["url"].endswith(
        "/commercial/route-intelligence/payment-readiness"
    )
    assert priced["purchase"]["url"].endswith(
        "/commercial/route-intelligence/purchase"
    )

    ard_entry = client.get("/.well-known/ard.json").json()["entries"][0]
    assert "PaidRouteIntelligence" in ard_entry["capabilities"]
    assert ard_entry["metadata"]["routeIntelligencePaymentReadiness"].endswith(
        "/commercial/route-intelligence/payment-readiness"
    )
    assert ard_entry["metadata"]["routeIntelligencePurchase"].endswith(
        "/commercial/route-intelligence/purchase"
    )
    assert guidance["examples"] == ['{"action":"onboarding"}']


def test_a2a_onboarding_and_join_expose_cross_interface_path_without_bearer_in_message_guidance():
    before_agents = _agent_count()
    onboarding = _a2a('{"action":"onboarding"}')
    _assert_truthful_journey(onboarding["verified_outcome_journey"])
    assert "agent_key" not in onboarding
    assert _agent_count() == before_agents

    joined = _a2a(json.dumps({
        "action": "join_aion",
        "external_id": "package5b-a2a-" + uuid.uuid4().hex,
        "name": "Package 5B A2A Test",
    }))
    assert joined["agent_key"].startswith("aion_")
    journey = joined["next_actions"]["verified_outcome_journey"]
    _assert_truthful_journey(journey)
    assert journey["authenticated_execution"]["operator_participation_review_required"] is False


def test_skill_and_llms_are_complete_consistent_and_contain_no_real_credential():
    documents = [client.get("/skill.md").text, client.get("/llms.txt").text]
    for document in documents:
        assert "AGENT-NATIVE AION JOURNEY" in document
        assert "world_bank.population.latest" in document
        assert "operator review" in document.lower()
        assert "do not wait" in document.lower() or "not" in document.lower()
        assert "Human usefulness acknowledgement is optional feedback" in document
        assert "purchase-bound EIP-3009 USDC on Base" in document
        assert "X-AION-PURCHASE-ID" in document
        assert "X-AION-PAYMENT-TX" in document
        assert "PAYMENT-SIGNATURE" not in document
        assert "route-intelligence/payment-readiness" in document
        assert "route-intelligence/purchase" in document
        assert "buyer" in document.lower() and "gas" in document.lower()
        assert not re.search(r"aion_[A-Za-z0-9_-]{20,}", document)


def test_rest_and_mcp_join_next_actions_expose_existing_protected_sequence():
    rest = client.post(
        "/agents",
        json={"external_id": "package5b-rest-" + uuid.uuid4().hex, "name": "Package 5B REST Test"},
    ).json()
    rest_actions = "\n".join(rest["next_actions"])
    assert "POST /commercial/executions/world-bank-population" in rest_actions
    assert "No Package 5 operator review is required" in rest_actions
    assert "POST /actions/verify-callability" in rest_actions
    assert "payment-readiness" in rest_actions
    assert "X-AION-PURCHASE-ID" in rest_actions
    assert "X-AION-PAYMENT-TX" in rest_actions
    assert "purchase-bound EIP-3009" in rest_actions
    assert "PAYMENT-SIGNATURE" not in rest_actions
    assert "never in A2A message text" in rest_actions

    mcp = _mcp(
        "tools/call",
        {"name": "join_aion", "arguments": {"external_id": "package5b-mcp-" + uuid.uuid4().hex, "name": "Package 5B MCP Test"}},
    ).json()["result"]["structuredContent"]
    mcp_actions = "\n".join(mcp["next_actions"])
    assert "MCP verify_external_callability" in mcp_actions
    assert "No Package 5 operator review is required" in mcp_actions
    assert "POST /commercial/executions/world-bank-population" in mcp_actions
    _assert_truthful_journey(mcp["verified_outcome_journey"])


def test_mcp_discovery_tools_and_knowledge_expose_truthful_existing_interfaces():
    discovery = _mcp("server/discover").json()["result"]
    instructions = discovery["instructions"]
    assert "verify_external_callability" in instructions
    assert "get_action_status" in instructions
    assert "world_bank.population.latest" in instructions
    assert "operator review" not in instructions.lower() or "not" in instructions.lower()

    tools = {
        tool["name"]: tool
        for tool in _mcp("tools/list").json()["result"]["tools"]
    }
    assert "not by itself a semantic VUO" in tools["verify_external_callability"]["description"]
    assert "without rerunning" in tools["get_action_status"]["description"]
    assert "Reading it creates no participation" in tools["get_package5_proof"]["description"]

    knowledge = _mcp("tools/call", {"name": "temple_knowledge", "arguments": {}}).json()["result"]["structuredContent"]
    _assert_truthful_journey(knowledge["verified_outcome_journey"])
    route = knowledge["commercial_route_planning"]
    executable = route["executable_zero_cost_capability"]
    assert executable["REST"]["acknowledgement_url_template"] == executable["REST"]["optional_feedback_url_template"]
    assert route["planning"]["required_before_direct_execution"] is False
    assert route["truth_boundaries"]["route_plan_is_not_revenue_vuo_or_adoption_proof"] is True
    assert route["truth_boundaries"]["provider_interaction_endpoint_is_not_contacted"] is True
    assert route["truth_boundaries"]["payment_rail_is_not_contacted"] is True
    assert route["truth_boundaries"]["route_plan_is_not_persisted"] is True


def test_protected_writes_and_status_remain_authenticated_while_proof_is_read_only():
    before = _proof_counts()
    action = client.post(
        "/actions/verify-callability",
        headers={"Idempotency-Key": "package5b-unauth-action"},
        json={"query": "research", "authorize_external_contact": True},
    )
    assert action.status_code == 401
    assert client.get("/actions/00000000-0000-0000-0000-000000000000").status_code == 401
    acknowledgement = client.post(
        "/proof/package-5/vuos",
        headers={"Idempotency-Key": "package5b-unauth-vuo"},
        json={
            "action_id": "00000000-0000-0000-0000-000000000000",
            "goal_kind": "verify_external_agent_callability",
            "product_goal": "find_verify_invoke_external_a2a_agent",
            "delivered_outcome": "verified_external_agent_callability",
            "usefulness_confirmed": True,
            "usefulness_evidence": "requester_confirms_goal_was_useful",
        },
    )
    assert acknowledgement.status_code == 401
    assert client.get("/proof/package-5").status_code == 200
    assert client.post("/proof/package-5").status_code == 405
    assert _proof_counts() == before


def test_package5b_does_not_change_threshold_or_create_fake_commercial_proof():
    assert RETURN_THRESHOLD_SECONDS == DEFAULT_RETURN_THRESHOLD_SECONDS == 86_400
    proof = client.get("/proof/package-5").json()
    assert proof["counts"]["independent_logical_identities"] == 0
    assert proof["counts"]["qualifying_vuos"] == 0
    assert proof["counts"]["identities_with_qualifying_return"] == 0
    assert proof["commercial_proof_established"] is False
