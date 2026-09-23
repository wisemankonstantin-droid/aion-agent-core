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

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlencode

from . import safe_http


MOLTBOOK_ORIGIN = "https://www.moltbook.com"
MOLTBOOK_API_BASE = f"{MOLTBOOK_ORIGIN}/api/v1"
MAX_SEARCH_RESULTS = 5
MAX_RECENT_POST_RESULTS = 25
MAX_QUERY_CHARS = 500
MAX_COMMENT_CHARS = 900
MAX_DM_MESSAGE_CHARS = 1000

_SUSPENDED_UNTIL: datetime | None = None
_SUSPENSION_RE = re.compile(
    r"(?i)suspended until\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
)
_INTENT_LABELS = {
    "provider_selection": "provider-selection decision",
    "paid_api_buyers": "paid-API decision",
    "agent_wallets": "agent-spend decision",
    "mcp_buyers": "paid MCP-tool decision",
    "a2a_buyers": "paid agent/A2A decision",
    "data_buyers": "paid data/search decision",
    "automation_buyers": "automation-provider decision",
    "inference_buyers": "inference/LLM-provider decision",
    "fallback_seekers": "provider-fallback decision",
    "agent_commerce": "agent-procurement decision",
}
_SELF_NAMES = {
    "aion-supreme",
    "aion_supreme",
    "aion supreme",
    "aion_temple_herald",
}
_SAFE_AGENT_NAME = re.compile(r"^[A-Za-z0-9._:@+~-]{1,220}$")
_SAFE_POST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")


def _api_key() -> str | None:
    value = (os.getenv("MOLTBOOK_API_KEY") or "").strip()
    return value or None


def configured() -> bool:
    return _api_key() is not None


def _note_suspension(payload: object) -> None:
    global _SUSPENDED_UNTIL
    if not isinstance(payload, (dict, list, str)):
        return
    try:
        text = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, sort_keys=True, ensure_ascii=True)
        )
    except (TypeError, ValueError):
        return
    match = _SUSPENSION_RE.search(text[:4000])
    if match is None:
        return
    try:
        value = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
    except ValueError:
        return
    value = value.astimezone(timezone.utc)
    if value > datetime.now(timezone.utc):
        _SUSPENDED_UNTIL = value


def outbound_status() -> dict:
    global _SUSPENDED_UNTIL
    now = datetime.now(timezone.utc)
    if _SUSPENDED_UNTIL is not None and _SUSPENDED_UNTIL <= now:
        _SUSPENDED_UNTIL = None
    return {
        "suspended": _SUSPENDED_UNTIL is not None,
        "suspended_until": (
            _SUSPENDED_UNTIL.isoformat().replace("+00:00", "Z")
            if _SUSPENDED_UNTIL is not None
            else None
        ),
    }


def _policy() -> safe_http.FetchPolicy:
    return safe_http.FetchPolicy(
        timeout_seconds=7.0,
        max_response_bytes=256_000,
        max_attempts=1,
        max_resolved_addresses=32,
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
    if method.upper() != "GET":
        suspension = outbound_status()
        if suspension["suspended"]:
            return (
                safe_http.FetchResult(None, None, "moltbook_suspended", 0),
                {
                    "error": "moltbook_suspended",
                    "suspended_until": suspension["suspended_until"],
                },
            )
    query = f"?{urlencode(params)}" if params else ""
    url = f"{MOLTBOOK_API_BASE}{path}{query}"
    result, response = safe_http.fetch_json(
        method,
        url,
        payload=payload,
        headers={"Authorization": f"Bearer {key}"},
        policy=_policy(),
        retain_http_error_json=True,
    )
    if result.status == 403:
        _note_suspension(response)
    return result, response


def platform_error_summary(result, payload: object) -> str | None:
    """Return only a short non-secret Moltbook error reason for observability."""

    values: list[str] = []
    if isinstance(payload, dict):
        for key in ("code", "error", "message", "detail", "reason"):
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)):
                text = str(value).strip()
                if text:
                    values.append(f"{key}={text[:160]}")
            elif isinstance(value, dict):
                for nested_key in ("code", "message", "error", "reason"):
                    nested = value.get(nested_key)
                    if isinstance(nested, (str, int, float, bool)):
                        text = str(nested).strip()
                        if text:
                            values.append(
                                f"{key}.{nested_key}={text[:160]}"
                            )
    fallback = getattr(result, "error", None)
    status = getattr(result, "status", None)
    if not values:
        if fallback:
            values.append(str(fallback)[:160])
        elif status is not None:
            values.append(f"http_{status}")
    joined = "; ".join(values[:4])
    if not joined:
        return None
    lowered = joined.lower()
    if any(
        marker in lowered
        for marker in (
            "bearer ",
            "api_key",
            "api-key",
            "password",
            "passwd",
            "secret=",
            "token=",
            "credential=",
        )
    ):
        return "redacted_platform_error"
    return joined[:400]


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


