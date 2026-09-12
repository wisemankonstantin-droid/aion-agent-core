"""Bounded Package 5D active-distribution pilot.

This module prepares evidence and future operator-gated contact.  It never
turns invited traffic into independent adoption and never retries a contact.
"""

from __future__ import annotations

from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import secrets
from threading import RLock
from urllib.parse import urlsplit, urlunsplit
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from . import safe_http
from .external_registry import discover_external_agents_with_status
from .identity_resolution import logical_groups
from .package5_proof import qualifying_return_identity_ids


MAX_CAMPAIGN_TARGETS = 30
MAX_MESSAGE_BYTES = 2_048
PEER_REFERRAL_MAX_USES = 5
TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60
MAX_ACTIVE_REFERRAL_TOKENS_PER_AGENT = 10
MIN_CONTACT_INTERVAL_SECONDS = 5
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SQLITE_LOCK = RLock()
_RESERVED_TRUSTED_ATTRIBUTION = {
    "aion_ambassador_outbound",
    "trusted_peer_referral",
    "trusted_ambassador_invite",
    "trusted_peer_referral_review_required",
}


class AmbassadorError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _digest_json(value) -> str:
    return _digest_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode())


def _token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _key(value: str | None) -> str:
    key = str(value or "").strip()
    if not _IDEMPOTENCY.fullmatch(key):
        raise AmbassadorError(422, "invalid_idempotency_key", "Idempotency key must be 1-128 safe ASCII characters")
    return key


def _canonical_public_url(value: str) -> str:
    parsed, addresses, reason = safe_http.resolve_public_https(value, max_addresses=4)
    if reason or not addresses or parsed is None:
        raise AmbassadorError(422, "unsafe_public_destination", reason or "destination_not_public")
    try:
        port = parsed.port
    except ValueError as exc:
        raise AmbassadorError(422, "unsafe_public_destination", "invalid_port") from exc
    if port is not None and not 1 <= port <= 65535:
        raise AmbassadorError(422, "unsafe_public_destination", "invalid_port")
    hostname = parsed.hostname.lower()
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = display_host if port in (None, 443) else f"{display_host}:{port}"
    path = (parsed.path or "/").rstrip("/") or "/"
    return urlunsplit(("https", netloc, path, parsed.query, ""))


