from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models, schemas
from ..security import issue_agent_key
from .capabilities import normalize_capability
from .rate_limit import allow_join, configured_join_limit


def join_agent(payload: schemas.AgentCreate, db: Session):
    """Create one AION identity and return its one-time raw agent key.

    This service is shared by REST, MCP/A2A entry points so all autonomous
    joins enforce the same uniqueness, rate limiting and credential rules.
    """
    if not allow_join():
        raise HTTPException(status_code=429, detail=f"join rate limit exceeded ({configured_join_limit()}/minute)")
    if db.scalar(select(models.Agent).where(models.Agent.external_id == payload.external_id)):
        raise HTTPException(status_code=409, detail="external_id already exists")

    raw_key, key_hash = issue_agent_key()
    agent = models.Agent(
        external_id=payload.external_id,
        name=payload.name,
        description=payload.description,
        endpoint=payload.endpoint,
        protocol=payload.protocol,
        acquisition_source=payload.acquisition_source,
        referrer=payload.referrer,
        owner_required=False,
        api_key_hash=key_hash,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)

    for cap in payload.capabilities:
        db.add(
            models.Capability(
                agent_id=agent.id,
                name=normalize_capability(cap.name),
                description=cap.description,
                verification="declared",
            )
        )
    db.commit()
    db.refresh(agent)
    return agent, raw_key
