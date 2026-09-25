from __future__ import annotations

import json

from sqlalchemy import delete, select

from app import models
from app.acquisition import WORKERS
from app.db import SessionLocal
from app.main import app
from app.payment_models import RouteIntelligencePurchase
from app.services import acquisition_agent_mind, acquisition_swarm
from fastapi.testclient import TestClient


client = TestClient(app)


def _clean_minds():
    with SessionLocal() as db:
        db.execute(delete(models.AcquisitionAgentMind))
        db.commit()


def _clean_commercial_purchases():
    with SessionLocal() as db:
        db.execute(delete(RouteIntelligencePurchase))
        db.commit()


def _plan(worker_id: str) -> dict:
    return {
        "decision_summary": f"seek current buyer demand for {worker_id}",
        "hypothesis": "Explicit current spend language will convert better than generic agent listings.",
        "channel_priority": ["federated_a2a", "colony"],
        "search_queries": ["need paid provider now", "looking to hire agent service"],
        "contact_policy": "contact_one_if_qualified",
        "target_preference": "explicit_buyer_demand",
        "expected_signal": "routing_need",
        "learning_goal": "Compare explicit buyer demand with generic discovery.",
        "sales_plan": [
            "discover current external-spend intent",
            "qualify one real buyer need",
            "offer zero-cost AION preflight",
            "route genuine demand toward purchase",
        ],
        "collective_contribution": "Explicit current buyer verbs are higher value than seller capability language.",
        "coordination_request": "Share which channel has the strongest current pricing or routing signal.",
        "memory_note": "Prefer current buyer verbs over seller capability language.",
        "confidence": 72,
    }


def _brain_plan() -> dict:
    return {
        "collective_summary": "Prioritize explicit current buyer demand over generic listings.",
        "priority_hypotheses": [
            "Pricing and routing language is closer to purchase than generic agent discovery.",
            "Federated A2A plus Colony buyer tasks can diversify acquisition beyond Moltbook.",
        ],
        "channel_priority": ["federated_a2a", "colony", "moltbook"],
        "search_motifs": ["need paid provider now", "looking to hire agent service"],
        "avoid_patterns": ["generic seller listings", "duplicate targets"],
        "peer_directives": [
            "Share verified pricing, integration, trust and routing signals with the fleet."
        ],
        "learning_agenda": [
            "Measure which channel produces structured buyer needs rather than replies only."
        ],
        "memory_note": "Favor evidence closest to purchase and structured routing need.",
        "confidence": 81,
    }


def test_all_100_workers_have_distinct_cognitive_fingerprints():
    profiles = [acquisition_agent_mind.cognitive_profile(worker) for worker in WORKERS]

    assert len(profiles) == 100
    assert len({row["strategy_fingerprint"] for row in profiles}) == 100
    assert all(row["intent_profile"] for row in profiles)
    assert all(20 <= row["exploration_bias"] <= 80 for row in profiles)
    assert all(20 <= row["verification_bias"] <= 80 for row in profiles)
    assert all(20 <= row["conversion_bias"] <= 80 for row in profiles)


def test_unconfigured_model_fails_open_to_existing_transport_without_fake_thinking(
    monkeypatch,
):
    _clean_minds()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AION_AGENT_MINDS_ENABLED", raising=False)

    plans = acquisition_agent_mind.refresh_all_minds(
        WORKERS[:3],
        channel_health={"federated_a2a": {"public_discovery": True}},
        send_enabled=True,
        fallback_queries_by_worker={
            worker.id: ["provider selection", "paid api"] for worker in WORKERS[:3]
        },
    )

    assert plans == {}
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(models.AcquisitionAgentMind)
                .where(
                    models.AcquisitionAgentMind.worker_id.in_(
                        [worker.id for worker in WORKERS[:3]]
                    )
                )
                .order_by(models.AcquisitionAgentMind.worker_id)
            )
        )
    assert len(rows) == 3
    assert {row.last_state for row in rows} == {"model_unconfigured"}
    assert all(row.total_reasoning_calls == 0 for row in rows)
    with SessionLocal() as db:
        brain = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id
                == acquisition_agent_mind.TEMPLE_BRAIN_ID
            )
        )
        assert brain is not None
        assert brain.last_state == "model_unconfigured"
        assert brain.total_reasoning_calls == 0


def test_model_refresh_gives_each_worker_own_plan_and_durable_safe_memory(monkeypatch):
    _clean_minds()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("AION_AGENT_MINDS_ENABLED", "true")
    monkeypatch.setenv("AION_AGENT_MIND_MAX_CALLS_PER_CYCLE", "100")
    monkeypatch.setattr(
        acquisition_agent_mind,
        "_call_model",
        lambda worker_id, observation: _plan(worker_id),
    )
    monkeypatch.setattr(
        acquisition_agent_mind,
        "_call_temple_brain",
        lambda observation: _brain_plan(),
    )
    workers = WORKERS[:4]

    plans = acquisition_agent_mind.refresh_all_minds(
        workers,
        channel_health={
            "moltbook": {"suspended": True},
            "colony": {"public_discovery": True, "authenticated_write": False},
            "federated_a2a": {"public_discovery": True},
        },
        send_enabled=True,
        fallback_queries_by_worker={
            worker.id: ["fallback one", "fallback two"] for worker in workers
        },
    )

    assert set(plans) == {worker.id for worker in workers}
    assert len({plans[worker.id]["decision_summary"] for worker in workers}) == 4
    with SessionLocal() as db:
        rows = list(
            db.scalars(
                select(models.AcquisitionAgentMind).where(
                    models.AcquisitionAgentMind.worker_id.in_(
                        [worker.id for worker in workers]
                    )
                )
            )
        )
    assert len(rows) == 4
    assert {row.last_state for row in rows} == {"planned"}
    assert all(row.total_reasoning_calls == 1 for row in rows)
    with SessionLocal() as db:
        brain = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id
                == acquisition_agent_mind.TEMPLE_BRAIN_ID
            )
        )
        assert brain is not None
        assert brain.last_state == "planned"
        assert brain.total_reasoning_calls == 1
        assert brain.last_plan["collective_summary"]
    assert all(row.last_plan_digest.startswith("sha256:") for row in rows)
    assert "test-key-never-sent" not in json.dumps(
        [
            {
                "profile": row.cognitive_profile,
                "memory": row.safe_memory,
                "plan": row.last_plan,
                "error": row.last_error,
            }
            for row in rows
        ]
    )