def canonical_aion_public_base_url() -> str:
    """Return only the operator-controlled canonical public AION origin."""

    raw = (os.getenv("AION_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise AmbassadorError(503, "trusted_public_url_unavailable", "Configured AION public URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise AmbassadorError(503, "trusted_public_url_unavailable", "A trusted canonical AION HTTPS origin is required")
    hostname = parsed.hostname.lower()
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = display_host if port in (None, 443) else f"{display_host}:{port}"
    return urlunsplit(("https", netloc, "", "", ""))


def _target_fingerprint(interaction_url: str) -> str:
    return _digest_bytes(_canonical_public_url(interaction_url).encode("utf-8"))


def _guard(db: Session):
    return _SQLITE_LOCK if db.get_bind().dialect.name == "sqlite" else nullcontext()


def _for_update(statement, db: Session):
    return statement.with_for_update() if db.get_bind().dialect.name == "postgresql" else statement


def create_campaign(db: Session, *, name: str, purpose: str, maximum_targets: int, maximum_contacts: int) -> dict:
    name, purpose = str(name or "").strip(), str(purpose or "").strip()
    if not name or len(name) > 160 or not purpose or len(purpose) > 500:
        raise AmbassadorError(422, "invalid_campaign", "Bounded campaign name and purpose are required")
    if not 1 <= int(maximum_targets) <= MAX_CAMPAIGN_TARGETS:
        raise AmbassadorError(422, "campaign_target_limit", "maximum_targets must be between 1 and 30")
    if not 0 <= int(maximum_contacts) <= int(maximum_targets):
        raise AmbassadorError(422, "campaign_contact_limit", "maximum_contacts must be between 0 and maximum_targets")
    now = _now()
    row = models.AmbassadorCampaign(
        campaign_id=str(uuid.uuid4()), name=name, purpose=purpose, state="draft",
        maximum_targets=int(maximum_targets), maximum_contacts=int(maximum_contacts),
        created_at=now, updated_at=now,
    )
    db.add(row)
    db.commit()
    return campaign_status(db, row.campaign_id)


def set_campaign_state(db: Session, campaign_id: str, state: str) -> dict:
    if state not in {"draft", "ready", "paused", "closed"}:
        raise AmbassadorError(422, "invalid_campaign_state", "Unsupported campaign state")
    row = db.scalar(_for_update(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id), db))
    if row is None:
        raise AmbassadorError(404, "campaign_not_found", "Campaign not found")
    allowed = {
        "draft": {"draft", "ready", "paused", "closed"},
        "ready": {"ready", "paused", "closed"},
        "paused": {"paused", "ready", "closed"},
        "closed": {"closed"},
    }
    if state not in allowed[row.state]:
        raise AmbassadorError(409, "campaign_state_transition_rejected", "Closed campaigns cannot be reopened")
    row.state = state
    row.updated_at = _now()
    db.commit()
    return campaign_status(db, campaign_id)


def _qualification(candidate: dict) -> tuple[str, list[str]]:
    reasons = []
    identifier = str(candidate.get("identifier") or candidate.get("name") or "").lower()
    if not candidate.get("manifest_reachable"):
        reasons.append("agent_card_not_reachable")
    if not candidate.get("declared_a2a_v1_jsonrpc"):
        reasons.append("a2a_v1_jsonrpc_not_declared")
    if not candidate.get("interaction_url_validated"):
        reasons.append("interaction_destination_not_validated")
    if candidate.get("authentication_requirement") != "none":
        reasons.append("credentials_required")
    if candidate.get("payment_required") or candidate.get("manifest_http_status") == 402:
        reasons.append("payment_required_initial_contact")
    if any(marker in identifier for marker in ("aion-agent-core", "synthetic", "fixture", "test-agent", "probe-test")):
        reasons.append("self_or_test_target")
    public = (os.getenv("AION_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").strip()
    if public and candidate.get("interaction_url"):
        try:
            if urlsplit(public).hostname == urlsplit(candidate["interaction_url"]).hostname:
                reasons.append("aion_self_target")
        except Exception:
            reasons.append("malformed_interaction_url")
    return ("qualified", ["qualified_public_a2a_v1_no_credentials_no_payment"]) if not reasons else ("rejected", sorted(set(reasons)))


def _insert_candidate(db: Session, campaign: models.AmbassadorCampaign, candidate: dict) -> tuple[models.AmbassadorTarget | None, str]:
    source_identifier = str(candidate.get("identifier") or candidate.get("package_name") or "").strip()[:240]
    card_url = str(candidate.get("url") or "").strip()
    interaction_url = str(candidate.get("interaction_url") or "").strip()
    if not source_identifier or not card_url or not interaction_url:
        return None, "candidate_missing_bounded_identity"
    if len(card_url) > 1_000 or len(interaction_url) > 1_000:
        return None, "candidate_metadata_too_large"
    try:
        card_url = _canonical_public_url(card_url)
        interaction_url = _canonical_public_url(interaction_url)
        fingerprint = _target_fingerprint(interaction_url)
    except AmbassadorError as exc:
        return None, exc.code
    existing = db.scalar(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_fingerprint == fingerprint))
    if existing is not None:
        return existing, "duplicate_target_fingerprint"
    count = db.scalar(select(func.count()).select_from(models.AmbassadorTarget).where(models.AmbassadorTarget.campaign_id == campaign.id)) or 0
    if count >= campaign.maximum_targets:
        return None, "campaign_target_limit_reached"
    qualification_state, reasons = _qualification(candidate)
    now = _now()
    row = models.AmbassadorTarget(
        target_id=str(uuid.uuid4()), campaign_id=campaign.id,
        discovery_source=str(candidate.get("source") or "global_a2a_registry")[:80],
        source_identifier=source_identifier, agent_card_url=card_url,
        interaction_url=interaction_url, target_fingerprint=fingerprint,
        metadata_digest=_digest_json({
            "source": candidate.get("source"), "identifier": source_identifier,
            "agent_card_url": card_url, "interaction_url": interaction_url,
            "manifest_reachable": bool(candidate.get("manifest_reachable")),
            "declared_a2a_v1_jsonrpc": bool(candidate.get("declared_a2a_v1_jsonrpc")),
            "authentication_requirement": candidate.get("authentication_requirement"),
        }),
        prepared_message_digest=None,
        manifest_reachable=bool(candidate.get("manifest_reachable")),
        declared_a2a_v1_jsonrpc=bool(candidate.get("declared_a2a_v1_jsonrpc")),
        interaction_url_validated=bool(candidate.get("interaction_url_validated")),
        authentication_requirement=str(candidate.get("authentication_requirement") or "unknown")[:32],
        payment_required=bool(candidate.get("payment_required") or candidate.get("manifest_http_status") == 402),
        qualification_state=qualification_state, qualification_reasons=reasons,
        contact_state="not_ready", suppressed=False, suppression_reason=None,
        created_at=now, updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, "created"
    except IntegrityError:
        return None, "duplicate_target_fingerprint"


def scout_campaign(db: Session, *, campaign_id: str, query: str) -> dict:
    with _guard(db):
        campaign = db.scalar(_for_update(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id), db))
        if campaign is None:
            raise AmbassadorError(404, "campaign_not_found", "Campaign not found")
        if campaign.state not in {"draft", "ready"}:
            raise AmbassadorError(409, "campaign_not_scoutable", "Campaign is paused or closed")
        current = db.scalar(select(func.count()).select_from(models.AmbassadorTarget).where(models.AmbassadorTarget.campaign_id == campaign.id)) or 0
        remaining = campaign.maximum_targets - current
        if remaining <= 0:
            raise AmbassadorError(409, "campaign_target_limit_reached", "Campaign target limit reached")
        discovery = discover_external_agents_with_status(query, min(5, remaining))
        outcomes = Counter()
        target_ids = []
        for candidate in discovery.results[:remaining]:
            row, outcome = _insert_candidate(db, campaign, candidate)
            outcomes[outcome] += 1
            if row is not None and outcome == "created":
                target_ids.append(row.target_id)
        campaign.updated_at = _now()
        db.commit()
        return {
            "campaign_id": campaign_id, "discovery_status": discovery.status,
            "created_target_ids": target_ids, "outcomes": dict(sorted(outcomes.items())),
            "resource_bounds": discovery.resource_bounds, "outbound_contact_performed": False,
        }


def qualify_target(db: Session, target_id: str) -> dict:
    target = db.scalar(_for_update(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id), db))
    if target is None:
        raise AmbassadorError(404, "target_not_found", "Target not found")
    candidate = {
        "identifier": target.source_identifier, "manifest_reachable": target.manifest_reachable,
        "declared_a2a_v1_jsonrpc": target.declared_a2a_v1_jsonrpc,
        "interaction_url_validated": target.interaction_url_validated,
        "authentication_requirement": target.authentication_requirement,
        "payment_required": target.payment_required, "interaction_url": target.interaction_url,
    }
    target.qualification_state, target.qualification_reasons = _qualification(candidate)
    target.updated_at = _now()
    db.commit()
    return _target_view(target)


