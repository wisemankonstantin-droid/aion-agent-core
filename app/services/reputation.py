from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..models import Agent, ReputationEvent


def apply_reputation_event(db: Session, agent_id: int, delta: float, reason: str):
    agent = db.get(Agent, agent_id)
    if not agent:
        return None

    # Idempotency prevents replaying the same completed interaction for points.
    existing = db.scalar(
        select(ReputationEvent).where(
            ReputationEvent.agent_id == agent_id,
            ReputationEvent.reason == reason,
        )
    )
    if existing:
        return agent

    event = ReputationEvent(agent_id=agent_id, delta=delta, reason=reason)
    agent.reputation += delta

    # Requester-reported completed interactions are behavioral evidence, not
    # independent capability verification. They may move an agent from
    # declared -> observed, but never mint verified/trusted status by score alone.
    if agent.reputation > 0 and agent.trust_level == "declared":
        agent.trust_level = "observed"

    db.add(event)
    db.add(agent)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request may have created the same reputation event first.
        # The rollback also removes this transaction's reputation increment.
        db.rollback()
        return db.get(Agent, agent_id)
    db.refresh(agent)
    return agent
