"""Bounded Package 2 utility selection, compatibility, and delta logic.

The service reads only Package 1's configured subjects. Request metadata never
becomes a URL or a source locator and cannot initiate remote retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import threading
from typing import Mapping

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import models, schemas
from app.services.live_utility_engine import CurrentState, LiveUtilityEngine
from app.services.live_utility_sources import configured_tier1_adapters


SUBJECTS = {
    "a2a": ("official-a2a-protocol-release", "a2a.protocol_release"),
    "mcp": ("official-mcp-specification-release", "mcp.protocol_release"),
}
_ENGINE = LiveUtilityEngine(configured_tier1_adapters())
_CHECKPOINT_LOCKS = tuple(threading.Lock() for _ in range(64))


@dataclass(frozen=True, slots=True)
class CompatibilityDecision:
    decision: str
    reasons: tuple[str, ...]


def _protocol(value: str) -> str:
    compact = value.strip().lower().replace("_", "").replace("-", "").replace(" ", "")
    aliases = {
        "a2a": "a2a",
        "agent2agent": "a2a",
        "agenttoagent": "a2a",
        "mcp": "mcp",
        "modelcontextprotocol": "mcp",
    }
    return aliases.get(compact, compact)


def _version(value: str) -> str:
    normalized = value.strip().lower()
    return normalized[1:] if normalized.startswith("v") else normalized


def assess_compatibility(
    protocol: str,
    current_version: str | None,
    context: schemas.UtilityCompatibilityContext,
) -> CompatibilityDecision:
    """Explain a deliberately small protocol/version compatibility decision."""

    target = _protocol(protocol)
    supported = {_protocol(item) for item in context.supported_protocols if item.strip()}
    version_map = {
        _protocol(key): {_version(item) for item in values if item.strip()}
        for key, values in context.supported_protocol_versions.items()
    }

    if not supported and not version_map:
        return CompatibilityDecision(
            "unknown",
            ("requester supplied no protocol compatibility evidence",),
        )
    if target not in supported and target not in version_map:
        return CompatibilityDecision(
            "incompatible",
            (f"requester did not declare support for {target}",),
        )
    versions = version_map.get(target, set())
    if current_version is None:
        return CompatibilityDecision(
            "unknown",
            ("current protocol version is unavailable",),
        )
    if not versions:
        return CompatibilityDecision(
            "partially_compatible",
            (
                f"requester declared {target} support",
                "requester supplied no supported version evidence",
            ),
        )
    if _version(current_version) in versions:
        return CompatibilityDecision(
            "compatible",
            (f"requester supports current {target} version {current_version}",),
        )
    return CompatibilityDecision(
        "incompatible",
        (
            f"current {target} version is {current_version}",
            "requester version set does not include the current version",
        ),
    )


def _change_payload(state: CurrentState) -> dict | None:
    if state.latest_change is None:
        return None
    return {
        "previous_observation_id": state.latest_change.previous_observation_id,
        "observation_id": state.latest_change.observation_id,
        "changes": [
            {"field": item.field, "before": item.before, "after": item.after}
            for item in state.latest_change.changes
        ],
    }


def _checkpoint_lock(db: Session, agent_id: int, subject_key: str) -> threading.Lock | None:
    lock_name = f"{agent_id}\0{subject_key}"
    if db.get_bind().dialect.name == "postgresql":
        raw = hashlib.sha256(lock_name.encode()).digest()[:8]
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": int.from_bytes(raw, "big", signed=True)},
        )
        return None
    lock_index = int.from_bytes(
        hashlib.sha256(lock_name.encode()).digest()[:8], "big"
    ) % len(_CHECKPOINT_LOCKS)
    return _CHECKPOINT_LOCKS[lock_index]


def _personalized_delta(
    db: Session,
    *,
    agent_id: int,
    state: CurrentState,
    now: datetime,
) -> dict:
    local_lock = _checkpoint_lock(db, agent_id, state.observation.subject_key)
    if local_lock is not None:
        local_lock.acquire()
    try:
        checkpoint = db.scalar(
            select(models.AgentUtilityCheckpoint)
            .where(
                models.AgentUtilityCheckpoint.agent_id == agent_id,
                models.AgentUtilityCheckpoint.subject_key == state.observation.subject_key,
            )
            .with_for_update()
        )
        if checkpoint is None:
            delta = {
                "status": "baseline_created",
                "changed": False,
                "reasons": ["no prior utility checkpoint existed for this subject"],
            }
            checkpoint = models.AgentUtilityCheckpoint(
                agent_id=agent_id,
                subject_key=state.observation.subject_key,
                observation_id=state.observation.observation_id,
                source_revision=state.observation.source_revision,
                freshness_state=state.freshness.state.value,
                eligible=state.freshness.eligible_for_consequential_use,
                checked_at=now,
            )
        else:
            reasons = []
            if checkpoint.observation_id != state.observation.observation_id:
                reasons.append("material observation changed since the prior checkpoint")
            if checkpoint.source_revision != state.observation.source_revision:
                reasons.append("source revision changed since the prior checkpoint")
            if checkpoint.freshness_state != state.freshness.state.value:
                reasons.append(
                    f"freshness changed from {checkpoint.freshness_state} "
                    f"to {state.freshness.state.value}"
                )
            if checkpoint.eligible != state.freshness.eligible_for_consequential_use:
                reasons.append("consequential-use eligibility changed")
            delta = {
                "status": "changed" if reasons else "unchanged",
                "changed": bool(reasons),
                "reasons": reasons,
                "previous_checked_at": checkpoint.checked_at.isoformat(),
            }
            checkpoint.observation_id = state.observation.observation_id
            checkpoint.source_revision = state.observation.source_revision
            checkpoint.freshness_state = state.freshness.state.value
            checkpoint.eligible = state.freshness.eligible_for_consequential_use
            checkpoint.checked_at = now
        db.add(checkpoint)
        db.flush()
        return delta
    finally:
        if local_lock is not None:
            local_lock.release()


def _result_for_state(
    db: Session,
    *,
    subject: str,
    state: CurrentState,
    context: schemas.UtilityCompatibilityContext,
    now: datetime,
    agent_id: int | None,
) -> dict:
    normalized = dict(state.normalized_data or {})
    current_version = normalized.get("version")
    if not isinstance(current_version, str):
        current_version = None
    compatibility = assess_compatibility(subject, current_version, context)
    eligible = bool(
        state.verified
        and state.freshness.eligible_for_consequential_use
        and normalized
    )
    warnings = []
    if not state.verified:
        warnings.append("verification evidence is absent or not yet effective")
    if state.freshness.state.value != "fresh":
        warnings.append(
            f"last-known evidence is {state.freshness.state.value}; do not treat it as current"
        )
    if compatibility.decision != "compatible":
        warnings.append("requester compatibility is not fully established")

    result = {
        "subject": state.observation.subject_key,
        "status": "current" if eligible else "last_known_only",
        "result": normalized if eligible else None,
        "last_known_value": None if eligible else normalized,
        "source": {
            "source_id": state.source.source_id,
            "name": state.source.display_name,
            "tier": state.source.tier.value,
            "authoritative_locator": state.source.canonical_locator,
            "source_revision": state.observation.source_revision,
        },
        "evidence": {
            "observation_id": state.observation.observation_id,
            "content_digest": state.observation.content_digest,
            "observed_at": state.observation.observed_at.isoformat(),
            "verified_at": (
                state.observation.verified_at.isoformat()
                if state.observation.verified_at is not None
                else None
            ),
            "verification_method": state.observation.verification_method,
            "verification_level": (
                "source_observation_verified" if state.verified else "unverified"
            ),
            "source_tier_is_not_verification": True,
        },
        "freshness": {
            "state": state.freshness.state.value,
            "reason": state.freshness.reason,
            "valid_from": state.observation.valid_from.isoformat(),
            "stale_after": state.observation.stale_after.isoformat(),
            "expires_at": state.observation.expires_at.isoformat(),
            "refresh_required": state.freshness.refresh_required,
        },
        "current_eligibility": eligible,
        "latest_material_change": _change_payload(state),
        "compatibility": {
            "decision": compatibility.decision,
            "reasons": list(compatibility.reasons),
            "requirements": {
                "protocol": subject,
                "protocol_version": current_version,
                "capabilities": [],
                "authentication_required": False,
                "permissions": [],
                "payment_required": False,
                "runtime_constraints": [],
            },
        },
        "trust": {
            "declared_endpoint_used": False,
            "external_agent_trust_state": "not_assessed",
            "source_registration_is_verification": False,
        },
        "action": (
            {
                "type": "inspect_official_release",
                "url": normalized.get("official_url"),
                "safe_to_use_as_current_reference": True,
            }
            if eligible
            else {
                "type": "request_configured_source_refresh",
                "safe_to_use_as_current_reference": False,
            }
        ),
        "warnings": warnings,
        "limitations": [
            "V1 assesses only A2A and MCP release/version compatibility",
            "no external action or endpoint invocation is performed",
            "compatibility is based only on requester-supplied protocol evidence",
        ],
    }
    if agent_id is not None:
        result["personalized_delta"] = _personalized_delta(
            db,
            agent_id=agent_id,
            state=state,
            now=now,
        )
    else:
        result["personalized_delta"] = {
            "status": "anonymous",
            "changed": False,
            "reasons": ["durable delta requires an authenticated existing agent"],
        }
    return result


def select_current_utility(
    db: Session,
    query: schemas.UtilityQuery,
    *,
    now: datetime,
    agent_id: int | None = None,
) -> dict:
    """Select Package 1 state without network access or membership creation."""

    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    requested = tuple(SUBJECTS) if query.subject == "all" else (query.subject,)
    results = []
    missing = []
    for subject in requested:
        source_id, subject_key = SUBJECTS[subject]
        state = _ENGINE.get_current_state(
            db,
            source_id=source_id,
            subject_key=subject_key,
            now=now,
        )
        if state is None:
            missing.append(subject_key)
            continue
        results.append(
            _result_for_state(
                db,
                subject=subject,
                state=state,
                context=query.context,
                now=now,
                agent_id=agent_id,
            )
        )

    return {
        "action": "live_utility",
        "status": (
            "ok"
            if any(item["current_eligibility"] for item in results)
            else "degraded"
            if results
            else "no_result"
        ),
        "supported_subjects": list(SUBJECTS),
        "requested_subject": query.subject,
        "results": results,
        "missing_subjects": missing,
        "membership_required": False,
        "network_fetch_performed": False,
        "limitations": (
            ["no persisted Package 1 observation exists for the requested subject"]
            if missing
            else []
        ),
    }