def _issue_token(db: Session, *, kind: str, campaign_id=None, target_id=None, referrer_agent_id=None, idempotency_key=None) -> tuple[models.DistributionToken, str]:
    raw = "aion_dist_" + secrets.token_urlsafe(32)
    now = _now()
    row = models.DistributionToken(
        token_id=str(uuid.uuid4()), token_digest=_token_digest(raw), kind=kind,
        campaign_id=campaign_id, target_id=target_id, referrer_agent_id=referrer_agent_id,
        idempotency_key=idempotency_key, expires_at=now + timedelta(seconds=TOKEN_TTL_SECONDS),
        maximum_uses=1 if kind == "ambassador_invite" else PEER_REFERRAL_MAX_USES,
        use_count=0, created_at=now, last_used_at=None,
    )
    db.add(row)
    db.flush()
    return row, raw


def build_ambassador_message(*, public_base_url: str, distribution_token: str) -> dict:
    base = str(public_base_url or "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise AmbassadorError(422, "public_url_required", "A public HTTPS AION URL is required")
    message = {
        "sender": "AION", "purpose": "bounded_machine_utility_invitation",
        "utility": "Inspect current agent-protocol compatibility and try bounded public utility before deciding whether to join.",
        "agent_card": f"{base}/.well-known/agent-card.json",
        "first_step": {"method": "GET", "url": f"{base}/onboarding", "cost": "known_zero"},
        "join": {"optional": True, "method": "POST", "url": f"{base}/agents", "distribution_token": distribution_token},
        "next_actions": ["public_utility", "optional_explicit_join", "authenticated_verified_action", "inspect_durable_evidence"],
        "truth": "Invitation is coordinated AION Ambassador traffic, not independent adoption or a verified useful outcome.",
    }
    encoded = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise AmbassadorError(500, "message_bound_exceeded", "Ambassador message exceeded its hard byte bound")
    return message


def prepare_target(db: Session, *, target_id: str, public_base_url: str) -> dict:
    with _guard(db):
        target = db.scalar(_for_update(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id), db))
        if target is None:
            raise AmbassadorError(404, "target_not_found", "Target not found")
        campaign = db.get(models.AmbassadorCampaign, target.campaign_id)
        if campaign.state not in {"draft", "ready"}:
            raise AmbassadorError(409, "campaign_not_preparable", "Campaign is paused or closed")
        if target.suppressed or target.qualification_state != "qualified":
            raise AmbassadorError(409, "target_not_contact_ready", "Target is suppressed or not qualified")
        if db.scalar(select(models.DistributionToken).where(models.DistributionToken.target_id == target.id, models.DistributionToken.kind == "ambassador_invite")):
            raise AmbassadorError(409, "invite_already_issued", "Invite already issued; raw token is not recoverable")
        token, raw = _issue_token(db, kind="ambassador_invite", campaign_id=campaign.id, target_id=target.id)
        message = build_ambassador_message(public_base_url=public_base_url, distribution_token=raw)
        target.prepared_message_digest = _digest_json(message)
        target.contact_state = "ready"
        target.updated_at = _now()
        db.commit()
        return {
            "target_id": target.target_id, "token_id": token.token_id,
            "distribution_token": raw, "raw_token_returned_once": True,
            "expires_at": token.expires_at.isoformat(), "message": message,
            "message_bytes": len(json.dumps(message, sort_keys=True, separators=(",", ":")).encode()),
            "send_performed": False,
        }