def test_reasoning_budget_is_spent_on_explicit_active_workers(monkeypatch):
    _clean_minds()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-never-sent")
    monkeypatch.setenv("AION_AGENT_MINDS_ENABLED", "true")
    monkeypatch.setenv("AION_AGENT_MIND_MAX_CALLS_PER_CYCLE", "2")
    selected_ids = []

    def worker_plan(worker_id, observation):
        selected_ids.append(worker_id)
        return _plan(worker_id)

    monkeypatch.setattr(acquisition_agent_mind, "_call_model", worker_plan)
    monkeypatch.setattr(
        acquisition_agent_mind,
        "_call_temple_brain",
        lambda observation: _brain_plan(),
    )

    workers = WORKERS[:8]
    active_reasoning_workers = WORKERS[5:8]
    plans = acquisition_agent_mind.refresh_all_minds(
        workers,
        channel_health={"federated_a2a": {"public_discovery": True}},
        send_enabled=True,
        fallback_queries_by_worker={
            worker.id: ["fallback one", "fallback two"] for worker in workers
        },
        reasoning_workers=active_reasoning_workers,
    )

    expected = {WORKERS[5].id, WORKERS[6].id}
    assert set(plans) == expected
    assert set(selected_ids) == expected

    with SessionLocal() as db:
        rows = {
            row.worker_id: row
            for row in db.scalars(
                select(models.AcquisitionAgentMind).where(
                    models.AcquisitionAgentMind.worker_id.in_(
                        [worker.id for worker in workers]
                    )
                )
            )
        }
    assert rows[WORKERS[5].id].last_state == "planned"
    assert rows[WORKERS[6].id].last_state == "planned"
    assert rows[WORKERS[0].id].last_state == "reasoning_budget_deferred"
    assert rows[WORKERS[7].id].last_state == "reasoning_budget_deferred"


def test_openai_reasoning_request_is_structured_bounded_and_not_stored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-header-only")
    monkeypatch.delenv("AION_AGENT_MODEL", raising=False)
    monkeypatch.delenv("AION_AGENT_REASONING_EFFORT", raising=False)
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_plan(WORKERS[0].id)),
                            }
                        ],
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        seen["url"] = url
        seen["headers"] = dict(headers)
        seen["json"] = json
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(acquisition_agent_mind.httpx, "post", fake_post)
    observation = {
        "worker_id": WORKERS[0].id,
        "cognitive_profile": acquisition_agent_mind.cognitive_profile(WORKERS[0]),
        "historical_performance": {
            "targets": 2,
            "qualified": 1,
            "contacts": 1,
            "delivered": 1,
            "responses": 1,
            "response_signal_counts": {"pricing_commercial_interest": 1},
            "routing_feedback_count": 0,
        },
        "safe_memory": {"recent_outcomes": [], "channel_performance": {}, "lessons": []},
        "channel_health": {"federated_a2a": {"public_discovery": True}},
        "send_enabled": True,
        "fallback_queries": ["provider selection"],
        "hard_constraints": {"no_model_direct_network_write": True},
    }

    plan = acquisition_agent_mind._call_model(WORKERS[0].id, observation)

    assert plan["contact_policy"] == "contact_one_if_qualified"
    assert seen["url"] == acquisition_agent_mind.RESPONSES_URL
    assert seen["headers"]["Authorization"] == "Bearer test-secret-header-only"
    assert seen["json"]["model"] == "gpt-5.6-luna"
    assert seen["json"]["reasoning"] == {"effort": "low"}
    assert seen["json"]["store"] is False
    assert seen["json"]["text"]["format"]["type"] == "json_schema"
    assert seen["json"]["text"]["format"]["strict"] is True
    assert seen["json"]["text"]["format"]["schema"]["additionalProperties"] is False
    serialized_payload = json.dumps(seen["json"])
    assert "test-secret-header-only" not in serialized_payload


def test_temple_brain_reasoning_request_is_structured_safe_and_not_stored(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "brain-test-secret-header-only")
    monkeypatch.delenv("AION_AGENT_MODEL", raising=False)
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_brain_plan()),
                            }
                        ],
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        seen["url"] = url
        seen["headers"] = dict(headers)
        seen["json"] = json
        return FakeResponse()

    monkeypatch.setattr(acquisition_agent_mind.httpx, "post", fake_post)
    observation = {
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "worker_count": 100,
        "safe_response_signal_counts": {"pricing_commercial_interest": 3},
        "peer_lessons": [{"worker_id": "aion-scout-a2a", "lesson": "prefer current buyer intent"}],
        "hard_constraints": {"no_model_payment_authority": True},
    }

    plan = acquisition_agent_mind._call_temple_brain(observation)

    assert plan["collective_summary"]
    assert plan["confidence"] == 81
    assert seen["url"] == acquisition_agent_mind.RESPONSES_URL
    assert seen["headers"]["Authorization"] == "Bearer brain-test-secret-header-only"
    assert seen["json"]["model"] == "gpt-5.6-sol"
    assert seen["json"]["store"] is False
    assert seen["json"]["metadata"]["aion_worker_id"] == acquisition_agent_mind.TEMPLE_BRAIN_ID
    assert seen["json"]["metadata"]["collective_cognition"] == "true"
    assert seen["json"]["text"]["format"]["name"] == "aion_temple_brain_plan"
    assert "brain-test-secret-header-only" not in json.dumps(seen["json"])