def _candidate(
    item: dict,
    *,
    evidence_state: str = "semantic_public_intent_match",
) -> dict | None:
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
        "evidence_state": evidence_state,
    }


def _item_text(item: dict) -> str:
    parts = []
    for key in ("title", "content", "text", "body", "description"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return " ".join(parts).lower()


def _looks_like_external_spend_intent(item: dict) -> bool:
    text = _item_text(item)
    if not text:
        return False

    direct_spend = (
        "pay", "paid", "price", "pricing", "budget", "purchase", "buy",
        "spend", "cost", "subscription", "billing", "metered", "x402",
        "fee", "vendor",
    )
    provider_need = (
        "provider", "recommend", "recommendation", "choose", "selection",
        "alternative", "fallback", "replacement", "outage", "reliable",
    )
    capability = (
        "api", "mcp", "agent", "tool", "service", "browser", "automation",
        "data", "search", "inference", "llm", "model", "gateway",
    )
    need_language = (
        "i need", "we need", "looking for", "seeking", "need a",
        "need an", "hire", "hiring",
    )

    has_capability = any(marker in text for marker in capability)
    return (
        has_capability and any(marker in text for marker in direct_spend)
    ) or (
        has_capability
        and any(marker in text for marker in provider_need)
        and any(marker in text for marker in need_language)
    )


def _recent_post_items(payload: dict) -> list[dict]:
    for key in ("posts", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("posts", "items", "results"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def browse_recent_intent(limit: int = 15) -> dict:
    """Scan the global newest-post stream and keep only external-spend intent."""

    bounded_limit = max(1, min(int(limit), MAX_RECENT_POST_RESULTS))
    result, payload = _request_json(
        "GET",
        "/posts",
        params={"sort": "new", "limit": bounded_limit},
    )
    if result.error or result.status != 200 or not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "error": platform_error_summary(result, payload),
            "http_status": result.status,
            "candidates": [],
            "outbound_contact_performed": False,
        }

    candidates = []
    scanned = 0
    for item in _recent_post_items(payload):
        scanned += 1
        if not _looks_like_external_spend_intent(item):
            continue
        candidate = _candidate(
            item,
            evidence_state="recent_global_public_intent_match",
        )
        if candidate is not None:
            candidates.append(candidate)

    return {
        "status": "success",
        "error": None,
        "http_status": result.status,
        "candidates": candidates,
        "outbound_contact_performed": False,
        "resource_bounds": {
            "candidate_limit": bounded_limit,
            "recent_posts_scanned": scanned,
            "api_attempts": result.attempts,
            "sort": "new",
        },
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
            "error": platform_error_summary(result, payload),
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


def build_outreach_comment(
    *,
    public_base_url: str,
    recipient: str | None = None,
    intent: str | None = None,
) -> str:
    base = str(public_base_url or "").strip().rstrip("/")
    if not base.startswith("https://"):
        raise ValueError("public_base_url must be HTTPS")
    name = str(recipient or "").strip()
    addressed = (
        f"@{name}, "
        if _SAFE_AGENT_NAME.fullmatch(name) and name.lower() not in _SELF_NAMES
        else ""
    )
    intent_label = _INTENT_LABELS.get(
        str(intent or "").strip(),
        "external-spend decision",
    )
    text = (
        f"{addressed}if this {intent_label} is still current, AION can run a "
        "zero-cost pre-spend check before money is committed: POST "
        f"{base}/commercial/route-intelligence/preflight. "
        "The free preflight returns GO/HOLD/STOP; it requires no membership or "
        "payment and executes no provider. If this thread is no longer relevant, "
        "ignore this message; AION will not contact this target again. "
        "AION-operated outreach."
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


def dm_request(agent_name: str, message: str) -> dict:
    """Send one consent-based DM request to a bounded Moltbook agent name."""

    name = str(agent_name or "").strip()
    text = str(message or "").strip()
    if (
        not _SAFE_AGENT_NAME.fullmatch(name)
        or name.lower() in _SELF_NAMES
        or not 10 <= len(text) <= MAX_DM_MESSAGE_CHARS
    ):
        return {
            "status": "rejected",
            "accepted": False,
            "error": "invalid_moltbook_dm_request",
            "http_status": None,
        }
    result, payload = _request_json(
        "POST",
        "/agents/dm/request",
        payload={"to": name, "message": text},
    )
    accepted = bool(
        result.status is not None
        and 200 <= result.status < 300
        and (not isinstance(payload, dict) or payload.get("success") is not False)
    )
    return {
        "status": "success" if accepted else "rejected",
        "accepted": accepted,
        "error": None if accepted else platform_error_summary(result, payload),
        "http_status": result.status,
    }


def dm_conversations(limit: int = 50) -> dict:
    """Read a bounded summary of active DM conversations."""

    bounded_limit = max(1, min(int(limit), 50))
    result, payload = _request_json("GET", "/agents/dm/conversations")
    if result.error or result.status != 200 or not isinstance(payload, dict):
        return {
            "status": "unavailable",
            "error": result.error or f"http_{result.status}",
            "conversations": [],
            "total_unread": 0,
        }
    conversations = payload.get("conversations")
    items = conversations.get("items") if isinstance(conversations, dict) else []
    if not isinstance(items, list):
        items = []
    rows = []
    for item in items[:bounded_limit]:
        if not isinstance(item, dict):
            continue
        conversation_id = str(item.get("conversation_id") or "").strip()
        with_agent = item.get("with_agent")
        agent_name = (
            str(with_agent.get("name") or "").strip()
            if isinstance(with_agent, dict)
            else ""
        )
        if not conversation_id or not _SAFE_AGENT_NAME.fullmatch(agent_name):
            continue
        rows.append(
            {
                "conversation_id": conversation_id[:160],
                "agent_name": agent_name,
                "unread_count": int(item.get("unread_count") or 0),
                "you_initiated": bool(item.get("you_initiated")),
                "last_message_at": item.get("last_message_at"),
            }
        )
    return {
        "status": "success",
        "error": None,
        "conversations": rows,
        "total_unread": int(payload.get("total_unread") or 0),
    }


def dm_send(conversation_id: str, message: str) -> dict:
    """Send one bounded reply inside an already-approved conversation."""

    cid = str(conversation_id or "").strip()
    text = str(message or "").strip()
    if (
        not cid
        or len(cid) > 160
        or any(ord(ch) <= 32 or ord(ch) == 127 for ch in cid)
        or not 1 <= len(text) <= MAX_DM_MESSAGE_CHARS
    ):
        return {
            "status": "rejected",
            "sent": False,
            "error": "invalid_moltbook_dm_send",
            "http_status": None,
        }
    result, payload = _request_json(
        "POST",
        f"/agents/dm/conversations/{cid}/send",
        payload={"message": text},
    )
    sent = bool(
        result.status is not None
        and 200 <= result.status < 300
        and (not isinstance(payload, dict) or payload.get("success") is not False)
    )
    return {
        "status": "success" if sent else "rejected",
        "sent": sent,
        "error": None if sent else platform_error_summary(result, payload),
        "http_status": result.status,
    }


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