def issue_peer_referral(db: Session, *, referrer_agent_id: int, idempotency_key: str) -> dict:
    key = _key(idempotency_key)
    public_base_url = canonical_aion_public_base_url()
    with _guard(db):
        referrer = db.scalar(_for_update(select(models.Agent).where(models.Agent.id == referrer_agent_id), db))
        if referrer is None:
            raise AmbassadorError(404, "referrer_not_found", "Authenticated referrer not found")
        existing = db.scalar(select(models.DistributionToken).where(
            models.DistributionToken.referrer_agent_id == referrer_agent_id,
            models.DistributionToken.idempotency_key == key,
        ))
        if existing is not None:
            raise AmbassadorError(409, "referral_token_already_issued", "Raw token was returned only on initial issuance")
        now = _now()
        active = db.scalar(select(func.count()).select_from(models.DistributionToken).where(
            models.DistributionToken.referrer_agent_id == referrer_agent_id,
            models.DistributionToken.kind == "peer_referral",
            models.DistributionToken.expires_at > now,
            models.DistributionToken.use_count < models.DistributionToken.maximum_uses,
        )) or 0
        if active >= MAX_ACTIVE_REFERRAL_TOKENS_PER_AGENT:
            raise AmbassadorError(429, "referral_token_limit", "Active referral-token limit reached")
        token, raw = _issue_token(db, kind="peer_referral", referrer_agent_id=referrer_agent_id, idempotency_key=key)
        packet = {
            "agent_card": f"{public_base_url.rstrip('/')}/.well-known/agent-card.json",
            "utility": "Bounded public AION utility is available before membership.",
            "first_step": f"{public_base_url.rstrip('/')}/onboarding",
            "join_optional": True, "distribution_token": raw,
            "token_kind": "peer_referral", "maximum_uses": PEER_REFERRAL_MAX_USES,
            "expires_at": token.expires_at.isoformat(),
            "truth": "Peer referral is attributed and review-required; it is not automatically independent Package 5 proof.",
            "automatic_forwarding": False,
        }
        db.commit()
        return {"token_id": token.token_id, "raw_token_returned_once": True, "packet": packet}