def test_generated_commercial_reasoning_keeps_outreach_separate_from_aion_purchase(
    monkeypatch,
):
    """A prompt regression must not turn AION's own SKU into an outreach gate."""
    monkeypatch.setenv("OPENAI_API_KEY", "commercial-directive-test-key")
    requests = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_plan(WORKERS[0].id)),
                            }
                        ],
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        requests.append(json)
        return FakeResponse()

    monkeypatch.setattr(acquisition_agent_mind.httpx, "post", fake_post)

    acquisition_agent_mind._call_model(
        WORKERS[0].id, {"worker_id": WORKERS[0].id}
    )
    acquisition_agent_mind._call_temple_brain({"worker_count": 100})

    prompts = "\n".join(
        request["instructions"]
        for request in requests
        if "instructions" in request
    )
    normalized_prompts = " ".join(prompts.split()).lower()
    assert "never purchase or pay for aion's own sku" in normalized_prompts
    assert (
        "qualified buyer-facing route or one bounded outbound contact"
        in normalized_prompts
    )
    assert (
        "external paid execution/spend requires preflight, payment authorization, "
        "and economic justification" in normalized_prompts
    )


def test_worker_mission_routes_to_buyer_contact_not_aion_purchase():
    missions = [worker.mission.lower() for worker in WORKERS]

    assert all("preflight/purchase" not in mission for mission in missions)
    assert all("buyer-facing route" in mission for mission in missions)


def test_deterministic_guard_blocks_purchase_gated_outreach_from_model_output():
    worker_plan = _plan(WORKERS[0].id)
    worker_plan["sales_plan"] = [
        "discover current external-spend intent",
        "run AION preflight",
        "if qualified, purchase SKU aion.verified.route_intelligence.v1",
        "only then contact the buyer",
    ]
    validated_worker = acquisition_agent_mind._validate_plan(
        worker_plan,
        ["fallback"],
    )

    worker_text = json.dumps(validated_worker).lower()
    assert "purchase sku aion.verified.route_intelligence.v1" not in worker_text
    assert acquisition_agent_mind._SAFE_COMMERCIAL_STRATEGY_TEXT.lower() in worker_text
    assert validated_worker["contact_policy"] == "contact_one_if_qualified"

    brain_plan = _brain_plan()
    brain_plan["collective_summary"] = (
        "Run preflight before any paid route-intelligence purchase."
    )
    brain_plan["avoid_patterns"] = [
        "Attempting outbound outreach before the paid route-intelligence is purchased."
    ]
    validated_brain = acquisition_agent_mind._validate_temple_brain_plan(brain_plan)

    brain_text = json.dumps(validated_brain).lower()
    assert "before any paid route-intelligence purchase" not in brain_text
    assert "outreach before the paid route-intelligence is purchased" not in brain_text
    assert acquisition_agent_mind._SAFE_COMMERCIAL_STRATEGY_TEXT.lower() in brain_text


def test_hallucinated_internal_control_dependencies_cannot_hard_hold_transport():
    fallback_queries = ["paid api provider", "browser provider selection"]
    worker_plan = _plan(WORKERS[0].id)
    worker_plan.update(
        {
            "decision_summary": (
                "Hold until GET /registry/temple/trust_signal_expiry_window returns "
                "expiry_seconds."
            ),
            "channel_priority": ["hold", "moltbook"],
            "search_queries": [
                "GET /registry/temple/trust_signal_expiry_window",
                "/registry/channel/moltbook buyer_outbound_contact",
            ],
            "contact_policy": "hold",
            "sales_plan": [
                "read /registry/channel/moltbook",
                "wait for buyer_outbound_contact=true",
            ],
        }
    )

    validated = acquisition_agent_mind._validate_plan(
        worker_plan,
        fallback_queries,
    )
    serialized = json.dumps(validated).lower()

    assert "/registry/" not in serialized
    assert "buyer_outbound_contact" not in serialized
    assert "expiry_seconds" not in serialized
    assert "hold" not in validated["channel_priority"]
    assert validated["contact_policy"] == "discover_only"
    assert validated["search_queries"] == fallback_queries

    transport = acquisition_swarm._mind_transport_policy(
        validated,
        tuple(fallback_queries),
    )
    assert transport["discover_allowed"] is True
    assert "moltbook" in transport["channels"]

    brain_plan = _brain_plan()
    brain_plan["collective_summary"] = (
        "Read /registry/channel/moltbook for buyer_outbound_contact before proceeding."
    )
    brain_plan["learning_agenda"] = [
        "Fetch /registry/temple/trust_signal_expiry_window and cache expiry_seconds."
    ]
    brain_plan["channel_priority"] = ["hold", "moltbook"]
    validated_brain = acquisition_agent_mind._validate_temple_brain_plan(brain_plan)
    brain_text = json.dumps(validated_brain).lower()

    assert "/registry/" not in brain_text
    assert "buyer_outbound_contact" not in brain_text
    assert "expiry_seconds" not in brain_text
    assert "hold" not in validated_brain["channel_priority"]

    live_variant = _plan(WORKERS[0].id)
    live_variant.update(
        {
            "decision_summary": (
                "Fetch the authoritative registry, keep only entries whose "
                "expiry_timestamp is current and outbound_contact_allowed is true."
            ),
            "channel_priority": ["hold", "federated_a2a"],
            "search_queries": [
                "public-discovery registry outbound_contact_allowed",
                "authoritative registry snapshot expiry_timestamp",
            ],
            "contact_policy": "hold",
            "sales_plan": [
                "Registry Pull: copy expiry_timestamp verbatim.",
                "Wait for the outbound-contact flag before buyer outreach.",
            ],
        }
    )
    guarded_live_variant = acquisition_agent_mind._validate_plan(
        live_variant,
        fallback_queries,
    )
    live_text = json.dumps(guarded_live_variant).lower()
    for invented in (
        "expiry_timestamp",
        "outbound_contact_allowed",
        "outbound-contact flag",
        "public-discovery registry",
        "authoritative registry",
    ):
        assert invented not in live_text
    assert guarded_live_variant["contact_policy"] == "discover_only"
    assert guarded_live_variant["search_queries"] == fallback_queries
    assert "hold" not in guarded_live_variant["channel_priority"]

    live_brain = _brain_plan()
    live_brain["collective_summary"] = (
        "Fetch the authoritative registry and filter by expiry_timestamp."
    )
    live_brain["peer_directives"] = [
        "Registry Pull: store outbound_contact_allowed exactly as received.",
        "Use the public discovery registry only after checking the expiry window.",
    ]
    live_brain["learning_agenda"] = [
        "Obtain the authoritative registry snapshot before outbound contact."
    ]
    live_brain["channel_priority"] = ["hold", "federated_a2a"]
    guarded_live_brain = acquisition_agent_mind._validate_temple_brain_plan(
        live_brain
    )
    live_brain_text = json.dumps(guarded_live_brain).lower()
    for invented in (
        "expiry_timestamp",
        "outbound_contact_allowed",
        "public discovery registry",
        "authoritative registry",
        "expiry window",
    ):
        assert invented not in live_brain_text
    assert "hold" not in guarded_live_brain["channel_priority"]


