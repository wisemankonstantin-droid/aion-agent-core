"""Trusted canonical public origin for machine-facing AION URLs."""

from __future__ import annotations

import os
from urllib.parse import urlsplit, urlunsplit


class PublicOriginError(RuntimeError):
    pass


def _normalize_origin(value: str) -> str:
    raw = str(value or "").strip()
    if not raw or any(ord(character) <= 32 or ord(character) == 127 for character in raw):
        raise PublicOriginError("A trusted canonical AION HTTPS origin is required")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise PublicOriginError("Configured AION public origin is invalid") from exc
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise PublicOriginError("A trusted canonical AION HTTPS origin is required")
    hostname = parsed.hostname.lower()
    display_host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = display_host if port in (None, 443) else f"{display_host}:{port}"
    return urlunsplit(("https", netloc, "", "", ""))


def canonical_public_origin() -> str:
    """Return an operator-controlled origin, never a request Host-derived URL."""
    configured = os.getenv("AION_PUBLIC_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if configured:
        return _normalize_origin(configured)
    if os.getenv("RENDER") or os.getenv("RENDER_SERVICE_ID"):
        raise PublicOriginError("Managed runtime requires a configured trusted public origin")
    # Fixed non-managed fallback supports local development without trusting Host.
    return _normalize_origin(os.getenv("AION_TEST_PUBLIC_URL", "https://localhost:8000"))