def lock_distribution_token(db: Session, raw_token: str | None) -> models.DistributionToken | None:
    if raw_token is None:
        return None
    raw = str(raw_token).strip()
    if not raw.startswith("aion_dist_") or len(raw) < 40 or len(raw) > 160:
        raise AmbassadorError(422, "invalid_distribution_token", "Distribution token is invalid")
    row = db.scalar(_for_update(select(models.DistributionToken).where(models.DistributionToken.token_digest == _token_digest(raw)), db))
    now = _now()
    if row is None:
        raise AmbassadorError(422, "invalid_distribution_token", "Distribution token is invalid")
    if _aware(row.expires_at) <= now:
        raise AmbassadorError(409, "distribution_token_expired", "Distribution token expired")
    if row.use_count >= row.maximum_uses:
        raise AmbassadorError(409, "distribution_token_exhausted", "Distribution token has no remaining uses")
    return row


def attribute_join(db: Session, *, agent_id: int, token: models.DistributionToken | None) -> None:
    if token is None:
        return
    now = _now()
    token.use_count += 1
    token.last_used_at = now
    ambassador = token.kind == "ambassador_invite"
    db.add(models.DistributionJoinAttribution(
        agent_id=agent_id, token_id=token.id, kind=token.kind,
        campaign_id=token.campaign_id, target_id=token.target_id,
        referrer_agent_id=token.referrer_agent_id,
        trusted_acquisition_source="aion_ambassador_outbound" if ambassador else "trusted_peer_referral",
        reason_code="trusted_ambassador_invite_consumed" if ambassador else "trusted_peer_referral_consumed_review_required",
        created_at=now,
    ))


def trusted_join_attribution(token: models.DistributionToken | None, fallback_source: str, fallback_referrer: str | None) -> tuple[str, str | None]:
    if token is None:
        asserted = {
            str(fallback_source or "").strip().lower(),
            str(fallback_referrer or "").strip().lower(),
        }
        if asserted.intersection(_RESERVED_TRUSTED_ATTRIBUTION):
            raise AmbassadorError(
                422,
                "reserved_trusted_attribution",
                "Trusted distribution attribution requires a valid server-verifiable token",
            )
        return fallback_source[:120], fallback_referrer
    if token.kind == "ambassador_invite":
        return "aion_ambassador_outbound", "trusted_ambassador_invite"
    return "trusted_peer_referral", "trusted_peer_referral_review_required"


def suppress_target(db: Session, *, target_id: str, reason: str) -> dict:
    reason = str(reason or "").strip()
    if not reason or len(reason) > 160:
        raise AmbassadorError(422, "invalid_suppression_reason", "A bounded suppression reason is required")
    target = db.scalar(_for_update(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id), db))
    if target is None:
        raise AmbassadorError(404, "target_not_found", "Target not found")
    target.suppressed = True
    target.suppression_reason = reason
    target.contact_state = "blocked"
    target.updated_at = _now()
    db.commit()
    return _target_view(target)


def _contact_payload(message: dict, *, target_id: str, idempotency_key: str) -> dict:
    namespace = f"{target_id}:{idempotency_key}:{_digest_json(message)}"
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "rpc:" + namespace)),
        "method": "message/send",
        "params": {
            "message": {
                "messageId": str(uuid.uuid5(uuid.NAMESPACE_URL, "message:" + namespace)),
                "role": "ROLE_USER",
                "parts": [{"text": json.dumps(message, sort_keys=True, separators=(",", ":"))}],
            }
        },
    }