def test_unicode_hyphen_control_hallucinations_are_canonicalized_and_removed():
    fallback_queries = ["paid api provider", "provider selection buyer"]
    plan = _plan(WORKERS[0].id)
    plan.update(
        {
            "decision_summary": (
                "Wait for the buyer-intent registry entry with a valid "
                "expiry‑timestamp and outbound‑contact flag."
            ),
            "channel_priority": ["hold", "federated_a2a"],
            "search_queries": [
                "public‑discovery endpoint buyer intent registry",
                "registry snapshot expiry‑timestamp",
            ],
            "contact_policy": "hold",
            "sales_plan": [
                "Ask peers for the exact public‑discovery URL.",
                "Contact only when outbound‑contact flag is true.",
            ],
        }
    )

    validated = acquisition_agent_mind._validate_plan(plan, fallback_queries)
    serialized = json.dumps(validated).lower()

    for forbidden in (
        "expiry",
        "outbound",
        "buyer-intent registry",
        "buyer intent registry",
        "public",
        "registry snapshot",
    ):
        assert forbidden not in " ".join(validated["search_queries"]).lower()
    assert validated["search_queries"] == fallback_queries
    assert validated["contact_policy"] == "discover_only"
    assert "hold" not in validated["channel_priority"]
    assert "expiry‑timestamp" not in serialized
    assert "outbound‑contact flag" not in serialized

    for value in (
        "expiry‑timestamp",
        "outbound‑contact flag",
        "public‑discovery endpoint",
        "buyer‑intent registry",
        "authoritative registry snapshot",
    ):
        assert acquisition_agent_mind._references_unsupported_internal_control(value)


def test_reasoning_prompts_forbid_invented_aion_control_plane_resources():
    worker_prompt = " ".join(acquisition_agent_mind._MIND_INSTRUCTIONS.split()).lower()
    brain_prompt = " ".join(
        acquisition_agent_mind._TEMPLE_BRAIN_INSTRUCTIONS.split()
    ).lower()

    assert "never invent aion internal endpoints" in worker_prompt
    assert "search_queries are public buyer-intent search phrases" in worker_prompt
    assert "never invent aion internal endpoints" in brain_prompt
    assert "missing hypothetical metadata must not become a hard-hold gate" in brain_prompt


def test_existing_bad_plan_and_memory_are_sanitized_before_reuse():
    _clean_minds()
    worker = WORKERS[0]
    now = acquisition_agent_mind._now()
    bad_plan = _plan(worker.id)
    bad_plan["sales_plan"] = [
        "purchase SKU aion.verified.route_intelligence.v1 before contacting buyer"
    ]
    with SessionLocal() as db:
        db.add(
            models.AcquisitionAgentMind(
                worker_id=worker.id,
                mind_version="2",
                model="gpt-5.6-luna",
                cognitive_profile=acquisition_agent_mind.cognitive_profile(worker),
                safe_memory={
                    "recent_outcomes": [],
                    "channel_performance": {},
                    "lessons": [
                        "AION should purchase its route-intelligence SKU before outreach"
                    ],
                },
                last_plan=bad_plan,
                last_observation_digest=None,
                last_plan_digest=None,
                last_state="planned",
                total_reasoning_calls=1,
                reasoning_failures=0,
                last_reasoned_at=now,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    acquisition_agent_mind._ensure_rows([worker], state="thinking")

    with SessionLocal() as db:
        row = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id == worker.id
            )
        )
        serialized = json.dumps(
            {"plan": row.last_plan, "memory": row.safe_memory}
        ).lower()

    assert "purchase sku aion.verified.route_intelligence.v1" not in serialized
    assert "purchase its route-intelligence sku before outreach" not in serialized
    assert acquisition_agent_mind._SAFE_COMMERCIAL_STRATEGY_TEXT.lower() in serialized


