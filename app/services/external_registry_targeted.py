"""Targeted public A2A Registry lookup for Commercial Router privacy.

This helper deliberately accepts only a Registry identifier. It has no `need`
parameter, so identifier-scoped routing cannot accidentally fall back to a
semantic `?q=<need>` search.
"""
from __future__ import annotations

import os
import re
from urllib.parse import quote

from . import external_registry as _registry


_TARGET_IDENTIFIER = re.compile(r"^[A-Za-z0-9_@+~-]+(?:\.[A-Za-z0-9_@+~-]+)*$")


def _normalized_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    identifier = value.strip()
    if (
        not identifier
        or len(identifier) > 240
        or ".." in identifier
        or not _TARGET_IDENTIFIER.fullmatch(identifier)
        or any(ord(character) < 32 or ord(character) == 127 for character in identifier)
    ):
        return None
    return identifier


def _failure_result(failure: str, budget) -> _registry.DiscoveryResult:
    return _registry.DiscoveryResult(
        [], failure, failure, _registry._discovery_bounds(budget)
    )


def discover_external_agent_by_identifier_with_status(identifier: str) -> _registry.DiscoveryResult:
    normalized = _normalized_identifier(identifier)
    empty_budget = _registry._OutboundBudget()
    if normalized is None or os.getenv("AION_DISABLE_EXTERNAL_DISCOVERY") == "1":
        return _failure_result("unavailable", empty_budget)
    if not _registry._allow_discovery():
        return _failure_result("rate_limited", empty_budget)

    budget = _registry._OutboundBudget()
    detail_url = f"{_registry.A2A_REGISTRY_SEARCH}/{quote(normalized, safe='')}"
    status, payload, error = _registry._read_json("GET", detail_url, budget=budget)
    if status == 404 and not error:
        return _registry.DiscoveryResult(
            [], "success", None, _registry._discovery_bounds(budget)
        )
    if error or status != 200:
        failure = _registry._operational_failure(status, error)
        return _failure_result(failure, budget)
    if not isinstance(payload, dict):
        return _failure_result("unavailable", budget)

    detail = _registry._unwrap(payload)
    if not isinstance(detail, dict):
        return _failure_result("unavailable", budget)

    package_name = _registry._first(detail, "package_name", "package", "package_id")
    manifest_url = _registry._first(
        detail,
        "manifest_url",
        "manifestUrl",
        "agent_card_url",
        "agentCardUrl",
        "url",
        "endpoint",
    )
    resolved = {}
    resolution_error = None
    if not manifest_url and package_name:
        resolve_url = (
            f"{_registry.A2A_REGISTRY_SEARCH}/resolve/"
            f"{quote(str(package_name), safe='')}"
        )
        resolve_status, resolve_payload, resolve_error = _registry._read_json(
            "GET", resolve_url, budget=budget
        )
        if resolve_status == 200 and isinstance(resolve_payload, dict):
            resolved = _registry._unwrap(resolve_payload)
            manifest_url = _registry._first(
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
    row = {
        "source": "global_a2a_registry",
        "identifier": normalized,
        "package_name": package_name
        or _registry._first(resolved, "package_name", "package", "package_id"),
        "name": _registry._first(detail, "name", "display_name", "title")
        or _registry._first(resolved, "name", "display_name", "title")
        or normalized,
        "description": _registry._first(detail, "description") or "",
        "url": manifest_url,
        "registry_verified_claim": (
            detail.get("verified")
            if "verified" in detail
            else resolved.get("verified")
            if "verified" in resolved
            else None
        ),
        "raw_category": detail.get("category") or detail.get("target"),
        "resolution_status": "manifest_url_declared" if has_manifest else "unresolved",
        "resolution_reason": None
        if has_manifest
        else (resolution_error or "no_manifest_url_declared"),
        "evidence_state": "registry_manifest_url_declared"
        if has_manifest
        else "registry_hit_unresolved",
        "followable": has_manifest,
    }

    validated = _registry._validate_external(row, budget)
    failure_class = None
    reason = validated.get("failure_reason")
    if reason == "outbound_budget_exhausted":
        failure_class = "unavailable"
    elif reason == "http_429":
        failure_class = "rate_limited"
    elif not validated.get("manifest_reachable") and reason not in {
        None,
        "no_manifest_url",
    }:
        failure_class = (
            "unavailable"
            if str(reason) in {"response_too_large", "content_encoding_rejected"}
            else "endpoint_unreachable"
        )

    resource_bounds = _registry._discovery_bounds(budget)
    validated["resource_bounds"] = dict(resource_bounds)
    return _registry.DiscoveryResult(
        [validated],
        failure_class or "success",
        failure_class,
        resource_bounds,
    )