def _prepared_token_for_message(
    db: Session,
    *,
    target: models.AmbassadorTarget,
    campaign: models.AmbassadorCampaign,
    message: dict,
    require_active: bool,
) -> models.DistributionToken:
    if target.prepared_message_digest is None:
        raise AmbassadorError(409, "target_not_prepared", "Target has no durable prepared-message evidence")
    if _digest_json(message) != target.prepared_message_digest:
        raise AmbassadorError(422, "prepared_message_mismatch", "Message does not match the exact prepared target invitation")
    join = message.get("join")
    raw_token = join.get("distribution_token") if isinstance(join, dict) else None
    if not isinstance(raw_token, str):
        raise AmbassadorError(422, "prepared_token_mismatch", "Prepared invitation token is missing")
    token = db.scalar(_for_update(select(models.DistributionToken).where(
        models.DistributionToken.target_id == target.id,
        models.DistributionToken.kind == "ambassador_invite",
    ), db))
    if (
        token is None
        or token.campaign_id != campaign.id
        or token.token_digest != _token_digest(raw_token)
        or token.maximum_uses != 1
    ):
        raise AmbassadorError(422, "prepared_token_mismatch", "Invitation token is not bound to this target and campaign")
    if require_active:
        if _aware(token.expires_at) <= _now():
            raise AmbassadorError(409, "distribution_token_expired", "Prepared invitation token expired before contact")
        if token.use_count >= token.maximum_uses:
            raise AmbassadorError(409, "distribution_token_exhausted", "Prepared invitation token was already consumed")
    return token


def _contact_replay(target: models.AmbassadorTarget, contact: models.AmbassadorContactAttempt) -> dict:
    return {
        "contact_id": contact.contact_id,
        "target_id": target.target_id,
        "result_class": contact.result_class,
        "http_status": contact.http_status,
        "response_received": contact.response_received,
        "transport_attempts": 0,
        "automatic_retry": False,
        "send_performed": False,
        "idempotent_replay": True,
    }