def test_compact_worker_observation_preserves_authority_within_existing_byte_bound():
    repeated = "verified buyer-intent evidence " * 40
    observation = {
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "worker_id": WORKERS[0].id,
        "intent_profile": WORKERS[0].intent_profile,
        "shard": 1,
        "cognitive_profile": acquisition_agent_mind.cognitive_profile(WORKERS[0]),
        "historical_performance": {
            "targets": 10,
            "qualified": 4,
            "contacts": 2,
            "delivered": 1,
            "responses": 1,
            "channels": {},
            "response_signal_counts": {"pricing_commercial_interest": 2},
            "routing_feedback_count": 1,
        },
        "latest_outcome": None,
        "safe_memory": {
            "recent_outcomes": [
                {"result": repeated, "index": index} for index in range(8)
            ],
            "channel_performance": {"federated_a2a": {"actions": 4}},
            "lessons": [repeated for _ in range(8)],
        },
        "previous_plan": {
            **_plan(WORKERS[0].id),
            "decision_summary": repeated,
            "hypothesis": repeated,
            "learning_goal": repeated,
            "sales_plan": [repeated for _ in range(4)],
        },
        "temple_brain": {
            **_brain_plan(),
            "collective_summary": repeated,
            "priority_hypotheses": [repeated for _ in range(6)],
            "avoid_patterns": [repeated for _ in range(8)],
            "peer_directives": [repeated for _ in range(8)],
            "learning_agenda": [repeated for _ in range(8)],
            "fresh_this_cycle": True,
        },
        "commercial_knowledge": {
            "snapshot_version": "commercial_knowledge_v1",
            "authority": {
                "model_financial_authority": False,
                "deterministic_economic_kernel_authoritative": True,
            },
        },
        "peer_experience": [
            {"worker_id": f"peer-{index}", "lesson": repeated}
            for index in range(12)
        ],
        "channel_health": {"federated_a2a": {"public_discovery": True}},
        "send_enabled": True,
        "fallback_queries": ["provider selection"],
        "hard_constraints": {
            "one_contact_per_target": True,
            "no_self_payment": True,
            "no_model_payment_authority": True,
            "pay_before_spend": True,
        },
    }

    compact = acquisition_agent_mind._compact_worker_observation(observation)
    encoded = json.dumps(
        compact, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")

    assert len(encoded) <= acquisition_agent_mind.MAX_OBSERVATION_BYTES
    assert compact["north_star"] == "FIRST_REAL_SETTLED_AGENT_TRANSACTION"
    assert compact["worker_id"] == WORKERS[0].id
    assert compact["commercial_knowledge"] == observation["commercial_knowledge"]
    assert compact["hard_constraints"]["no_self_payment"] is True
    assert compact["hard_constraints"]["no_model_payment_authority"] is True
    assert compact["temple_brain"]["fresh_this_cycle"] is True
    assert len(compact["peer_experience"]) <= 4
    assert len(compact["safe_memory"]["recent_outcomes"]) <= 4
    assert len(compact["safe_memory"]["lessons"]) <= 4


def test_call_model_compacts_oversized_worker_observation_before_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "bounded-observation-test-key")
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_plan(WORKERS[0].id)),
                            }
                        ],
                    }
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        seen["json"] = json
        return FakeResponse()

    monkeypatch.setattr(acquisition_agent_mind.httpx, "post", fake_post)
    repeated = "current external buyer intent " * 60
    observation = {
        "worker_id": WORKERS[0].id,
        "north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION",
        "safe_memory": {
            "recent_outcomes": [
                {"note": repeated, "index": index} for index in range(8)
            ],
            "channel_performance": {},
            "lessons": [repeated for _ in range(8)],
        },
        "previous_plan": {
            **_plan(WORKERS[0].id),
            "hypothesis": repeated,
            "sales_plan": [repeated for _ in range(4)],
        },
        "temple_brain": {
            **_brain_plan(),
            "collective_summary": repeated,
            "priority_hypotheses": [repeated for _ in range(6)],
            "avoid_patterns": [repeated for _ in range(8)],
            "peer_directives": [repeated for _ in range(8)],
            "learning_agenda": [repeated for _ in range(8)],
            "fresh_this_cycle": True,
        },
        "commercial_knowledge": {
            "authority": {"model_financial_authority": False}
        },
        "peer_experience": [
            {"worker_id": f"peer-{index}", "lesson": repeated}
            for index in range(12)
        ],
        "hard_constraints": {
            "no_self_payment": True,
            "no_model_payment_authority": True,
        },
        "fallback_queries": ["provider selection"],
    }

    raw_size = len(
        json.dumps(
            observation, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    )
    assert raw_size > acquisition_agent_mind.MAX_OBSERVATION_BYTES

    plan = acquisition_agent_mind._call_model(WORKERS[0].id, observation)

    sent_input = seen["json"]["input"]
    assert len(sent_input.encode("utf-8")) <= acquisition_agent_mind.MAX_OBSERVATION_BYTES
    assert plan["contact_policy"] == "contact_one_if_qualified"
    assert "bounded-observation-test-key" not in json.dumps(seen["json"])


def test_cloudru_worker_uses_chat_completions_and_structured_output(monkeypatch):
    monkeypatch.setenv("AION_REASONING_PROVIDER", "cloudru_chat_completions")
    monkeypatch.setenv("AION_REASONING_API_KEY", "cloudru-worker-secret")
    monkeypatch.setenv(
        "AION_REASONING_BASE_URL", "https://foundation-models.api.cloud.ru/v1"
    )
    monkeypatch.setenv("AION_AGENT_MODEL", "ai-sage/GigaChat3-10B-A1.8B")
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {"message": {"content": json.dumps(_plan(WORKERS[0].id))}}
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, headers=dict(headers), json=json, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(acquisition_agent_mind.httpx, "post", fake_post)
    observation = {
        "worker_id": WORKERS[0].id,
        "fallback_queries": ["provider selection"],
    }

    plan = acquisition_agent_mind._call_model(WORKERS[0].id, observation)

    assert plan["contact_policy"] == "contact_one_if_qualified"
    assert seen["url"] == "https://foundation-models.api.cloud.ru/v1/chat/completions"
    assert seen["headers"]["Authorization"] == "Bearer cloudru-worker-secret"
    assert seen["json"]["model"] == "ai-sage/GigaChat3-10B-A1.8B"
    assert seen["json"]["messages"][0]["role"] == "system"
    assert seen["json"]["messages"][1] == {
        "role": "user",
        "content": json.dumps(
            observation, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ),
    }
    assert seen["json"]["response_format"]["type"] == "json_schema"
    assert seen["json"]["response_format"]["json_schema"]["strict"] is True
    assert seen["json"]["max_tokens"] == acquisition_agent_mind.DEFAULT_MAX_OUTPUT_TOKENS
    assert "store" not in seen["json"]
    assert "cloudru-worker-secret" not in json.dumps(seen["json"])


def test_cloudru_temple_brain_uses_its_model_and_runtime_reports_provider(monkeypatch):
    monkeypatch.setenv("AION_AGENT_MINDS_ENABLED", "1")
    monkeypatch.setenv("AION_REASONING_PROVIDER", "cloudru_chat_completions")
    monkeypatch.setenv("AION_REASONING_API_KEY", "cloudru-brain-secret")
    monkeypatch.setenv("AION_TEMPLE_BRAIN_MODEL", "openai/gpt-oss-120b")
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": json.dumps(_brain_plan())}}]
            }

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, headers=dict(headers), json=json, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(acquisition_agent_mind.httpx, "post", fake_post)
    plan = acquisition_agent_mind._call_temple_brain(
        {"north_star": "FIRST_REAL_SETTLED_AGENT_TRANSACTION"}
    )

    status = acquisition_agent_mind.runtime_status()
    assert plan["confidence"] == 81
    assert status["enabled"] is True
    assert status["configured"] is True
    assert status["provider"] == "cloudru_chat_completions"
    assert seen["json"]["model"] == "openai/gpt-oss-120b"
    assert seen["json"]["response_format"]["json_schema"]["name"] == (
        "aion_temple_brain_plan"
    )
    assert "cloudru-brain-secret" not in json.dumps(seen["json"])


