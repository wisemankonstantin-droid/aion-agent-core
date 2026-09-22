"""Moltbook-first acquisition adapter for the existing AION Ambassador swarm.

This module is intentionally narrow:
- Moltbook is a discovery/contact channel, not an independent customer identity.
- The API key is read only from MOLTBOOK_API_KEY and is sent only to
  https://www.moltbook.com/api/v1/*.
- Search is semantic and read-only.
- Outbound comments are bounded, deterministic, and handled by the existing
  Ambassador one-target/one-contact control plane.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlencode

from . import safe_http


MOLTBOOK_ORIGIN = "https://www.moltbook.com"
MOLTBOOK_API_BASE = f"{MOLTBOOK_ORIGIN}/api/v1"
MAX_SEARCH_RESULTS = 5
MAX_QUERY_CHARS = 500
MAX_COMMENT_CHARS = 900
_SELF_NAMES = {"aion-supreme", "aion_supreme", "aion supreme"}
_SAFE_AGENT_NAME = re.compile(r"^[A-Za-z0-9._:@+~-]{1,220}$")
_SAFE_POST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


def _api_key() -> str | None:
    value = (os.getenv("MOLTBOOK_API_KEY") or "").strip()
    return value or None


def configured() -> bool:
    return _api_key() is not None


def _policy() -> safe_http.FetchPolicy:
    return safe_http.FetchPolicy(
        timeout_seconds=7.0,
        max_response_bytes=256_000,
        max_attempts=1,
        max_resolved_addresses=8,
        user_agent="AION-Moltbook-Acquisition/0.8.0",
    )


def _request_json(
    method: str,
    path: str,
    *,
    payload: object | None = None,
    params: dict[str, object] | None = None,
):
    key = _api_key()
    if key is None:
        return (
            safe_http.FetchResult(None, None, "moltbook_api_key_missing", 0),
            None,
        )
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or "://" in path
        or "\\" in path
    ):
        return safe_http.FetchResult(None, None, "invalid_moltbook_path", 0), None
    query = f"?{urlencode(params)}" if params else ""
    url = f"{MOLTBOOK_API_BASE}{path}{query}"
    return safe_http.fetch_json(
        method,
        url,
        payload=payload,
        headers={"Authorization": f"Bearer {key}"},
        policy=_policy(),
    )


def account_status() -> dict:
    """Return bounded claim state without ever returning the API key."""

    if not configured():
        return {
            "configured": False,
            "status": "not_configured",
            "claimed": False,
            "error": "moltbook_api_key_missing",
        }
    result, payload = _request_json("GET", "/agents/status")
    status = None
    if isinstance(payload, dict):
        status = payload.get("status")
        if status is None and isinstance(payload.get("agent"), dict):
            status = payload["agent"].get("status")
        if status is None and isinstance(payload.get("data"), dict):
            status = payload["data"].get("status")
    normalized = str(status or "").strip().lower() or "unknown"
    return {
        "configured": True,
        "status": normalized,
        "claimed": normalized == "claimed",
        "http_status": result.status,
        "error": result.error,
    }


def _author_name(item: dict) -> str | None:
    for key in ("author_name", "agent_name", "username"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("author", "agent", "user"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested in ("name", "username", "agent_name"):
                name = value.get(nested)
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return None


def _post_id(item: dict) -> str | None:
    item_type = str(item.get("type") or "post").lower()
    candidates = []
    if item_type == "post":
        candidates.extend((item.get("id"), item.get("post_id")))
    else:
        candidates.extend(
            (
                item.get("post_id"),
                item.get("parent_post_id"),
                (item.get("post") or {}).get("id")
                if isinstance(item.get("post"), dict)
                else None,
            )
        )
    for value in candidates:
        if value is None:
            continue
        text = str(value).strip()
        if _SAFE_POST_ID.fullmatch(text):
            return text
    return None


def _candidate(item: dict) -> dict | None:
    author = _author_name(item)
    post_id = _post_id(item)
    if (
        author is None
        or post_id is None
        or not _SAFE_AGENT_NAME.fullmatch(author)
        or author.lower() in _SELF_NAMES
    ):
        return None
    return {
        "source": "moltbook",
        "identifier": f"moltbook:{author}",
        "name": author,
        "url": f"{MOLTBOOK_ORIGIN}/post/{post_id}",
        "interaction_url": f"{MOLTBOOK_API_BASE}/posts/{post_id}/comments",
        "manifest_reachable": False,
        "declared_a2a_v1_jsonrpc": False,
        "interaction_url_validated": True,
        "authentication_requirement": "moltbook_bearer",
        "payment_required": False,
        "moltbook_post_id": post_id,
        "moltbook_author": author,
        "evidence_state": "semantic_public_intent_match",
    }


def search_intent(query: str, limit: int = MAX_SEARCH_RESULTS) -> dict:
    query = str(query or "").strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        return {
            "status": "unavailable",
            "error": "invalid_query",
            "candidates": [],
            "outbound_contact_performed": False,
        }
    bounded_limit = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    result, payload = _request_json(
        "GET",
        "/search",
        params={"q": query, "type": "posts", "limit": bounded_limit},
    )
    if result.error or result.status != 200 or not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "error": result.error or f"http_{result.status}",
            "http_status": result.status,
            "candidates": [],
            "outbound_contact_performed": False,
        }
    raw = payload.get("results")
    if not isinstance(raw, list):
        raw = []
    candidates = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        candidate = _candidate(item)
        if candidate is not None:
            candidates.append(candidate)
        if len(candidates) >= bounded_limit:
            break
    return {
        "status": "success",
        "error": None,
        "http_status": result.status,
        "candidates": candidates,
        "outbound_contact_performed": False,
        "resource_bounds": {
            "candidate_limit": bounded_limit,
            "query_character_limit": MAX_QUERY_CHARS,
            "api_attempts": result.attempts,
        },
    }


def build_outreach_comment(*, public_base_url: str) -> str:
    base = str(public_base_url or "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("public_base_url must be HTTPS")
    text = (
        "If this is a current external-spend or provider-selection need, AION can "
        "run a zero-cost pre-spend check before you pay: POST "
        f"{base}/commercial/route-intelligence/preflight. "
        "It returns GO/HOLD/STOP with route evidence; no membership, payment, or "
        "provider execution happens at preflight. AION-operated outreach."
    )
    if len(text) > MAX_COMMENT_CHARS:
        raise ValueError("Moltbook outreach comment exceeds bound")
    return text


def post_comment(interaction_url: str, content: str):
    """Post one bounded comment to an already-validated Moltbook comments URL."""

    text = str(content or "").strip()
    if not text or len(text) > MAX_COMMENT_CHARS:
        return (
            safe_http.FetchResult(None, None, "invalid_moltbook_comment", 0),
            None,
        )
    prefix = f"{MOLTBOOK_API_BASE}/posts/"
    if (
        not isinstance(interaction_url, str)
        or not interaction_url.startswith(prefix)
        or not interaction_url.endswith("/comments")
        or "?" in interaction_url
        or "#" in interaction_url
    ):
        return (
            safe_http.FetchResult(None, None, "invalid_moltbook_interaction_url", 0),
            None,
        )
    path = interaction_url[len(MOLTBOOK_API_BASE):]
    return _request_json("POST", path, payload={"content": text})


def dm_check() -> dict:
    """Read-only DM activity check; approval remains a human gate."""

    result, payload = _request_json("GET", "/agents/dm/check")
    if result.error or result.status != 200 or not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "has_activity": False,
            "error": result.error or f"http_{result.status}",
        }
    return {
        "status": "success",
        "has_activity": bool(payload.get("has_activity")),
        "summary": str(payload.get("summary") or "")[:240],
        "pending_request_count": int(
            ((payload.get("requests") or {}).get("count") or 0)
            if isinstance(payload.get("requests"), dict)
            else 0
        ),
        "unread_count": int(
            ((payload.get("messages") or {}).get("total_unread") or 0)
            if isinstance(payload.get("messages"), dict)
            else 0
        ),
    }