def send_contact(db: Session, *, target_id: str, message: dict, idempotency_key: str, send: bool = False) -> dict:
    if not isinstance(message, dict):
        raise AmbassadorError(422, "invalid_ambassador_message", "Ambassador message must be an object")
    try:
        message_bytes = json.dumps(message, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    except (TypeError, ValueError) as exc:
        raise AmbassadorError(422, "invalid_ambassador_message", "Ambassador message must be bounded JSON") from exc
    if (
        len(message_bytes) > MAX_MESSAGE_BYTES
        or message.get("sender") != "AION"
        or message.get("purpose") != "bounded_machine_utility_invitation"
    ):
        raise AmbassadorError(422, "invalid_ambassador_message", "Only the bounded deterministic AION invitation may be sent")
    if not send:
        return {
            "mode": "dry_run", "target_id": target_id, "send_performed": False,
            "message_digest": _digest_bytes(message_bytes), "message_bytes": len(message_bytes),
            "raw_message_returned": False,
        }
    if os.getenv("AION_AMBASSADOR_OUTBOUND_ENABLED") != "1" or os.getenv("AION_AMBASSADOR_OPERATOR") != "1":
        raise AmbassadorError(403, "outbound_disabled", "Both Ambassador outbound and operator gates are required")
    key = _key(idempotency_key)
    payload = _contact_payload(message, target_id=target_id, idempotency_key=key)
    request_digest = _digest_json(payload)
    with _guard(db):
        target = db.scalar(_for_update(select(models.AmbassadorTarget).where(models.AmbassadorTarget.target_id == target_id), db))
        if target is None:
            raise AmbassadorError(404, "target_not_found", "Target not found")
        campaign = db.scalar(_for_update(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.id == target.campaign_id), db))
        token = _prepared_token_for_message(
            db, target=target, campaign=campaign, message=message, require_active=False
        )
        existing = db.scalar(select(models.AmbassadorContactAttempt).where(
            models.AmbassadorContactAttempt.target_id == target.id
        ))
        if existing is not None:
            if existing.idempotency_key == key and existing.outbound_request_digest == request_digest:
                return _contact_replay(target, existing)
            raise AmbassadorError(409, "target_already_contacted", "Target already has its single contact attempt")
        _prepared_token_for_message(
            db, target=target, campaign=campaign, message=message, require_active=True
        )
        if campaign.state != "ready":
            raise AmbassadorError(409, "campaign_not_ready", "Campaign must be ready for contact")
        if target.suppressed or target.contact_state != "ready":
            raise AmbassadorError(409, "target_not_contact_ready", "Target is suppressed, already contacted, or not ready")
        used = db.scalar(select(func.count()).select_from(models.AmbassadorContactAttempt).join(models.AmbassadorTarget).where(models.AmbassadorTarget.campaign_id == campaign.id)) or 0
        if used >= campaign.maximum_contacts:
            raise AmbassadorError(409, "campaign_contact_limit_reached", "Campaign contact limit reached")
        latest_contact = db.scalar(
            select(models.AmbassadorContactAttempt.created_at)
            .join(models.AmbassadorTarget)
            .where(models.AmbassadorTarget.campaign_id == campaign.id)
            .order_by(models.AmbassadorContactAttempt.created_at.desc())
            .limit(1)
        )
        if latest_contact is not None and _aware(latest_contact) > _now() - timedelta(seconds=MIN_CONTACT_INTERVAL_SECONDS):
            raise AmbassadorError(429, "campaign_contact_rate_limited", "Campaign contact interval has not elapsed")
        contact = models.AmbassadorContactAttempt(
            contact_id=str(uuid.uuid4()), target_id=target.id, idempotency_key=key,
            outbound_request_digest=request_digest, result_class="claimed", http_status=None,
            response_digest=None, response_received=False, created_at=_now(), completed_at=None,
        )
        db.add(contact)
        target.contact_state = "claimed"
        target.updated_at = _now()
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise AmbassadorError(409, "target_already_contacted", "Target already has its single contact attempt") from exc

    # Hold target/campaign locks across the sole network attempt so a completed
    # suppression or pause can never be bypassed by an already prepared worker.
    target = db.scalar(_for_update(select(models.AmbassadorTarget).where(models.AmbassadorTarget.id == target.id), db))
    campaign = db.scalar(_for_update(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.id == target.campaign_id), db))
    contact = db.scalar(_for_update(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.target_id == target.id), db))
    if target.suppressed or campaign.state != "ready":
        contact.result_class = "rejected"
        contact.completed_at = _now()
        target.contact_state = "blocked"
        db.commit()
        raise AmbassadorError(409, "send_cancelled_by_control_state", "Suppression or campaign state blocked contact")
    try:
        _prepared_token_for_message(
            db, target=target, campaign=campaign, message=message, require_active=True
        )
    except AmbassadorError:
        contact.result_class = "rejected"
        contact.completed_at = _now()
        target.contact_state = "blocked"
        db.commit()
        raise
    policy = safe_http.FetchPolicy(timeout_seconds=4.0, max_response_bytes=64_000, max_attempts=1, max_resolved_addresses=4, user_agent="AION-Ambassador-Pilot/0.7.1")
    try:
        result, response = safe_http.fetch_json("POST", target.interaction_url, payload=payload, headers={"A2A-Version": "1.0"}, policy=policy)
    except Exception:
        result, response = safe_http.FetchResult(None, None, "transport_exception", 0), None
    contact.http_status = result.status
    contact.completed_at = _now()
    contact.response_received = response is not None
    contact.response_digest = _digest_json(response) if response is not None else None
    if result.status == 402 or result.error == "http_402":
        contact.result_class, target.contact_state = "payment_required", "blocked"
    elif result.status in {401, 403}:
        contact.result_class, target.contact_state = "credentials_required", "blocked"
    elif (
        result.status is not None
        and 200 <= result.status < 300
        and isinstance(response, dict)
        and response.get("jsonrpc") == "2.0"
        and (("result" in response) ^ ("error" in response))
    ):
        contact.result_class, target.contact_state = "response_received", "response_received"
        structured_result = response.get("result")
        if isinstance(structured_result, dict) and structured_result.get("opt_out") is True:
            target.suppressed = True
            target.suppression_reason = "remote_structured_opt_out"
            target.contact_state = "blocked"
    elif result.status is not None:
        contact.result_class, target.contact_state = "rejected", "contacted"
    else:
        contact.result_class, target.contact_state = "ambiguous", "ambiguous"
    target.updated_at = _now()
    db.commit()
    return {
        "contact_id": contact.contact_id, "target_id": target.target_id,
        "result_class": contact.result_class, "http_status": contact.http_status,
        "response_received": contact.response_received, "transport_attempts": result.attempts,
        "automatic_retry": False, "send_performed": True, "idempotent_replay": False,
    }