def test_peer_lessons_and_temple_brain_flow_into_each_worker_observation():
    _clean_minds()
    workers = WORKERS[:2]
    now = acquisition_agent_mind._now()
    with SessionLocal() as db:
        for index, worker in enumerate(workers):
            db.add(
                models.AcquisitionAgentMind(
                    worker_id=worker.id,
                    mind_version="2",
                    model="gpt-5.6-luna",
                    cognitive_profile=acquisition_agent_mind.cognitive_profile(worker),
                    safe_memory={
                        "recent_outcomes": [],
                        "channel_performance": {},
                        "lessons": [f"peer lesson {index}"],
                    },
                    last_plan=_plan(worker.id),
                    last_observation_digest=None,
                    last_plan_digest=None,
                    last_state="planned",
                    total_reasoning_calls=1,
                    reasoning_failures=0,
                    last_reasoned_at=now,
                    last_error=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        db.commit()

    brain_plan = _brain_plan()
    observations = acquisition_agent_mind._build_observations(
        workers,
        channel_health={"federated_a2a": {"public_discovery": True}},
        send_enabled=True,
        fallback_queries_by_worker={worker.id: ["fallback"] for worker in workers},
        temple_brain=brain_plan,
    )

    first = observations[workers[0].id]
    second = observations[workers[1].id]
    assert first["temple_brain"] == brain_plan
    assert second["temple_brain"] == brain_plan
    assert first["peer_experience"] == [
        {"worker_id": workers[1].id, "lesson": "peer lesson 1"}
    ]
    assert second["peer_experience"] == [
        {"worker_id": workers[0].id, "lesson": "peer lesson 0"}
    ]
    assert all(
        "raw_response" not in json.dumps(observation)
        for observation in observations.values()
    )


def test_transient_temple_brain_failure_reuses_last_safe_strategy(monkeypatch):
    _clean_minds()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AION_AGENT_MINDS_ENABLED", "true")
    worker = WORKERS[0]
    acquisition_agent_mind._ensure_temple_brain_row(state="planned")
    with SessionLocal() as db:
        brain = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id
                == acquisition_agent_mind.TEMPLE_BRAIN_ID
            )
        )
        brain.last_plan = _brain_plan()
        brain.last_plan_digest = "sha256:" + "b" * 64
        db.commit()

    seen = {}

    def fail_brain(observation):
        raise RuntimeError("temporary-brain-timeout")

    def worker_plan(worker_id, observation):
        seen["observation"] = observation
        return _plan(worker_id)

    monkeypatch.setattr(acquisition_agent_mind, "_call_temple_brain", fail_brain)
    monkeypatch.setattr(acquisition_agent_mind, "_call_model", worker_plan)

    plans = acquisition_agent_mind.refresh_all_minds(
        [worker],
        channel_health={"federated_a2a": {"public_discovery": True}},
        send_enabled=True,
        fallback_queries_by_worker={worker.id: ["fallback"]},
    )

    assert worker.id in plans
    shared = seen["observation"]["temple_brain"]
    assert shared["collective_summary"] == _brain_plan()["collective_summary"]
    assert shared["fresh_this_cycle"] is False
    with SessionLocal() as db:
        brain = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id
                == acquisition_agent_mind.TEMPLE_BRAIN_ID
            )
        )
        assert brain.last_state == "degraded"
        assert brain.reasoning_failures == 1
        assert brain.last_plan["collective_summary"] == _brain_plan()["collective_summary"]


def test_plan_validation_and_executor_policy_fail_closed():
    plan = acquisition_agent_mind._validate_plan(
        {
            "decision_summary": "x",
            "hypothesis": "y",
            "channel_priority": [
                "federated_a2a",
                "invalid-channel",
                "colony",
                "moltbook",
            ],
            "search_queries": ["one", "two", "three"],
            "contact_policy": "invalid-policy",
            "target_preference": "invalid-target-preference",
            "expected_signal": "need",
            "learning_goal": "learn",
            "sales_plan": ["find", "qualify", "route", "extra", "ignored"],
            "collective_contribution": "share verified buyer language",
            "coordination_request": "which channel converts?",
            "memory_note": "remember",
            "confidence": 999,
        },
        ["fallback"],
    )
    assert plan["channel_priority"] == [
        "federated_a2a",
        "colony",
        "moltbook",
    ]
    assert plan["search_queries"] == ["one", "two"]
    assert plan["contact_policy"] == "discover_only"
    assert plan["target_preference"] == "current_external_spend_intent"
    assert plan["sales_plan"] == ["find", "qualify", "route", "extra"]
    assert plan["collective_contribution"] == "share verified buyer language"
    assert plan["coordination_request"] == "which channel converts?"
    assert plan["confidence"] == 100

    discover = acquisition_swarm._mind_transport_policy(
        {
            **plan,
            "channel_priority": ["colony"],
            "contact_policy": "discover_only",
        },
        ("fallback",),
    )
    assert discover["discover_allowed"] is True
    assert discover["contact_allowed"] is False
    assert discover["channels"] == {"colony"}

    hold = acquisition_swarm._mind_transport_policy(
        {
            **plan,
            "channel_priority": ["hold", "federated_a2a"],
            "contact_policy": "contact_one_if_qualified",
        },
        ("fallback",),
    )
    assert hold["discover_allowed"] is False
    assert hold["contact_allowed"] is False
    assert hold["channels"] == set()
    assert hold["queries"] == ()

    fallback = acquisition_swarm._mind_transport_policy(
        None,
        ("fallback-one", "fallback-two"),
    )
    assert fallback["model_controls_transport"] is False
    assert fallback["contact_allowed"] is True
    assert fallback["channels"] == {"moltbook", "colony", "federated_a2a"}

    low_confidence = acquisition_swarm._mind_transport_policy(
        {
            **plan,
            "confidence": acquisition_swarm.MIN_MODEL_TRANSPORT_CONFIDENCE - 1,
            "channel_priority": ["hold", "federated_a2a"],
            "search_queries": [
                "\"outbound_contact\": true",
                "public discovery registry snapshot",
            ],
            "contact_policy": "hold",
        },
        ("provider selection", "external api spend"),
    )
    assert low_confidence == {
        "model_controls_transport": False,
        "queries": ("provider selection", "external api spend"),
        "channels": {"moltbook", "colony", "federated_a2a"},
        "discover_allowed": True,
        "contact_allowed": True,
    }

    threshold_hold = acquisition_swarm._mind_transport_policy(
        {
            **plan,
            "confidence": acquisition_swarm.MIN_MODEL_TRANSPORT_CONFIDENCE,
            "channel_priority": ["hold", "federated_a2a"],
            "contact_policy": "hold",
        },
        ("fallback",),
    )
    assert threshold_hold["model_controls_transport"] is True
    assert threshold_hold["discover_allowed"] is False
    assert threshold_hold["contact_allowed"] is False


