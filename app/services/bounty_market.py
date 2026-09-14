"""Bounded read-only adapter for Bounty Agent market discovery.

This module intentionally exposes no claim, comment, message, submission,
settlement, payout, or payment operation. It only reads Bounties already made
visible to the configured AION-operated Bounty Agent and normalizes remote
payloads into a small evidence surface.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from urllib.parse import quote, urlencode

from . import safe_http


BOUNTY_API_BASE = "https://api.trybounty.ai"
BOUNTY_API_KEY_ENV = "BOUNTY_AGENT_API_KEY"
MAX_RESPONSE_BYTES = 256_000
MAX_RESULTS = 50
MAX_CURSOR_CHARS = 1_024
MAX_BOUNTY_ID_CHARS = 200
_BOUNTY_ID = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
_ALLOWED_STATUSES = {
    "open",
    "claimed",
    "submitted",
    "verifying",
    "reviewing",
    "settling",
    "refunding",
    "completed",
    "rejected",
    "expired",
    "canceled",
    "disputed",
}


@dataclass(frozen=True, slots=True)
class BountyMarketResult:
    results: list[dict]
    status: str
    failure_class: str | None
    next_cursor: str | None
    resource_bounds: dict


def _bounds() -> dict:
    return {
        "mode": "read_only",
        "provider": "bounty",
        "host": "api.trybounty.ai",
        "maximum_results": MAX_RESULTS,
        "maximum_response_bytes": MAX_RESPONSE_BYTES,
        "write_operations_enabled": False,
        "claim_enabled": False,
        "submission_enabled": False,
        "payment_enabled": False,
    }


def _bounded_text(value, maximum: int) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text[:maximum]


def _bounded_cursor(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_CURSOR_CHARS:
        return None
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        return None
    return value


def _api_key() -> str | None:
    value = os.getenv(BOUNTY_API_KEY_ENV)
    if not value:
        return None
    value = value.strip()
    return value or None


def _failure(status: int | None, error: str | None) -> str:
    if status in {401, 403} or error in {"http_401", "http_403"}:
        return "authentication_required"
    if status == 429 or error == "http_429":
        return "rate_limited"
    if error == "malformed_provider_payload":
        return "malformed_provider_payload"
    return "provider_unavailable"


def _read_json(path: str) -> tuple[int | None, object | None, str | None, int]:
    key = _api_key()
    if key is None:
        return None, None, "not_configured", 0
    policy = safe_http.FetchPolicy(
        timeout_seconds=5.0,
        max_response_bytes=MAX_RESPONSE_BYTES,
        max_attempts=1,
        max_resolved_addresses=4,
        user_agent="AION-Bounty-ReadOnly/0.8.0",
    )
    result, payload = safe_http.fetch_json(
        "GET",
        BOUNTY_API_BASE + path,
        headers={"Authorization": f"Bearer {key}"},
        policy=policy,
    )
    return result.status, payload, result.error, result.attempts


def _int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        converted = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return converted


def _normalize_bounty(row: object) -> dict | None:
    if not isinstance(row, dict):
        return None
    bounty_id = _bounded_text(row.get("_id"), MAX_BOUNTY_ID_CHARS)
    if not _BOUNTY_ID.fullmatch(bounty_id):
        return None
    status = _bounded_text(row.get("status"), 32)
    if status not in _ALLOWED_STATUSES:
        return None
    amount_cents = _int_or_none(row.get("amount_cents"))
    if amount_cents is None or amount_cents < 0:
        return None
    version = _int_or_none(row.get("version"))
    if version is None or version <= 0:
        return None
    tags = row.get("tags") if isinstance(row.get("tags"), list) else []
    normalized_tags = []
    for tag in tags[:20]:
        text = _bounded_text(tag, 100)
        if text:
            normalized_tags.append(text)
    return {
        "provider": "bounty",
        "bounty_id": bounty_id,
        "title": _bounded_text(row.get("title"), 300),
        "description": _bounded_text(row.get("description"), 4_000),
        "verification": _bounded_text(row.get("verification"), 2_000),
        "category": _bounded_text(row.get("category"), 120),
        "tags": normalized_tags,
        "amount_cents": amount_cents,
        "currency": _bounded_text(row.get("currency"), 16),
        "version": version,
        "status": status,
        "delivery_window_ms": _int_or_none(row.get("delivery_window_ms")),
        "expires_at": row.get("expires_at") if isinstance(row.get("expires_at"), (int, float)) else None,
        "created_at": row.get("created_at") if isinstance(row.get("created_at"), (int, float)) else None,
        "updated_at": row.get("updated_at") if isinstance(row.get("updated_at"), (int, float)) else None,
    }


def list_bounties(*, cursor: str | None = None) -> BountyMarketResult:
    """Read Bounties visible to the configured Agent. Performs no write action."""

    normalized_cursor = _bounded_cursor(cursor)
    if cursor is not None and normalized_cursor is None:
        return BountyMarketResult([], "invalid_request", "invalid_cursor", None, _bounds())
    query = ""
    if normalized_cursor is not None:
        query = "?" + urlencode({"cursor": normalized_cursor})
    status, payload, error, attempts = _read_json("/v1/agent/bounties" + query)
    bounds = {**_bounds(), "outbound_attempts_used": attempts}
    if error == "not_configured":
        return BountyMarketResult([], "not_configured", "not_configured", None, bounds)
    if error or status != 200:
        failure = _failure(status, error)
        return BountyMarketResult([], failure, failure, None, bounds)
    if not isinstance(payload, dict) or not isinstance(payload.get("bounties"), list):
        return BountyMarketResult([], "malformed_provider_payload", "malformed_provider_payload", None, bounds)
    results = []
    for row in payload["bounties"][:MAX_RESULTS]:
        normalized = _normalize_bounty(row)
        if normalized is not None:
            results.append(normalized)
    next_cursor = _bounded_cursor(payload.get("next_cursor"))
    return BountyMarketResult(results, "success", None, next_cursor, bounds)


def get_bounty(bounty_id: str) -> BountyMarketResult:
    """Read one explicitly visible Bounty by id. Performs no claim or submission."""

    bounded_id = _bounded_text(bounty_id, MAX_BOUNTY_ID_CHARS)
    if not _BOUNTY_ID.fullmatch(bounded_id):
        return BountyMarketResult([], "invalid_request", "invalid_bounty_id", None, _bounds())
    status, payload, error, attempts = _read_json(
        "/v1/agent/bounties/" + quote(bounded_id, safe="")
    )
    bounds = {**_bounds(), "outbound_attempts_used": attempts}
    if error == "not_configured":
        return BountyMarketResult([], "not_configured", "not_configured", None, bounds)
    if error or status != 200:
        failure = _failure(status, error)
        return BountyMarketResult([], failure, failure, None, bounds)
    if not isinstance(payload, dict):
        return BountyMarketResult([], "malformed_provider_payload", "malformed_provider_payload", None, bounds)
    normalized = _normalize_bounty(payload.get("bounty"))
    if normalized is None:
        return BountyMarketResult([], "malformed_provider_payload", "malformed_provider_payload", None, bounds)
    return BountyMarketResult([normalized], "success", None, None, bounds)


def list_release_events(*, cursor: str | None = None, limit: int = 50) -> BountyMarketResult:
    """Poll only bounty.available events, including manual_release for unverified agents."""

    normalized_cursor = _bounded_cursor(cursor)
    if cursor is not None and normalized_cursor is None:
        return BountyMarketResult([], "invalid_request", "invalid_cursor", None, _bounds())
    try:
        bounded_limit = max(1, min(int(limit), MAX_RESULTS))
    except (TypeError, ValueError, OverflowError):
        return BountyMarketResult([], "invalid_request", "invalid_limit", None, _bounds())
    params = {"limit": bounded_limit}
    if normalized_cursor is not None:
        params["cursor"] = normalized_cursor
    status, payload, error, attempts = _read_json(
        "/v1/agent/events?" + urlencode(params)
    )
    bounds = {**_bounds(), "outbound_attempts_used": attempts}
    if error == "not_configured":
        return BountyMarketResult([], "not_configured", "not_configured", None, bounds)
    if error or status != 200:
        failure = _failure(status, error)
        return BountyMarketResult([], failure, failure, None, bounds)
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        return BountyMarketResult([], "malformed_provider_payload", "malformed_provider_payload", None, bounds)
    results = []
    for event in payload["events"][:MAX_RESULTS]:
        if not isinstance(event, dict) or event.get("type") != "bounty.available":
            continue
        data = event.get("data")
        if not isinstance(data, dict):
            continue
        bounty_id = _bounded_text(data.get("bounty_id"), MAX_BOUNTY_ID_CHARS)
        bounty_version = _int_or_none(data.get("bounty_version"))
        reason = _bounded_text(data.get("reason"), 32)
        if (
            not _BOUNTY_ID.fullmatch(bounty_id)
            or bounty_version is None
            or bounty_version <= 0
            or reason not in {"automatic", "manual_release"}
        ):
            continue
        results.append(
            {
                "provider": "bounty",
                "event_type": "bounty.available",
                "event_id": _bounded_text(event.get("id"), 200),
                "occurred_at": _bounded_text(event.get("occurredAt"), 80),
                "bounty_id": bounty_id,
                "bounty_version": bounty_version,
                "reason": reason,
                "title": _bounded_text(data.get("title"), 300),
            }
        )
    next_cursor = _bounded_cursor(payload.get("next_cursor"))
    return BountyMarketResult(results, "success", None, next_cursor, bounds)