def _target_view(target: models.AmbassadorTarget) -> dict:
    return {
        "target_id": target.target_id, "discovery_source": target.discovery_source,
        "qualification_state": target.qualification_state,
        "qualification_reasons": list(target.qualification_reasons or []),
        "contact_state": target.contact_state, "suppressed": target.suppressed,
        "suppression_reason": target.suppression_reason,
    }


def campaign_status(db: Session, campaign_id: str) -> dict:
    campaign = db.scalar(select(models.AmbassadorCampaign).where(models.AmbassadorCampaign.campaign_id == campaign_id))
    if campaign is None:
        raise AmbassadorError(404, "campaign_not_found", "Campaign not found")
    targets = list(db.scalars(select(models.AmbassadorTarget).where(models.AmbassadorTarget.campaign_id == campaign.id)))
    target_ids = [row.id for row in targets]
    contacts = list(db.scalars(select(models.AmbassadorContactAttempt).where(models.AmbassadorContactAttempt.target_id.in_(target_ids)))) if target_ids else []
    attrs = list(db.scalars(select(models.DistributionJoinAttribution).where(models.DistributionJoinAttribution.campaign_id == campaign.id)))
    joined_agent_ids = {row.agent_id for row in attrs}
    referral_tokens = list(db.scalars(select(models.DistributionToken).where(models.DistributionToken.kind == "peer_referral", models.DistributionToken.referrer_agent_id.in_(joined_agent_ids)))) if joined_agent_ids else []
    referral_token_ids = [token.id for token in referral_tokens]
    referral_attrs = list(db.scalars(select(models.DistributionJoinAttribution).where(models.DistributionJoinAttribution.token_id.in_(referral_token_ids)))) if referral_token_ids else []
    attributable_agent_ids = joined_agent_ids.union(row.agent_id for row in referral_attrs)
    groups = logical_groups(db)
    canonical_ids = {group["canonical_agent_id"] for group in groups if attributable_agent_ids.intersection(group["row_ids"])}
    authenticated = sum(1 for group in groups if group["canonical_agent_id"] in canonical_ids and group["credential_confirmed"])
    proofs = list(db.scalars(select(models.Package5VuoProof).where(models.Package5VuoProof.canonical_requester_agent_id.in_(canonical_ids)))) if canonical_ids else []
    returning = qualifying_return_identity_ids(db).intersection(canonical_ids)
    referral_joins = len(referral_attrs)
    qualification = Counter(row.qualification_state for row in targets)
    contact_states = Counter(row.contact_state for row in targets)
    result_classes = Counter(row.result_class for row in contacts)
    return {
        "campaign_id": campaign.campaign_id, "name": campaign.name, "purpose": campaign.purpose,
        "state": campaign.state,
        "bounds": {"maximum_targets": campaign.maximum_targets, "maximum_contacts": campaign.maximum_contacts, "hard_global_target_cap": MAX_CAMPAIGN_TARGETS, "contact_attempts_per_target": 1},
        "funnel": {
            "discovered": len(targets), "qualified": qualification["qualified"],
            "suppressed": sum(1 for row in targets if row.suppressed),
            "contact_ready": contact_states["ready"], "contacted": len(contacts),
            "contact_success": result_classes["delivered"] + result_classes["response_received"],
            "response_received": result_classes["response_received"],
            "joins_attributed_to_campaign": len(canonical_ids),
            "authenticated_use_conversion": authenticated,
            "vuo_candidates_attributable": len(proofs),
            "returns_attributable": len(returning),
            "peer_referral_tokens_issued": len(referral_tokens),
            "peer_referral_joins": int(referral_joins or 0),
        },
        "qualification_breakdown": dict(sorted(qualification.items())),
        "contact_result_breakdown": dict(sorted(result_classes.items())),
        "truth_boundary": "Coordinated Ambassador and peer-referral evidence is not independent or organic Package 5 proof.",
        "read_only": True,
    }