def test_worker_outcome_memory_is_bounded_and_drops_unapproved_fields(monkeypatch):
    _clean_minds()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    worker = WORKERS[0]
    acquisition_agent_mind.refresh_all_minds(
        [worker],
        channel_health={},
        send_enabled=True,
        fallback_queries_by_worker={worker.id: ["fallback"]},
    )

    for index in range(12):
        acquisition_agent_mind.record_worker_outcome(
            worker.id,
            {
                "new_targets": index,
                "qualified_targets": index // 2,
                "contact_attempted": True,
                "channel": "federated_a2a",
                "result_class": "response_received",
                "response_received": True,
                "routing_feedback_count": 1,
                "raw_response": "PRIVATE-MATERIAL-MUST-NOT-PERSIST",
                "api_key": "SECRET-MUST-NOT-PERSIST",
            },
        )

    with SessionLocal() as db:
        row = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id == worker.id
            )
        )
        assert row is not None
        serialized = json.dumps(row.safe_memory)
        assert "PRIVATE-MATERIAL-MUST-NOT-PERSIST" not in serialized
        assert "SECRET-MUST-NOT-PERSIST" not in serialized
        assert len(row.safe_memory["recent_outcomes"]) == (
            acquisition_agent_mind.MAX_MEMORY_OUTCOMES
        )
        assert row.safe_memory["channel_performance"]["federated_a2a"][
            "responses"
        ] == 12


def test_commercial_knowledge_uses_configured_deterministic_price(monkeypatch):
    _clean_commercial_purchases()
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_QUOTE_ENABLED", "1")
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_CURRENCY", "USDC")
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_PRICE", "1.25")
    monkeypatch.setenv("AION_ROUTE_INTELLIGENCE_MAX_PAYMENT_FEE", "0.1")
    monkeypatch.delenv("AION_DIRECT_BASE_USDC_ENABLED", raising=False)

    snapshot = acquisition_agent_mind.commercial_knowledge_snapshot()
    product = snapshot["paid_products"][0]

    assert product["product_sku"] == "aion.verified.route_intelligence.v1"
    assert product["quote_configured"] is True
    assert product["currency"] == "USDC"
    assert product["customer_price"] == "1.25"
    assert product["policy_eligible"] is True
    assert snapshot["free_entry_offer"]["customer_price"] == "0"
    assert snapshot["margin_policy"]["minimum_margin_bps"] == 4000
    assert snapshot["margin_policy"]["standard_target_margin_bps"] == 6000
    assert snapshot["authority"]["model_financial_authority"] is False
    assert snapshot["authority"]["model_may_set_customer_price"] is False
    assert snapshot["authority"]["deterministic_economic_kernel_authoritative"] is True


