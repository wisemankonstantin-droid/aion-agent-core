"""Narrow remote operator control for the Package 5D Ambassador pilot."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from . import ambassador
from .ambassador import AmbassadorError


MAX_AUTHORIZATION_HEADER_BYTES = 512
MIN_CONTROL_TOKEN_BYTES = 32
MAX_CONTROL_TOKEN_BYTES = 256
_IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_KINDS = {
    "create_campaign",
    "scout_campaign",
    "qualify_target",
    "set_campaign_state",
    "suppress_target",
    "contact_target",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def authorize_operator(authorization: str | None) -> None:
    """Validate only the dedicated control token without retaining it."""

    configured = os.getenv("AION_AMBASSADOR_CONTROL_TOKEN")
    if configured is None:
        raise AmbassadorError(
            503,
            "operator_control_disabled",
            "Ambassador operator control is not configured",
        )
    configured_bytes = configured.encode("utf-8")
    if (
        len(configured_bytes) < MIN_CONTROL_TOKEN_BYTES
        or len(configured_bytes) > MAX_CONTROL_TOKEN_BYTES
        or any(byte < 33 or byte > 126 for byte in configured_bytes)
    ):
        raise AmbassadorError(
            503,
            "operator_control_misconfigured",
            "Ambassador operator control is not safely configured",
        )
    if authorization is None:
        raise AmbassadorError(401, "operator_authorization_required", "Operator authorization is required")
    try:
        header_bytes = authorization.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AmbassadorError(401, "invalid_operator_authorization", "Operator authorization is invalid") from exc
    if len(header_bytes) > MAX_AUTHORIZATION_HEADER_BYTES:
        raise AmbassadorError(401, "invalid_operator_authorization", "Operator authorization is invalid")
    prefix = b"Bearer "
    candidate = header_bytes[len(prefix):] if header_bytes.startswith(prefix) else b""
    if not 1 <= len(candidate) <= MAX_CONTROL_TOKEN_BYTES:
        candidate = b"invalid"
    expected_digest = hashlib.sha256(configured_bytes).digest()
    candidate_digest = hashlib.sha256(candidate).digest()
    if not hmac.compare_digest(candidate_digest, expected_digest):
        raise AmbassadorError(401, "invalid_operator_authorization", "Operator authorization is invalid")


def _key(value: str | None) -> str:
    key = str(value or "").strip()
    if not _IDEMPOTENCY.fullmatch(key):
        raise AmbassadorError(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key must be 1-128 safe ASCII characters",
        )
    return key


def _public_ids(db: Session, action: models.AmbassadorOperatorAction) -> tuple[str | None, str | None]:
    campaign_id = None
    target_id = None
    if action.campaign_id is not None:
        campaign = db.get(models.AmbassadorCampaign, action.campaign_id)
        campaign_id = campaign.campaign_id if campaign is not None else None
    if action.target_id is not None:
        target = db.get(models.AmbassadorTarget, action.target_id)
        target_id = target.target_id if target is not None else None
    return campaign_id, target_id


def _audit_view(db: Session, action: models.AmbassadorOperatorAction) -> dict:
    campaign_id, target_id = _public_ids(db, action)
    return {
        "action_id": action.action_id,
        "operation_kind": action.operation_kind,
        "campaign_id": campaign_id,
        "target_id": target_id,
        "request_digest": action.request_digest,
        "result_class": action.result_class,
        "created_at": action.created_at.isoformat(),
        "completed_at": action.completed_at.isoformat() if action.completed_at else None,
    }


def _replay_result(db: Session, action: models.AmbassadorOperatorAction) -> dict | None:
    campaign_id, target_id = _public_ids(db, action)
    if action.operation_kind == "contact_target" and action.target_id is not None:
        target = db.get(models.AmbassadorTarget, action.target_id)
        contact = db.scalar(
            select(models.AmbassadorContactAttempt).where(
                models.AmbassadorContactAttempt.target_id == action.target_id
            )
        )
        if target is not None and contact is not None:
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
                "raw_distribution_token_returned": False,
                "raw_prepared_message_returned": False,
            }
    if action.operation_kind in {"create_campaign", "scout_campaign", "set_campaign_state"} and campaign_id:
        return ambassador.campaign_status(db, campaign_id)
    if target_id:
        return ambassador.target_status(db, target_id)
    return None


def _find_links(
    db: Session,
    *,
    campaign_id: str | None,
    target_id: str | None,
) -> tuple[int | None, int | None]:
    campaign_pk = None
    target_pk = None
    if campaign_id:
        campaign_pk = db.scalar(
            select(models.AmbassadorCampaign.id).where(
                models.AmbassadorCampaign.campaign_id == campaign_id
            )
        )
    if target_id:
        target = db.scalar(
            select(models.AmbassadorTarget).where(
                models.AmbassadorTarget.target_id == target_id
            )
        )
        if target is not None:
            target_pk = target.id
            campaign_pk = campaign_pk or target.campaign_id
    return campaign_pk, target_pk


def execute_operator_action(
    db: Session,
    *,
    operation_kind: str,
    idempotency_key: str | None,
    request_evidence: dict,
    callback: Callable[[], dict],
    campaign_id: str | None = None,
    target_id: str | None = None,
) -> dict:
    """Execute one idempotent bounded operator mutation with durable audit."""

    if operation_kind not in _KINDS:
        raise AmbassadorError(500, "invalid_operator_operation", "Unsupported operator operation")
    key = _key(idempotency_key)
    request_digest = _digest({"operation_kind": operation_kind, "request": request_evidence})
    campaign_pk, target_pk = _find_links(
        db, campaign_id=campaign_id, target_id=target_id
    )
    existing = db.scalar(
        select(models.AmbassadorOperatorAction).where(
            models.AmbassadorOperatorAction.operation_kind == operation_kind,
            models.AmbassadorOperatorAction.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise AmbassadorError(409, "operator_idempotency_conflict", "Idempotency key was used for a different request")
        if existing.result_class == "claimed":
            raise AmbassadorError(409, "operator_action_uncertain", "Operator action is already claimed; it will not be retried")
        return {
            "operator_action": _audit_view(db, existing),
            "result": _replay_result(db, existing),
            "idempotent_replay": True,
        }

    action = models.AmbassadorOperatorAction(
        action_id=str(uuid.uuid4()),
        operation_kind=operation_kind,
        campaign_id=campaign_pk,
        target_id=target_pk,
        idempotency_key=key,
        request_digest=request_digest,
        result_class="claimed",
        created_at=_now(),
        completed_at=None,
    )
    db.add(action)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(models.AmbassadorOperatorAction).where(
                models.AmbassadorOperatorAction.operation_kind == operation_kind,
                models.AmbassadorOperatorAction.idempotency_key == key,
            )
        )
        if concurrent is None or concurrent.request_digest != request_digest:
            raise AmbassadorError(409, "operator_idempotency_conflict", "Idempotency key was used concurrently")
        raise AmbassadorError(409, "operator_action_uncertain", "Operator action was concurrently claimed; it will not be retried")

    action_pk = action.id

    try:
        result = callback()
    except AmbassadorError:
        db.rollback()
        action = db.get(models.AmbassadorOperatorAction, action_pk)
        action.result_class = "rejected"
        action.completed_at = _now()
        db.commit()
        raise
    except Exception:
        db.rollback()
        action = db.get(models.AmbassadorOperatorAction, action_pk)
        action.result_class = "failed"
        action.completed_at = _now()
        db.commit()
        raise

    result_campaign_id = result.get("campaign_id") if isinstance(result, dict) else None
    result_target_id = result.get("target_id") if isinstance(result, dict) else None
    linked_campaign, linked_target = _find_links(
        db,
        campaign_id=result_campaign_id or campaign_id,
        target_id=result_target_id or target_id,
    )
    action = db.get(models.AmbassadorOperatorAction, action_pk)
    action.campaign_id = linked_campaign
    action.target_id = linked_target
    contact_class = result.get("result_class") if operation_kind == "contact_target" else None
    if contact_class == "ambiguous":
        action.result_class = "ambiguous"
    elif contact_class in {"payment_required", "credentials_required", "rejected"}:
        action.result_class = "rejected"
    else:
        action.result_class = "succeeded"
    action.completed_at = _now()
    db.commit()
    return {
        "operator_action": _audit_view(db, action),
        "result": result,
        "idempotent_replay": False,
    }
