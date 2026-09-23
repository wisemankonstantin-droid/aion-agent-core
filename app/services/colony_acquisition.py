"""The Colony acquisition adapter for the existing AION Ambassador swarm.

The Colony is an agent social/marketplace surface already used by AION through
scripts/colony_bootstrap.py. This runtime adapter preserves that identity rather
than creating extra accounts.

Rules:
- public search/paid-task discovery is read-only and works without credentials;
- outbound comments require the existing COLONY_API_KEY and a fresh JWT;
- full thread context is fetched before every comment;
- an existing AION comment in the thread suppresses another write;
- one-target/one-contact is still enforced by Ambassador persistence;
- no API key/JWT/raw private content is returned to callers.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlencode, urlsplit

from . import safe_http


COLONY_ORIGIN = "https://thecolony.ai"
COLONY_API_BASE = f"{COLONY_ORIGIN}/api/v1"
MAX_SEARCH_RESULTS = 5
MAX_QUERY_CHARS = 500
MAX_COMMENT_CHARS = 900
MAX_CONTEXT_BYTES = 256_000
_SELF_NAMES = {"aion-supreme", "aion_supreme", "aion supreme"}
_SAFE_AGENT_NAME = re.compile(r"^[A-Za-z0-9._:@+~-]{1,160}$")
_SAFE_POST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
_DEMAND_MARKERS = (
    "looking for",
    "seeking ",
    "wanted:",
    "wanted ",
    "need an agent",
    "need a provider",
    "need someone",
    "we need ",
    "please submit your bid",
    "please submit bids",
    "submit your bids",
    "bounty",
    "request for ",
    "hiring ",
    "looking to hire",
    "需要",
    "busco ",
    "se busca ",
)
_SUPPLY_MARKERS = (
    "for hire",
    "what i sell",
    "i sell ",
    "services & pricing",
    "services (",
    "i am available for",
    "available for immediate work",
    "how to order",
    "what i deliver",
)


def _buyer_demand_task(item: dict) -> bool:
    """Conservatively separate buyer demand from mislabelled seller listings."""

    if item.get("accepting_submissions") is False:
        return False
    title = str(item.get("title") or "").strip().lower()
    body = str(item.get("body") or "").strip().lower()
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    normalized_tags = {str(tag).strip().lower() for tag in tags}
    text = f"{title}\n{body}"
    if "for-hire" in normalized_tags or any(marker in text for marker in _SUPPLY_MARKERS):
        return False
    return any(marker in text for marker in _DEMAND_MARKERS)


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
    "security_buyers": "security-provider decision",
    "observability_buyers": "monitoring/observability-provider decision",
    "storage_compute_buyers": "storage/compute-provider decision",
    "payments_buyers": "payment-rail/provider decision",
    "verification_buyers": "provider-verification decision",
}


def _api_key() -> str | None:
    value = (os.getenv("COLONY_API_KEY") or "").strip()
    return value or None


def configured() -> bool:
    return _api_key() is not None


def _policy(*, attempts: int = 1) -> safe_http.FetchPolicy:
    return safe_http.FetchPolicy(
        timeout_seconds=7.0,
        max_response_bytes=MAX_CONTEXT_BYTES,
        max_attempts=attempts,
        max_resolved_addresses=32,
        user_agent="AION-Colony-Acquisition/0.8.0",
    )


def _safe_path(path: str) -> bool:
    return (
        isinstance(path, str)
        and path.startswith("/")
        and "://" not in path
        and "\\" not in path
        and len(path) <= 500
    )


def _request_public(
    method: str,
    path: str,
    *,
    payload: object | None = None,
    params: dict[str, object] | None = None,
    token: str | None = None,
):
    if not _safe_path(path):
        return safe_http.FetchResult(None, None, "invalid_colony_path", 0), None
    query = f"?{urlencode(params)}" if params else ""
    headers = {"Authorization": f"Bearer {token}"} if token else None
    return safe_http.fetch_json(
        method,
        f"{COLONY_API_BASE}{path}{query}",
        payload=payload,
        headers=headers,
        policy=_policy(),
        retain_http_error_json=True,
    )


def _access_token() -> tuple[safe_http.FetchResult, str | None]:
    key = _api_key()
    if key is None:
        return safe_http.FetchResult(None, None, "colony_api_key_missing", 0), None
    result, payload = _request_public(
        "POST",
        "/auth/token",
        payload={"api_key": key},
    )
    token = (
        str(payload.get("access_token") or "").strip()
        if isinstance(payload, dict)
        else ""
    )
    if (
        result.status is None
        or not 200 <= result.status < 300
        or not token
        or len(token) > 4096
    ):
        return result, None
    return result, token


def platform_error_summary(result, payload: object) -> str | None:
    values = []
    if isinstance(payload, dict):
        for key in ("code", "error", "message", "detail", "reason"):
            value = payload.get(key)
            if isinstance(value, (str, int, float, bool)) and str(value).strip():
                values.append(f"{key}={str(value).strip()[:160]}")
    if not values:
        error = getattr(result, "error", None)
        status = getattr(result, "status", None)
        if error:
            values.append(str(error)[:160])
        elif status is not None:
            values.append(f"http_{status}")
    joined = "; ".join(values[:4])
    lowered = joined.lower()
    if any(
        marker in lowered
        for marker in (
            "bearer ",
            "api_key",
            "api-key",
            "password",
            "secret=",
            "token=",
            "credential=",
        )
    ):
        return "redacted_platform_error"
    return joined[:400] or None


def account_status() -> dict:
    if not configured():
        return {
            "configured": False,
            "authenticated": False,
            "status": "read_only",
            "error": "colony_api_key_missing",
        }
    token_result, token = _access_token()
    if token is None:
        return {
            "configured": True,
            "authenticated": False,
            "status": "auth_unavailable",
            "http_status": token_result.status,
            "error": token_result.error or "token_exchange_failed",
        }
    result, payload = _request_public("GET", "/users/me", token=token)
    username = ""
    if isinstance(payload, dict):
        user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
        username = str(payload.get("username") or user.get("username") or "").strip()
    authenticated = bool(
        result.status is not None
        and 200 <= result.status < 300
        and username.lower() in _SELF_NAMES
    )
    return {
        "configured": True,
        "authenticated": authenticated,
        "status": "ready" if authenticated else "identity_mismatch_or_unavailable",
        "http_status": result.status,
        "username": username[:160] if authenticated else None,
        "error": None if authenticated else platform_error_summary(result, payload),
    }


def _rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    rows = []
    for key in ("posts", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("posts", "results", "items"):
            value = data.get(key)
            if isinstance(value, list):
                rows.extend(row for row in value if isinstance(row, dict))
    # Search may group results by kind.
    for key in ("post_results", "matches"):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    return rows


def _post_id(item: dict) -> str | None:
    nested = item.get("post") if isinstance(item.get("post"), dict) else {}
    for value in (
        item.get("post_id"),
        item.get("id") if str(item.get("type") or "post").lower() == "post" else None,
        nested.get("id"),
    ):
        text = str(value or "").strip()
        if _SAFE_POST_ID.fullmatch(text):
            return text
    return None


def _author(item: dict) -> str | None:
    nested_post = item.get("post") if isinstance(item.get("post"), dict) else {}
    candidates = [
        item.get("username"),
        item.get("author_username"),
        nested_post.get("author_username"),
    ]
    for holder in (item.get("author"), item.get("user"), nested_post.get("author")):
        if isinstance(holder, dict):
            candidates.extend((holder.get("username"), holder.get("name")))
        elif isinstance(holder, str):
            candidates.append(holder)
    for value in candidates:
        text = str(value or "").strip()
        if _SAFE_AGENT_NAME.fullmatch(text) and text.lower() not in _SELF_NAMES:
            return text
    return None


def _candidate(item: dict, *, evidence_state: str) -> dict | None:
    post_id = _post_id(item)
    author = _author(item)
    if post_id is None or author is None:
        return None
    return {
        "source": "colony",
        "identifier": f"colony:{author}",
        "name": author,
        "url": f"{COLONY_ORIGIN}/api/v1/posts/{post_id}",
        "interaction_url": f"{COLONY_API_BASE}/posts/{post_id}/comments",
        "manifest_reachable": False,
        "declared_a2a_v1_jsonrpc": False,
        "interaction_url_validated": True,
        "authentication_requirement": "colony_bearer",
        "payment_required": False,
        "colony_post_id": post_id,
        "colony_author": author,
        "evidence_state": evidence_state,
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
    bounded = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    result, payload = _request_public(
        "GET",
        "/search",
        params={
            "q": query,
            "sort": "relevance",
            "limit": bounded,
            "author_type": "agent",
        },
    )
    if result.error or result.status != 200:
        return {
            "status": "unavailable",
            "error": platform_error_summary(result, payload),
            "http_status": result.status,
            "candidates": [],
            "outbound_contact_performed": False,
        }
    candidates = []
    for item in _rows(payload):
        candidate = _candidate(
            item,
            evidence_state="colony_public_agent_intent_match",
        )
        if candidate is not None:
            candidates.append(candidate)
        if len(candidates) >= bounded:
            break
    return {
        "status": "success",
        "error": None,
        "http_status": result.status,
        "candidates": candidates,
        "outbound_contact_performed": False,
        "resource_bounds": {
            "candidate_limit": bounded,
            "query_character_limit": MAX_QUERY_CHARS,
            "api_attempts": result.attempts,
            "author_type": "agent",
        },
    }


def browse_paid_tasks(limit: int = MAX_SEARCH_RESULTS) -> dict:
    """Read public marketplace tasks and retain only clear buyer-demand posts.

    The Colony contract defines paid_task as work that workers bid on, but public
    data also contains seller self-listings mislabelled as paid_task. Intent-first
    acquisition must not count those sellers as buyer demand.
    """

    bounded = max(1, min(int(limit), MAX_SEARCH_RESULTS))
    result, payload = _request_public(
        "GET",
        "/marketplace/tasks",
        params={
            "sort": "budget",
            "limit": min(20, max(bounded * 4, bounded)),
        },
    )
    if result.error or result.status != 200:
        return {
            "status": "unavailable",
            "error": platform_error_summary(result, payload),
            "http_status": result.status,
            "candidates": [],
            "outbound_contact_performed": False,
        }
    candidates = []
    filtered_supply_like = 0
    for item in _rows(payload):
        if not _buyer_demand_task(item):
            filtered_supply_like += 1
            continue
        candidate = _candidate(
            item,
            evidence_state="colony_marketplace_buyer_demand",
        )
        if candidate is not None:
            candidates.append(candidate)
        if len(candidates) >= bounded:
            break
    return {
        "status": "success",
        "error": None,
        "http_status": result.status,
        "candidates": candidates,
        "outbound_contact_performed": False,
        "resource_bounds": {
            "candidate_limit": bounded,
            "api_attempts": result.attempts,
            "surface": "marketplace_tasks",
            "demand_filter": "conservative_buyer_intent",
            "filtered_supply_like": filtered_supply_like,
        },
    }


def build_outreach_comment(
    *,
    public_base_url: str,
    recipient: str | None,
    intent: str | None,
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
        f"{addressed}this thread matched AION's {intent_label} lane. "
        "Before committing external spend, AION can run a zero-cost preflight: POST "
        f"{base}/commercial/route-intelligence/preflight. "
        "It returns GO/HOLD/STOP without membership, payment, or provider execution. "
        "If this need is no longer current, ignore this reply; AION will not contact "
        "this target again. AION-operated outreach."
    )
    if len(text) > MAX_COMMENT_CHARS:
        raise ValueError("Colony outreach comment exceeds bound")
    return text


def _existing_aion_comment(context: object) -> bool:
    if not isinstance(context, dict):
        return False
    comments = context.get("comments")
    if isinstance(comments, dict):
        comments = comments.get("items") or comments.get("comments")
    if not isinstance(comments, list):
        comments = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        flat_name = str(
            comment.get("username") or comment.get("author_username") or ""
        ).strip().lower()
        if flat_name in _SELF_NAMES:
            return True
        author = _author(comment)
        if author and author.lower() in _SELF_NAMES:
            return True
        holder = comment.get("author")
        if isinstance(holder, dict):
            username = str(holder.get("username") or "").strip().lower()
            if username in _SELF_NAMES:
                return True
    return False


def post_comment(interaction_url: str, content: str):
    """Fetch full thread context, dedupe AION, then post one bounded reply."""

    text = str(content or "").strip()
    if not text or len(text) > MAX_COMMENT_CHARS:
        return safe_http.FetchResult(None, None, "invalid_colony_comment", 0), None

    try:
        parsed = urlsplit(str(interaction_url or ""))
    except ValueError:
        parsed = None
    if (
        parsed is None
        or parsed.scheme != "https"
        or parsed.hostname not in {"thecolony.ai", "thecolony.cc"}
        or parsed.query
        or parsed.fragment
    ):
        return safe_http.FetchResult(None, None, "invalid_colony_interaction_url", 0), None
    match = re.fullmatch(r"/api/v1/posts/([A-Za-z0-9._:-]{1,160})/comments", parsed.path)
    if match is None:
        return safe_http.FetchResult(None, None, "invalid_colony_interaction_url", 0), None
    post_id = match.group(1)

    token_result, token = _access_token()
    if token is None:
        return (
            safe_http.FetchResult(
                token_result.status,
                None,
                token_result.error or "colony_auth_unavailable",
                token_result.attempts,
            ),
            None,
        )

    context_result, context = _request_public(
        "GET",
        f"/posts/{post_id}/context",
        token=token,
    )
    if (
        context_result.status is None
        or not 200 <= context_result.status < 300
        or not isinstance(context, dict)
    ):
        return context_result, context
    if _existing_aion_comment(context):
        return (
            safe_http.FetchResult(409, None, "colony_aion_comment_already_exists", 0),
            {"error": "colony_aion_comment_already_exists"},
        )

    return _request_public(
        "POST",
        f"/posts/{post_id}/comments",
        payload={"body": text},
        token=token,
    )
