"""Bounded HTTPS retrieval with pinned, pre-validated destinations.

Remote bytes remain untrusted.  This module performs transport validation only;
callers remain responsible for validating and normalizing payload structure.
"""

from __future__ import annotations

from dataclasses import dataclass
import http.client as _http
import ipaddress as _ip
import json
import socket as _socket
import ssl as _ssl
from typing import Callable, Mapping
import urllib.parse as _uparse


DEFAULT_USER_AGENT = "AION-Live-Utility/0.7.1"


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    timeout_seconds: float = 7.0
    max_response_bytes: int = 256_000
    max_attempts: int = 2
    max_resolved_addresses: int = 4
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be in (0, 30]")
        if not 0 < self.max_response_bytes <= 2_000_000:
            raise ValueError("max_response_bytes must be in (0, 2000000]")
        if not 0 < self.max_attempts <= 4:
            raise ValueError("max_attempts must be in [1, 4]")
        if not 0 < self.max_resolved_addresses <= 8:
            raise ValueError("max_resolved_addresses must be in [1, 8]")
        if not self.user_agent.strip():
            raise ValueError("user_agent must not be empty")


@dataclass(frozen=True, slots=True)
class FetchResult:
    status: int | None
    body: bytes | None
    error: str | None
    attempts: int


def resolve_public_https(url: str, *, max_addresses: int = 8):
    """Resolve exactly once and reject the entire answer if any IP is non-global."""

    try:
        parsed = _uparse.urlparse(str(url or ""))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None, (), "url_must_be_public_https"
        # urlparse.port validates the numeric range and raises for malformed
        # values. Public HTTPS services may legitimately use an explicit
        # non-default port; the socket remains DNS-pinned and TLS still
        # authenticates the original hostname.
        explicit_port = parsed.port
        if explicit_port is not None and not 1 <= explicit_port <= 65535:
            return None, (), "invalid_port"
        port = explicit_port or 443
        infos = _socket.getaddrinfo(
            parsed.hostname,
            port,
            type=_socket.SOCK_STREAM,
        )
        if not infos:
            return None, (), "dns_no_addresses"
        candidates = []
        seen = set()
        for family, socktype, proto, _, sockaddr in infos:
            address = _ip.ip_address(sockaddr[0])
            if not address.is_global:
                return None, (), f"non_public_address:{address}"
            key = (family, socktype, proto, sockaddr)
            if key not in seen:
                seen.add(key)
                candidates.append(key)
        if len(candidates) > max_addresses:
            return None, (), "too_many_resolved_addresses"
        return parsed, tuple(candidates), None
    except Exception as exc:
        return None, (), f"url_validation_error:{type(exc).__name__}"


class PinnedHTTPSConnection(_http.HTTPConnection):
    """HTTPS over one validated numeric peer with the original TLS identity."""

    def __init__(self, hostname, candidate, timeout):
        super().__init__(hostname, 443, timeout=timeout)
        self._candidate = candidate
        self._tls_context = _ssl.create_default_context()

    def connect(self):
        family, socktype, proto, sockaddr = self._candidate
        raw = _socket.socket(family, socktype, proto)
        try:
            raw.settimeout(self.timeout)
            raw.connect(sockaddr)
            self.sock = self._tls_context.wrap_socket(
                raw,
                server_hostname=self.host,
            )
        except Exception:
            raw.close()
            raise


def _host_header(hostname: str) -> str:
    return f"[{hostname}]" if ":" in hostname else hostname


def fetch_bytes(
    method: str,
    url: str,
    *,
    payload: bytes | None = None,
    headers: Mapping[str, str] | None = None,
    policy: FetchPolicy = FetchPolicy(),
    connection_factory: Callable = PinnedHTTPSConnection,
) -> FetchResult:
    parsed, candidates, reason = resolve_public_https(
        url,
        max_addresses=policy.max_resolved_addresses,
    )
    if reason:
        return FetchResult(None, None, reason, 0)

    request_headers = {
        "User-Agent": policy.user_agent,
        "Accept": "application/json",
    }
    if headers:
        request_headers.update(headers)
    # Callers may add protocol headers but cannot redirect TLS/HTTP identity or
    # opt into transparent decompression that could bypass the byte budget.
    request_headers["Accept-Encoding"] = "identity"
    port = parsed.port or 443
    request_headers["Host"] = _host_header(parsed.hostname) + (
        f":{port}" if port != 443 else ""
    )
    target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    last_error = None

    for attempt in range(policy.max_attempts):
        candidate = candidates[attempt % len(candidates)]
        connection = connection_factory(
            parsed.hostname,
            candidate,
            policy.timeout_seconds,
        )
        try:
            connection.request(method, target, body=payload, headers=request_headers)
            response = connection.getresponse()
            raw = response.read(policy.max_response_bytes + 1)
            if len(raw) > policy.max_response_bytes:
                return FetchResult(response.status, None, "response_too_large", attempt + 1)
            get_header = getattr(response, "getheader", None)
            content_encoding = get_header("Content-Encoding") if get_header else None
            if content_encoding and content_encoding.lower() != "identity":
                return FetchResult(
                    response.status,
                    None,
                    "content_encoding_rejected",
                    attempt + 1,
                )
            if 300 <= response.status < 400:
                return FetchResult(response.status, None, "redirect_rejected", attempt + 1)
            if response.status >= 400:
                return FetchResult(
                    response.status,
                    None,
                    f"http_{response.status}",
                    attempt + 1,
                )
            return FetchResult(response.status, raw, None, attempt + 1)
        except Exception as exc:
            last_error = f"{type(exc).__name__}:{str(exc)[:240]}"
        finally:
            connection.close()
    return FetchResult(None, None, last_error or "connection_failed", policy.max_attempts)


def fetch_json(
    method: str,
    url: str,
    *,
    payload: object | None = None,
    headers: Mapping[str, str] | None = None,
    policy: FetchPolicy = FetchPolicy(),
    connection_factory: Callable = PinnedHTTPSConnection,
) -> tuple[FetchResult, object | None]:
    encoded = None
    request_headers = dict(headers or {})
    if payload is not None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    result = fetch_bytes(
        method,
        url,
        payload=encoded,
        headers=request_headers,
        policy=policy,
        connection_factory=connection_factory,
    )
    if result.error or result.body is None:
        return result, None
    try:
        return result, json.loads(result.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return FetchResult(result.status, None, "non_json_response", result.attempts), None
