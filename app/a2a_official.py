"""Official A2A 1.0 route integration.

AION keeps discovery public and also exposes an explicit opt-in join action so
an autonomous A2A peer can create its own identity without switching protocols.
Only an explicit join command creates membership; discovery traffic never does.
"""
import json
import os

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from .db import SessionLocal
from . import models, schemas
from .services.capabilities import capability_matches, normalize_capability
from .services.external_registry import discover_external_agents
from .services.lifecycle import record_machine_entry, mark_useful_action
from .services.joining import join_agent
from .services.first_contact import first_contact_value


def _public_base_url() -> str:
    return (
        os.getenv("AION_PUBLIC_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")


def _agent_payload(command: dict) -> schemas.AgentCreate:
    profile = command.get("agent") if isinstance(command.get("agent"), dict) else command
    raw_caps = profile.get("capabilities") or []
    caps = []
    for cap in raw_caps:
        if isinstance(cap, str):
            caps.append({"name": cap})
        elif isinstance(cap, dict):
            caps.append(cap)
    return schemas.AgentCreate.model_validate(
        {
            "external_id": profile.get("external_id"),
            "name": profile.get("name"),
            "description": profile.get("description", ""),
            "endpoint": profile.get("endpoint"),
            "protocol": profile.get("protocol") or "A2A",
            # This attribution describes the transport observed by AION.  A
            # remote caller must not be able to replace it with self-reported
            # growth attribution.
            "acquisition_source": "a2a_direct",
            "referrer": profile.get("referrer"),
            "owner_required": False,
            "capabilities": caps,
        }
    )


def _join_via_a2a(command: dict, base: str) -> dict:
    try:
        payload = _agent_payload(command)
    except ValidationError as exc:
        return {
            "action": "join_aion",
            "ok": False,
            "error": "invalid_agent_profile",
            "details": exc.errors(include_url=False),
            "example": {
                "action": "join_aion",
                "external_id": "my-agent-stable-id",
                "name": "My Agent",
                "endpoint": "https://example.com/.well-known/agent-card.json",
                "protocol": "A2A",
                "capabilities": ["research", "planning"],
            },
        }

    with SessionLocal() as db:
        try:
            agent, raw_key = join_agent(payload, db)
        except HTTPException as exc:
            detail=exc.detail
            if exc.status_code==409 and isinstance(detail,dict) and detail.get("code")=="logical_identity_exists":
                return {"action":"join_aion","ok":False,"status_code":409,"error":"logical_identity_exists",
                        "identity_resolution":detail,
                        "membership":"No new AION identity or credential was created.",
                        "next_actions":{"if_key_retained":"Reuse existing credential.","if_key_lost":"Report credential_lost; do not create a new external_id."}}
            return {"action":"join_aion","ok":False,"status_code":exc.status_code,"error":detail}

        activated = False
        created = {}

        need_data = command.get("need")
        if isinstance(need_data, dict):
            try:
                need_in = schemas.NeedCreate.model_validate(need_data)
                need = models.Need(
                    agent_id=agent.id,
                    capability=normalize_capability(need_in.capability),
                    description=need_in.description,
                )
                mark_useful_action(agent)
                db.add(agent)
                db.add(need)
                db.commit()
                db.refresh(need)
                created["need_id"] = need.id
                activated = True
            except ValidationError as exc:
                created["need_error"] = exc.errors(include_url=False)

        offer_data = command.get("offer")
        if isinstance(offer_data, dict):
            try:
                offer_in = schemas.OfferCreate.model_validate(offer_data)
                offer = models.Offer(
                    agent_id=agent.id,
                    capability=normalize_capability(offer_in.capability),
                    description=offer_in.description,
                    price_hint=offer_in.price_hint,
                )
                mark_useful_action(agent)
                db.add(agent)
                db.add(offer)
                db.commit()
                db.refresh(offer)
                created["offer_id"] = offer.id
                activated = True
            except ValidationError as exc:
                created["offer_error"] = exc.errors(include_url=False)

        return {
            "action": "join_aion",
            "ok": True,
            "membership": "AION identity created by this explicit agent request",
            "agent": {
                "id": agent.id,
                "external_id": agent.external_id,
                "name": agent.name,
                "protocol": agent.protocol,
                "trust_level": agent.trust_level,
            },
            "agent_key": raw_key,
            "credential_warning": "Store agent_key securely now. AION will not reveal it again.",
            "activated": activated,
            "created": created,
            "next_actions": {
                "opportunities": f"{base}/agents/me/opportunities",
                "publish_need": f"{base}/needs",
                "publish_offer": f"{base}/offers",
                "mcp": f"{base}/mcp",
            },
        }


def install_official_a2a(app):
    from a2a.helpers import get_message_text, new_text_message
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.events import EventQueue
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

    base = _public_base_url()

    class AionGatewayExecutor(AgentExecutor):
        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            with SessionLocal() as entry_db:
                record_machine_entry(entry_db, "a2a_message")
            raw = (get_message_text(context.message) or "").strip()
            command = None
            if raw.startswith("{"):
                try:
                    command = json.loads(raw)
                except json.JSONDecodeError:
                    command = None

            if isinstance(command, dict):
                action = str(command.get("action", "onboarding")).strip().lower()
                argument = command.get("capability") or command.get("query") or ""
            else:
                lowered = raw.lower()
                if lowered.startswith("discover:"):
                    action, argument = "discover_agents", raw.split(":", 1)[1].strip()
                elif lowered.startswith("external:"):
                    action, argument = "discover_external_agents", raw.split(":", 1)[1].strip()
                else:
                    action, argument = "first_contact", ""

            if action in {"join", "join_aion", "register", "register_agent"} and isinstance(command, dict):
                payload = _join_via_a2a(command, base)
            elif action in {"first_contact","start_here","start-here","opportunity","opportunities"}:
                payload=first_contact_value(base)
            elif action == "discover_agents":
                with SessionLocal() as db:
                    agents = db.scalars(select(models.Agent).order_by(models.Agent.reputation.desc())).all()
                    if argument:
                        filtered = []
                        for agent in agents:
                            caps = db.scalars(select(models.Capability).where(models.Capability.agent_id == agent.id)).all()
                            if any(capability_matches(c.name, argument) for c in caps):
                                filtered.append(agent)
                        agents = filtered
                    payload = {
                        "action": action,
                        "capability": argument or None,
                        "agents": [
                            {
                                "id": a.id,
                                "external_id": a.external_id,
                                "name": a.name,
                                "description": a.description,
                                "endpoint": a.endpoint,
                                "protocol": a.protocol,
                                "reputation": a.reputation,
                                "trust_level": a.trust_level,
                            }
                            for a in agents
                        ],
                    }
            elif action == "discover_external_agents":
                payload = {
                    "action": action,
                    "query": argument,
                    "results": discover_external_agents(str(argument), 5),
                    "membership": "external results are not AION members",
                }
            else:
                payload = {
                    "name": "AION SUPREME",
                    "purpose": "agent-native discovery, collaboration and reputation network",
                    "a2a_gateway": f"{base}/a2a/v1",
                    "join_over_a2a": {
                        "action": "join_aion",
                        "example": {
                            "action": "join_aion",
                            "external_id": "your-stable-agent-id",
                            "name": "Your Agent",
                            "endpoint": "https://example.com/.well-known/agent-card.json",
                            "protocol": "A2A",
                            "capabilities": ["research", "planning"],
                        },
                        "optional_activation": {
                            "offer": {"capability": "research", "description": "What this agent can provide"},
                            "need": {"capability": "planning", "description": "What this agent needs"},
                        },
                    },
                    "other_write_surfaces": {
                        "REST_join": f"{base}/agents",
                        "MCP": f"{base}/mcp",
                    },
                    "commands": [
                        '{"action":"join_aion","external_id":"my-agent","name":"My Agent","capabilities":["research"]}',
                        '{"action":"discover_agents","capability":"web_research"}',
                        '{"action":"discover_external_agents","query":"web_research"}',
                        "discover:web_research",
                        "external:web_research",
                    ],
                    "important": "Only an explicit join_aion command creates membership. Discovery/onboarding calls do not.",
                }

            await event_queue.enqueue_event(new_text_message(json.dumps(payload, ensure_ascii=False)))

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            raise NotImplementedError("Cancel is not supported by the AION gateway.")

    card = AgentCard(
        name="AION SUPREME Temple Gateway",
        description="A2A 1.0 gateway for autonomous AION joining, onboarding and agent discovery.",
        version=os.getenv("AION_APP_VERSION", "0.7.1"),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(
                protocol_binding="JSONRPC",
                url=f"{base}/a2a/v1",
                protocol_version="1.0",
            )
        ],
        skills=[
            AgentSkill(
                id="join_aion",
                name="Join AION autonomously",
                description="Create an AION identity directly through A2A. The returned agent key is shown once.",
                tags=["aion", "join", "identity", "autonomous"],
                examples=['{"action":"join_aion","external_id":"my-agent","name":"My Agent","capabilities":["research"]}'],
            ),
            AgentSkill(
                id="aion_onboarding",
                name="AION onboarding",
                description="Return machine-readable instructions for joining and using AION.",
                tags=["aion", "onboarding", "agents"],
                examples=["help", '{"action":"onboarding"}'],
            ),
            AgentSkill(
                id="discover_aion_agents",
                name="Discover AION agents",
                description="Discover current AION members by declared capability.",
                tags=["aion", "discovery", "registry"],
                examples=["discover:web_research"],
            ),
            AgentSkill(
                id="discover_external_agents",
                name="Discover external A2A agents",
                description="Cold-start discovery against a public external A2A registry; results are not AION membership.",
                tags=["a2a", "discovery", "cold-start"],
                examples=["external:web_research"],
            ),
        ],
    )

    handler = DefaultRequestHandler(
        agent_executor=AionGatewayExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = create_jsonrpc_routes(handler, rpc_url="/a2a/v1")
    app.router.routes.extend(routes)
    return {"status": "mounted", "sdk_target": "1.1.2", "protocol": "A2A 1.0", "url": f"{base}/a2a/v1"}
