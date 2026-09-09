"""Bounded, declaration-only discovery of external A2A candidates."""

from __future__ import annotations

from collections import OrderedDict, deque
import os
import threading
import time as _time
from urllib.parse import quote, urlencode

from app.services import safe_http as _safe_http


A2A_REGISTRY_SEARCH = "https://api.a2a-registry.org/public/agents"

_AION_MAX_EXTERNAL_CANDIDATES = 5
_AION_MAX_EXTERNAL_QUERY_CHARS = 128
_AION_OUTBOUND_ATTEMPT_BUDGET = 12
_AION_EXTERNAL_TIMEOUT_SECONDS = 4.0
_AION_EXTERNAL_MAX_ATTEMPTS = 2
_AION_MAX_EXTERNAL_BYTES = 256_000
_AION_VALIDATION_TTL = 600
_AION_VALIDATION_CACHE_MAX_ENTRIES = 128
_AION_DISCOVERY_RATE_LIMIT = 30
_AION_DISCOVERY_RATE_WINDOW_SECONDS = 60

_socket = _safe_http._socket
_ssl = _safe_http._ssl
_PinnedHTTPSConnection = _safe_http.PinnedHTTPSConnection

_AION_VALIDATION_CACHE = OrderedDict()
_AION_DISCOVERY_RATE_TIMES = deque()
_AION_DISCOVERY_STATE_LOCK = threading.Lock()


class _OutboundBudget:
    def __init__(self, maximum: int | None = None):
        self.maximum = (
            _AION_OUTBOUND_ATTEMPT_BUDGET if maximum is None else maximum
        )
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.maximum - self.used)

    def consume(self, attempts: int) -> None:
        self.used = min(self.maximum, self.used + max(0, int(attempts)))


def _normalized_query(query) -> str | None:
    if not isinstance(query, str):
        return None
    normalized = query.strip()
    if (
        not normalized
        or len(normalized) > _AION_MAX_EXTERNAL_QUERY_CHARS
        or any(ord(character) < 32 for character in normalized)
    ):
        return None
    return normalized


def _normalized_limit(limit) -> int | None:
    try:
        return max(1, min(int(limit), _AION_MAX_EXTERNAL_CANDIDATES))
    except (TypeError, ValueError, OverflowError):
        return None


def _allow_discovery(now: float | None = None) -> bool:
    current = _time.monotonic() if now is None else now
    cutoff = current - _AION_DISCOVERY_RATE_WINDOW_SECONDS
    with _AION_DISCOVERY_STATE_LOCK:
        while _AION_DISCOVERY_RATE_TIMES and _AION_DISCOVERY_RATE_TIMES[0] <= cutoff:
            _AION_DISCOVERY_RATE_TIMES.popleft()
        if len(_AION_DISCOVERY_RATE_TIMES) >= _AION_DISCOVERY_RATE_LIMIT:
            return False
        _AION_DISCOVERY_RATE_TIMES.append(current)
        return True


def _cache_get(key: str, now: float):
    with _AION_DISCOVERY_STATE_LOCK:
        cached = _AION_VALIDATION_CACHE.get(key)
        if cached is None:
            return None
        expires_at, state = cached
        if expires_at <= now:
            del _AION_VALIDATION_CACHE[key]
            return None
        _AION_VALIDATION_CACHE.move_to_end(key)
        return dict(state)


def _cache_put(key: str, state: dict, now: float) -> None:
    with _AION_DISCOVERY_STATE_LOCK:
        expired = [
            cached_key
            for cached_key, (expires_at, _) in _AION_VALIDATION_CACHE.items()
            if expires_at <= now
        ]
        for cached_key in expired:
            del _AION_VALIDATION_CACHE[cached_key]
        _AION_VALIDATION_CACHE.pop(key, None)
        while len(_AION_VALIDATION_CACHE) >= _AION_VALIDATION_CACHE_MAX_ENTRIES:
            _AION_VALIDATION_CACHE.popitem(last=False)
        _AION_VALIDATION_CACHE[key] = (now + _AION_VALIDATION_TTL, dict(state))


def _unwrap(payload):
    if not isinstance(payload, dict):
        return {}
    for key in ("agent", "data", "result"):
        if isinstance(payload.get(key), dict):
            return payload[key]
    return payload