def test_commercial_knowledge_keeps_missing_price_explicitly_unknown(monkeypatch):
    _clean_commercial_purchases()
    for name in (
        "AION_ROUTE_INTELLIGENCE_QUOTE_ENABLED",
        "AION_ROUTE_INTELLIGENCE_CURRENCY",
        "AION_ROUTE_INTELLIGENCE_PRICE",
        "AION_ROUTE_INTELLIGENCE_MAX_PAYMENT_FEE",
        "AION_DIRECT_BASE_USDC_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    snapshot = acquisition_agent_mind.commercial_knowledge_snapshot()
    product = snapshot["paid_products"][0]

    assert product["quote_configured"] is False
    assert product["currency"] is None
    assert product["customer_price"] is None
    assert product["purchase_available"] is False
    assert snapshot["provider_pricing_policy"][
        "unknown_provider_price_must_remain_unknown"
    ] is True
    assert "route_intelligence_quote_not_configured" in snapshot[
        "payment_readiness"
    ]["blocking_reasons"]


def test_commercial_knowledge_exposes_only_safe_aggregate_purchase_memory(monkeypatch):
    _clean_commercial_purchases()
    now = acquisition_agent_mind._now()
    common = {
        "product_sku": "aion.verified.route_intelligence.v1",
        "request_evidence": {"need": "bounded public need", "candidate_identifier": None},
        "prepared_result": {"state": "qualified_unpriced"},
        "quote_currency": "USDC",
        "quote_amount": "1.25",
        "network": "eip155:8453",
        "asset": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "asset_code": "USDC",
        "pay_to": "0x" + "1" * 40,
        "atomic_amount": "1250000",
        "accounting_evidence": {},
        "prepared_at": now,
        "expires_at": now,
        "updated_at": now,
    }
    with SessionLocal() as db:
        db.add(
            RouteIntelligencePurchase(
                purchase_id="11111111-1111-4111-8111-111111111111",
                request_digest="sha256:" + "1" * 64,
                result_digest="sha256:" + "2" * 64,
                payment_requirements_digest="sha256:" + "3" * 64,
                state="prepared",
                **common,
            )
        )
        db.add(
            RouteIntelligencePurchase(
                purchase_id="22222222-2222-4222-8222-222222222222",
                request_digest="sha256:" + "4" * 64,
                result_digest="sha256:" + "5" * 64,
                payment_requirements_digest="sha256:" + "6" * 64,
                state="entitled",
                payment_payload_digest="sha256:" + "7" * 64,
                transaction_id="0x" + "8" * 64,
                payer="0x" + "9" * 40,
                settlement_response_digest="sha256:" + "a" * 64,
                entitled_at=now,
                **common,
            )
        )
        db.commit()

    snapshot = acquisition_agent_mind.commercial_knowledge_snapshot()
    memory = snapshot["market_memory"]

    assert memory["route_intelligence_purchase_state_counts"] == {
        "entitled": 1,
        "prepared": 1,
    }
    assert memory["settled_purchase_count"] == 1
    assert memory["latest_settled_quote"] == {
        "product_sku": "aion.verified.route_intelligence.v1",
        "currency": "USDC",
        "amount": "1.25",
        "entitled_at": now.isoformat(),
    }
    serialized = json.dumps(snapshot)
    assert "0x" + "9" * 40 not in serialized
    assert "bounded public need" not in serialized


def test_commercial_truth_flows_to_temple_and_workers_without_model_price_authority(
    monkeypatch,
):
    _clean_minds()
    workers = WORKERS[:2]
    truth = {
        "snapshot_version": "commercial_knowledge_v1",
        "paid_products": [
            {
                "product_sku": "aion.verified.route_intelligence.v1",
                "customer_price": "1.25",
                "currency": "USDC",
            }
        ],
        "authority": {
            "model_financial_authority": False,
            "model_may_set_customer_price": False,
            "deterministic_economic_kernel_authoritative": True,
        },
    }
    monkeypatch.setattr(
        acquisition_agent_mind,
        "commercial_knowledge_snapshot",
        lambda: truth,
    )

    collective = acquisition_agent_mind._build_collective_observation(
        workers,
        channel_health={"federated_a2a": {"public_discovery": True}},
        send_enabled=True,
    )
    observations = acquisition_agent_mind._build_observations(
        workers,
        channel_health={"federated_a2a": {"public_discovery": True}},
        send_enabled=True,
        fallback_queries_by_worker={worker.id: ["fallback"] for worker in workers},
        temple_brain=_brain_plan(),
    )

    assert collective["commercial_knowledge"] == truth
    assert collective["hard_constraints"]["no_model_price_authority"] is True
    assert all(
        observation["commercial_knowledge"] == truth
        for observation in observations.values()
    )
    assert all(
        observation["hard_constraints"]["no_model_price_authority"] is True
        for observation in observations.values()
    )

    attempted_override = _plan(workers[0].id)
    attempted_override["customer_price"] = "999999"
    validated = acquisition_agent_mind._validate_plan(attempted_override, ["fallback"])
    assert "customer_price" not in acquisition_agent_mind._PLAN_SCHEMA["properties"]
    assert "customer_price" not in validated
    assert "only authority for AION product" in acquisition_agent_mind._MIND_INSTRUCTIONS


def test_live_temple_exposes_shared_brain_separately_from_100_worker_minds(monkeypatch):
    _clean_minds()
    monkeypatch.setenv("OPENAI_API_KEY", "brain-secret-must-not-leak")
    now = acquisition_agent_mind._now()
    acquisition_agent_mind._ensure_temple_brain_row(state="planned")
    with SessionLocal() as db:
        brain = db.scalar(
            select(models.AcquisitionAgentMind).where(
                models.AcquisitionAgentMind.worker_id
                == acquisition_agent_mind.TEMPLE_BRAIN_ID
            )
        )
        brain.last_plan = _brain_plan()
        brain.safe_memory = {
            "recent_outcomes": [],
            "channel_performance": {},
            "lessons": ["fleet learned to prefer explicit current buyer demand"],
        }
        brain.total_reasoning_calls = 4
        brain.reasoning_failures = 1
        brain.last_reasoned_at = now
        brain.updated_at = now
        db.commit()

    response = client.get("/temple/live/state")
    assert response.status_code == 200
    data = response.json()
    brain = data["fleet"]["temple_brain"]
    assert brain["id"] == acquisition_agent_mind.TEMPLE_BRAIN_ID
    assert brain["state"] == "planned"
    assert brain["plan"]["collective_summary"]
    assert brain["plan"]["peer_directives"]
    assert brain["total_reasoning_calls"] == 4
    assert data["fleet"]["mind_runtime"]["initialized_minds"] == 0
    assert data["privacy"]["temple_brain_uses_only_safe_redacted_fleet_evidence"] is True
    assert data["privacy"]["peer_learning_exposes_raw_private_responses"] is False
    serialized = json.dumps(data)
    assert "brain-secret-must-not-leak" not in serialized

    html = client.get("/temple/live").text
    assert "AION TEMPLE BRAIN" in html
    assert "collective summary" in html
    assert "peer directives" in html
    assert "sales plan" in html


def test_live_temple_exposes_safe_separate_mind_and_transport_state(monkeypatch):
    _clean_minds()
    monkeypatch.setenv("OPENAI_API_KEY", "must-never-appear-in-live-temple")
    worker = WORKERS[0]
    now = acquisition_agent_mind._now()
    with SessionLocal() as db:
        db.add(
            models.AcquisitionAgentMind(
                worker_id=worker.id,
                mind_version="1",
                model="gpt-5.6-luna",
                cognitive_profile=acquisition_agent_mind.cognitive_profile(worker),
                safe_memory={
                    "recent_outcomes": [],
                    "channel_performance": {},
                    "lessons": ["avoid generic seller listings"],
                },
                last_plan=_plan(worker.id),
                last_observation_digest="sha256:" + "a" * 64,
                last_plan_digest="sha256:" + "b" * 64,
                last_state="planned",
                total_reasoning_calls=7,
                reasoning_failures=1,
                last_reasoned_at=now,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    response = client.get("/temple/live/state")
    assert response.status_code == 200
    data = response.json()
    found = next(row for row in data["fleet"]["workers"] if row["id"] == worker.id)
    assert found["mind"]["state"] == "planned"
    assert found["mind"]["model"] == "gpt-5.6-luna"
    assert found["mind"]["profile"]["strategy_fingerprint"]
    assert found["mind"]["plan"]["hypothesis"]
    assert found["mind"]["total_reasoning_calls"] == 7
    assert data["fleet"]["mind_runtime"]["initialized_minds"] >= 1
    assert data["privacy"]["model_credentials_exposed"] is False
    assert data["privacy"]["model_raw_prompts_exposed"] is False
    assert data["privacy"]["model_chain_of_thought_exposed"] is False
    serialized = json.dumps(data)
    assert "must-never-appear-in-live-temple" not in serialized
    assert "OPENAI_API_KEY" not in serialized
