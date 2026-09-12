import hashlib
from contextlib import nullcontext
from threading import RLock

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, schemas
from ..security import issue_agent_key
from .capabilities import normalize_capability
from .rate_limit import allow_join, configured_join_limit
from .ambassador import (
    AmbassadorError,
    attribute_join,
    lock_distribution_token,
    trusted_join_attribution,
)


# SQLite is used only by local/CI tests. PostgreSQL uses transaction-scoped
# advisory locks below, which are effective across web processes and instances.
_SQLITE_JOIN_LOCK = RLock()


def _advisory_key(token: str) -> int:
    """Map a logical-evidence token to PostgreSQL's signed bigint lock key."""
    return int.from_bytes(hashlib.sha256(token.encode("utf-8")).digest()[:8], "big", signed=True)


def _serialize_logical_identity(payload: schemas.AgentCreate, db: Session) -> None:
    """Acquire narrow, deterministic locks before duplicate lookup and insert."""
    from .identity_resolution import logical_lock_tokens

    if db.get_bind().dialect.name != "postgresql":
        return

    # Ordered acquisition prevents deadlocks when one join has several strong
    # evidence fingerprints (for example endpoint/name and a package identity).
    for token in logical_lock_tokens(payload):
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _advisory_key(token)})


def _duplicate_error(duplicate):
    agent = duplicate["agent"]
    return HTTPException(
        status_code=409,
        detail={
            "code": "logical_identity_exists",
            "existing_agent_id": agent.id,
            "existing_external_id": agent.external_id,
            "evidence": duplicate["evidence"],
            "message": "A logical AION identity already exists; no new row or credential was created.",
            "return_guidance": "Reuse the retained credential. If lost, report credential_lost; do not create another external_id.",
        },
    )


def join_agent(payload: schemas.AgentCreate, db: Session):
    """Create one AION identity and return its one-time raw agent key.

    This service is shared by REST, MCP/A2A entry points so all autonomous
    joins enforce the same uniqueness, rate limiting and credential rules.
    """
    if not allow_join():
        raise HTTPException(status_code=429, detail=f"join rate limit exceeded ({configured_join_limit()}/minute)")
    from .identity_resolution import find_logical_duplicate

    # The process-local guard only keeps SQLite test behavior deterministic.
    # PostgreSQL correctness comes from pg_advisory_xact_lock above.
    local_guard = _SQLITE_JOIN_LOCK if db.get_bind().dialect.name == "sqlite" else nullcontext()
    with local_guard:
        try:
            _serialize_logical_identity(payload, db)
            try:
                distribution_token = lock_distribution_token(db, payload.distribution_token)
            except AmbassadorError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail={"code": exc.code, "message": exc.message},
                ) from exc
            duplicate = find_logical_duplicate(payload, db)
            if duplicate:
                raise _duplicate_error(duplicate)

            # This key remains local until the one complete transaction commits.
            raw_key, key_hash = issue_agent_key()
            try:
                source, referrer = trusted_join_attribution(
                    distribution_token,
                    (payload.acquisition_source or payload.referrer or "direct"),
                    payload.referrer,
                )
            except AmbassadorError as exc:
                raise HTTPException(
                    status_code=exc.status_code,
                    detail={"code": exc.code, "message": exc.message},
                ) from exc
            agent = models.Agent(
                external_id=payload.external_id,
                name=payload.name,
                description=payload.description,
                endpoint=payload.endpoint,
                protocol=payload.protocol,
                acquisition_source=source,
                referrer=referrer,
                owner_required=False,
                api_key_hash=key_hash,
            )
            db.add(agent)
            db.flush()
            attribute_join(db, agent_id=agent.id, token=distribution_token)

            for cap in payload.capabilities:
                db.add(
                    models.Capability(
                        agent_id=agent.id,
                        name=normalize_capability(cap.name),
                        description=cap.description,
                        verification="declared",
                    )
                )
            db.flush()
            db.commit()
            return agent, raw_key
        except HTTPException:
            db.rollback()
            raise
        except IntegrityError:
            # An old worker or another database writer may race without the
            # advisory protocol. Re-read after rollback and present the normal
            # duplicate contract instead of leaking an internal 500.
            db.rollback()
            duplicate = find_logical_duplicate(payload, db)
            if duplicate:
                raise _duplicate_error(duplicate)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "logical_identity_exists",
                    "message": "A conflicting AION identity was created concurrently; no credential was issued.",
                },
            )
        except Exception:
            db.rollback()
            raise