def _first(mapping, *keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return None


def _resolve_public_https(url):
    return _safe_http.resolve_public_https(url, max_addresses=4)


def _public_url(url):
    _, candidates, reason = _resolve_public_https(url)
    return bool(candidates), reason


def _read_json(
    method,
    url,
    payload=None,
    headers=None,
    timeout=_AION_EXTERNAL_TIMEOUT_SECONDS,
    budget=None,
):
    max_attempts = _AION_EXTERNAL_MAX_ATTEMPTS
    if budget is not None:
        if budget.remaining <= 0:
            return None, None, "outbound_budget_exhausted"
        max_attempts = min(max_attempts, budget.remaining)
    bounded_timeout = max(0.5, min(float(timeout), 7.0))
    policy = _safe_http.FetchPolicy(
        timeout_seconds=bounded_timeout,
        max_response_bytes=_AION_MAX_EXTERNAL_BYTES,
        max_attempts=max_attempts,
        max_resolved_addresses=4,
        user_agent="AION-External-Discovery/0.7.1",
    )
    result, data = _safe_http.fetch_json(
        method,
        url,
        payload=payload,
        headers=headers,
        policy=policy,
        connection_factory=_PinnedHTTPSConnection,
    )
    if budget is not None:
        budget.consume(result.attempts)
    return result.status, data, result.error


def _discover_external_agents_resolved(query: str, limit: int = 5, budget=None):
    query = _normalized_query(query)
    limit = _normalized_limit(limit)
    if (
        query is None
        or limit is None
        or os.getenv("AION_DISABLE_EXTERNAL_DISCOVERY") == "1"
    ):
        return []
    budget = budget or _OutboundBudget()
    search_url = f"{A2A_REGISTRY_SEARCH}?{urlencode({'q': query})}"
    status, payload, error = _read_json("GET", search_url, budget=budget)
    if error or status != 200:
        return []
    rows = payload if isinstance(payload, list) else _first(payload, "agents", "data")
    if not isinstance(rows, list):
        return []

    results = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        identifier = (
            row.get("identifier")
            or row.get("id")
            or row.get("package_name")
            or row.get("name")
        )
        detail = {}
        resolved = {}
        resolution_error = None
        if identifier:
            detail_url = f"{A2A_REGISTRY_SEARCH}/{quote(str(identifier), safe='')}"
            detail_status, detail_payload, detail_error = _read_json(
                "GET", detail_url, budget=budget
            )
            if detail_status == 200 and isinstance(detail_payload, dict):
                detail = _unwrap(detail_payload)
            else:
                resolution_error = detail_error or f"detail_http_{detail_status}"

        package_name = (
            _first(detail, "package_name", "package", "package_id")
            or row.get("package_name")
        )
        manifest_url = (
            _first(
                detail,
                "manifest_url",
                "manifestUrl",
                "agent_card_url",
                "agentCardUrl",
                "url",
                "endpoint",
            )
            or _first(
                row,
                "manifest_url",
                "manifestUrl",
                "agent_card_url",
                "agentCardUrl",
                "url",
                "endpoint",
            )
        )
        if not manifest_url and package_name:
            resolve_url = (
                f"{A2A_REGISTRY_SEARCH}/resolve/{quote(str(package_name), safe='')}"
            )
            resolve_status, resolve_payload, resolve_error = _read_json(
                "GET", resolve_url, budget=budget
            )
            if resolve_status == 200 and isinstance(resolve_payload, dict):
                resolved = _unwrap(resolve_payload)
                manifest_url = _first(
                    resolved,
                    "manifest_url",
                    "manifestUrl",
                    "agent_card_url",
                    "agentCardUrl",
                    "url",
                    "endpoint",
                )
            else:
                resolution_error = resolve_error or f"resolve_http_{resolve_status}"

        has_manifest = bool(manifest_url)
        results.append(
            {
                "source": "global_a2a_registry",
                "identifier": identifier,
                "package_name": package_name
                or _first(resolved, "package_name", "package", "package_id"),
                "name": _first(detail, "name", "display_name", "title")
                or _first(resolved, "name", "display_name", "title")
                or row.get("name")
                or row.get("display_name")
                or row.get("title")
                or identifier,
                "description": _first(detail, "description")
                or row.get("description")
                or "",
                "url": manifest_url,
                "registry_verified_claim": detail.get("verified")
                if "verified" in detail
                else resolved.get("verified")
                if "verified" in resolved
                else row.get("verified"),
                "raw_category": row.get("category") or row.get("target"),
                "resolution_status": "manifest_url_declared"
                if has_manifest
                else "unresolved",
                "resolution_reason": None
                if has_manifest
                else (resolution_error or "no_manifest_url_declared"),
                "evidence_state": "registry_manifest_url_declared"
                if has_manifest
                else "registry_hit_unresolved",
                "followable": has_manifest,
            }
        )
        if budget.remaining <= 0:
            break
    return results


_AION_RESOLVED_DISCOVER = _discover_external_agents_resolved


def _interface(card):
    if not isinstance(card, dict):
        return None, None, None
    interfaces = card.get("supportedInterfaces") or card.get("supported_interfaces") or []
    if isinstance(interfaces, list):
        for interface in interfaces:
            if not isinstance(interface, dict):
                continue
            binding = (
                interface.get("protocolBinding")
                or interface.get("protocol_binding")
                or ""
            ).upper()
            version = str(
                interface.get("protocolVersion")
                or interface.get("protocol_version")
                or ""
            )
            url = interface.get("url")
            if binding == "JSONRPC" and url:
                return url, version or None, "JSONRPC"
    url = card.get("url") or card.get("endpoint")
    version = str(card.get("protocolVersion") or card.get("protocol_version") or "")
    if url:
        return url, version or None, "JSONRPC_LEGACY"
    return None, None, None


def _validate_external(row, budget=None):
    base = dict(row or {})
    manifest_url = base.get("url")
    cache_key = str(manifest_url or "")
    now = _time.monotonic()
    if cache_key:
        cached = _cache_get(cache_key, now)
        if cached is not None:
            merged = dict(base)
            merged.update(cached)
            return merged

    state = {
        "resolved": bool(manifest_url),
        "reachable": False,
        "manifest_reachable": False,
        "card_parseable": False,
        "protocol_declared": False,
        "declared_a2a_v1_jsonrpc": False,
        "authentication_requirement": "unknown",
        "public_no_credentials": False,
        "conformant": False,
        "interaction_url_validated": False,
        "interaction_contacted": False,
        "interaction_success": False,
        "callable": False,
        "verified_external_agent": False,
        "verified_outcome": False,
        "last_success_at": None,
        "failure_reason": None,
        "manifest_followable": bool(base.get("followable")),
        "followable": False,
    }
    if not manifest_url:
        state["failure_reason"] = "no_manifest_url"
        state["evidence_state"] = "registry_hit_unresolved"
        state["validation_status"] = "unverified"
    else:
        status, card, error = _read_json("GET", manifest_url, budget=budget)
        state["manifest_http_status"] = status
        if status == 200 and isinstance(card, dict):
            state["reachable"] = True
            state["manifest_reachable"] = True
            state["card_parseable"] = True
            state["card_name"] = card.get("name")
            state["card_version"] = card.get("version")
            security_schemes = card.get("securitySchemes", card.get("security_schemes"))
            security_requirements = card.get("security")
            if security_schemes is not None and not isinstance(security_schemes, dict):
                authentication_requirement = "unknown"
            elif security_requirements is not None and not isinstance(
                security_requirements, list
            ):
                authentication_requirement = "unknown"
            elif security_schemes or security_requirements:
                authentication_requirement = "credentials_required"
            else:
                # In the A2A Agent Card schema, absent/empty security
                # requirements mean no credential scheme is required.
                authentication_requirement = "none"
            state["authentication_requirement"] = authentication_requirement
            state["public_no_credentials"] = authentication_requirement == "none"
            interaction_url, version, binding = _interface(card)
            state["interaction_url"] = interaction_url
            state["protocol_version"] = version
            state["protocol_binding"] = binding
            state["protocol_declared"] = bool(interaction_url and binding)
            state["declared_a2a_v1_jsonrpc"] = bool(
                interaction_url and binding == "JSONRPC" and str(version) == "1.0"
            )
            if interaction_url:
                valid_url, validation_error = _public_url(interaction_url)
                state["interaction_url_validated"] = valid_url
            else:
                validation_error = "no_interaction_url_declared"

            if state["declared_a2a_v1_jsonrpc"] and state["interaction_url_validated"]:
                state["evidence_state"] = "reachable_a2a_v1_declaration"
                state["validation_status"] = "declaration_observed"
            elif state["protocol_declared"] and not state["interaction_url_validated"]:
                state["failure_reason"] = validation_error
                state["evidence_state"] = "reachable_manifest_unsafe_interface"
                state["validation_status"] = "unverified"
            elif state["protocol_declared"]:
                state["failure_reason"] = "not_declared_a2a_v1_jsonrpc_interface"
                state["evidence_state"] = "reachable_manifest_protocol_declared"
                state["validation_status"] = "unverified"
            else:
                state["failure_reason"] = "no_a2a_jsonrpc_interface_declared"
                state["evidence_state"] = "reachable_manifest_protocol_unknown"
                state["validation_status"] = "unverified"
        else:
            state["failure_reason"] = error or "manifest_not_json_object"
            state["evidence_state"] = "unreachable_or_invalid_manifest"
            state["validation_status"] = "unverified"

    if cache_key:
        _cache_put(cache_key, state, now)
    merged = dict(base)
    merged.update(state)
    return merged


def discover_external_agents(query: str, limit: int = 5):
    normalized_query = _normalized_query(query)
    normalized_limit = _normalized_limit(limit)
    if (
        normalized_query is None
        or normalized_limit is None
        or os.getenv("AION_DISABLE_EXTERNAL_DISCOVERY") == "1"
        or not _allow_discovery()
    ):
        return []

    budget = _OutboundBudget()
    rows = _AION_RESOLVED_DISCOVER(normalized_query, normalized_limit, budget)
    results = []
    for row in rows[:normalized_limit]:
        if budget.remaining <= 0:
            break
        results.append(_validate_external(row, budget))

    resource_bounds = {
        "candidate_limit": _AION_MAX_EXTERNAL_CANDIDATES,
        "query_character_limit": _AION_MAX_EXTERNAL_QUERY_CHARS,
        "outbound_attempt_budget": budget.maximum,
        "outbound_attempts_used": budget.used,
        "response_byte_limit": _AION_MAX_EXTERNAL_BYTES,
        "cache_max_entries": _AION_VALIDATION_CACHE_MAX_ENTRIES,
        "cache_ttl_seconds": _AION_VALIDATION_TTL,
    }
    for result in results:
        result["resource_bounds"] = dict(resource_bounds)
    return results
