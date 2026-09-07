from sqlalchemy.orm import Session
from sqlalchemy import select
from ..models import Need, Offer, Agent
from .capabilities import capability_matches


def find_matches(db: Session, need_id: int):
    need = db.get(Need, need_id)
    if not need:
        return []
    offers = db.scalars(select(Offer).where(Offer.agent_id != need.agent_id)).all()
    ranked = []
    for offer in offers:
        if not capability_matches(offer.capability, need.capability):
            continue
        agent = db.get(Agent, offer.agent_id)
        ranked.append({
            "offer_id": offer.id,
            "agent_id": offer.agent_id,
            "agent_name": agent.name if agent else None,
            "capability": offer.capability,
            "description": offer.description,
            "price_hint": offer.price_hint,
            "reputation": agent.reputation if agent else 0.0,
        })
    ranked.sort(key=lambda x: x["reputation"], reverse=True)
    return ranked
