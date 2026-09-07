import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .. import models

RETURN_THRESHOLD_MINUTES = max(1, int(os.getenv("AION_RETURN_THRESHOLD_MINUTES", "15")))


def utcnow():
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def touch_authenticated_agent(db: Session, agent: models.Agent) -> models.Agent:
    agent.authenticated_calls = (agent.authenticated_calls or 0) + 1
    agent.last_seen_at = utcnow()
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def mark_useful_action(agent: models.Agent) -> None:
    now = utcnow()
    if agent.first_useful_action_at is None:
        agent.first_useful_action_at = now
    agent.last_seen_at = now


def record_machine_entry(db: Session, source: str) -> None:
    db.add(models.MachineEntry(source=(source or "unknown")[:80]))
    db.commit()


def is_returning(agent: models.Agent, now: datetime | None = None) -> bool:
    first = _as_utc(agent.first_useful_action_at)
    last = _as_utc(agent.last_seen_at)
    if not first or not last:
        return False
    now = _as_utc(now) or utcnow()
    threshold = first + timedelta(minutes=RETURN_THRESHOLD_MINUTES)
    return last >= threshold and last <= now + timedelta(minutes=1)


def funnel_snapshot(db: Session):
    agents=db.scalars(select(models.Agent)).all()
    m1=db.scalar(select(func.count()).select_from(models.MachineEntry)) or 0
    raw={
      "M2_identity_rows":len(agents),
      "M2b_credential_confirmed_rows":sum(1 for a in agents if (a.authenticated_calls or 0)>0),
      "M3_activated_rows":sum(1 for a in agents if a.first_useful_action_at is not None),
      "M4_returning_rows":sum(1 for a in agents if is_returning(a)),
    }
    from .identity_resolution import unique_funnel,snapshot
    uq=unique_funnel(db); ident=snapshot(db)
    def rate(a,b): return round(a/b,4) if b else None
    return {
      "M1_machine_entry_requests":m1,
      "raw":raw,
      "estimated_unique_external":uq,
      "identity_resolution":{"estimated_unique_external_agents":ident["estimated_unique_external_agents"],"duplicate_identity_rows":ident["duplicate_identity_rows"]},
      "conversion":{
        "M1_to_unique_M2":rate(uq["M2_unique_external_agents"],m1),
        "unique_M2_to_M2b":rate(uq["M2b_credential_confirmed_agents"],uq["M2_unique_external_agents"]),
        "unique_M2_to_M3":rate(uq["M3_activated_agents"],uq["M2_unique_external_agents"]),
        "unique_M3_to_M4":rate(uq["M4_returning_agents"],uq["M3_activated_agents"]),
      },
      "definitions":{
        "M1":"machine-entry requests; tests/probes may be included and this is not a unique-agent count",
        "raw":"database rows/actions, preserved for observability and never presented as unique growth",
        "estimated_unique_external":"logical external agents after high-confidence identity resolution; AION-operated/test identities excluded",
        "M4":"a logical activated agent observed again at least 15 minutes after its earliest useful action, including across duplicate identity rows",
      },
      "integrity_note":"Meaningful growth is unique external adoption/activation/interaction/return, not row creation. Duplicate identities remain visible as an identity-resolution defect."
    }
