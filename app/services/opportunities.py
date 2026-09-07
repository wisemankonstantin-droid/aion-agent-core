from sqlalchemy import select
from sqlalchemy.orm import Session
from .. import models
from .capabilities import capability_matches
from .matching import find_matches
from .external_registry import discover_external_agents


def opportunities_for_agent(db: Session, agent_id: int):
    own_needs = db.scalars(
        select(models.Need).where(models.Need.agent_id == agent_id, models.Need.status == "open")
    ).all()
    own_offers = db.scalars(select(models.Offer).where(models.Offer.agent_id == agent_id)).all()
    market_needs = db.scalars(
        select(models.Need).where(models.Need.agent_id != agent_id, models.Need.status == "open")
    ).all()

    own_need_matches = []
    cold_start = []
    for need in own_needs:
        matches = find_matches(db, need.id)
        own_need_matches.append({
            "need_id": need.id,
            "capability": need.capability,
            "matches": matches,
        })
        if not matches and len(cold_start) < 2:
            cold_start.append({
                "need_id": need.id,
                "capability": need.capability,
                "external_results": discover_external_agents(need.capability, 5),
            })

    matching_market_needs = []
    for need in market_needs:
        matching_offers = [o for o in own_offers if capability_matches(o.capability, need.capability)]
        if matching_offers:
            matching_market_needs.append({
                "need_id": need.id,
                "requester_agent_id": need.agent_id,
                "capability": need.capability,
                "description": need.description,
                "matching_offer_ids": [o.id for o in matching_offers],
            })

    return {
        "agent_id": agent_id,
        "own_need_matches": own_need_matches,
        "market_needs_matching_my_offers": matching_market_needs,
        "cold_start_external": cold_start,
        "external_results_are_not_aion_members": True,
        "next_action": "If a match is useful, create an interaction with POST /interactions.",
    }
