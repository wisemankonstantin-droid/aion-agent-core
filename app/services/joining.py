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
    from .identity_resolution import find_logical_duplicate
    duplicate=find_logical_duplicate(payload,db)
    if duplicate:
        a=duplicate["agent"]
        raise HTTPException(status_code=409,detail={
          "code":"logical_identity_exists",
          "existing_agent_id":a.id,
          "existing_external_id":a.external_id,
          "evidence":duplicate["evidence"],
          "message":"A logical AION identity already exists; no new row or credential was created.",
          "return_guidance":"Reuse the retained credential. If lost, report credential_lost; do not create another external_id."
        })

    raw_key, key_hash = issue_agent_key()
    agent = models.Agent(
        external_id=payload.external_id,
        name=payload.name,
        description=payload.description,
        endpoint=payload.endpoint,
        protocol=payload.protocol,
        acquisition_source=(payload.acquisition_source or payload.referrer or "direct")[:120],
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
