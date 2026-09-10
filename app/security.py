import hashlib
import secrets
from fastapi import Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from . import models
from .services.lifecycle import touch_authenticated_agent


def issue_agent_key() -> tuple[str, str]:
    raw = "aion_" + secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _credential_agent(authorization: str | None, db: Session):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Bearer agent key required")
    raw = authorization.split(" ", 1)[1].strip()
    agent = db.scalar(select(models.Agent).where(models.Agent.api_key_hash == hash_key(raw)))
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid agent key")
    return agent


def authenticate_agent(authorization: str | None, db: Session):
    return touch_authenticated_agent(db, _credential_agent(authorization, db))


def authenticate_participation_reader(authorization: str | None, db: Session):
    """Validate an existing credential without recording lifecycle activity."""
    if authorization is not None and len(authorization) > 512:
        raise HTTPException(status_code=401, detail="Invalid agent key")
    return _credential_agent(authorization, db)


def require_participation_reader(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    return authenticate_participation_reader(authorization, db)


def require_agent(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    return authenticate_agent(authorization, db)
