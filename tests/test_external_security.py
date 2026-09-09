import json
import socket
import ssl

import pytest

from app.services import external_registry


PUBLIC_V4 = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
]
PRIVATE_V4 = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))
]
PUBLIC_V6 = [
    (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("2606:4700:4700::1111", 443, 0, 0))
]


class _Response:
    def __init__(self, status=200, payload=None, raw=None):
        self.status = status
        self._raw = raw if raw is not None else json.dumps(payload or {}).encode()

    def read(self, limit):
        return self._raw


class _Connection:
    responses = {}
    instances = []

    def __init__(self, hostname, candidate, timeout):
        self.hostname = hostname
        self.candidate = candidate
        self.timeout = timeout
        self.requests = []
        self.closed = False
        self.instances.append(self)

    def request(self, method, target, body=None, headers=None):
        self.requests.append((method, target, body, dict(headers or {})))

    def getresponse(self):
        return self.responses[self.hostname]

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_test_state(monkeypatch):
    monkeypatch.delenv("AION_DISABLE_EXTERNAL_DISCOVERY", raising=False)
    _Connection.responses = {}
    _Connection.instances = []
    external_registry._AION_VALIDATION_CACHE.clear()
    external_registry._AION_DISCOVERY_RATE_TIMES.clear()


def _one_address(raw):
    ip = raw[0] if isinstance(raw, tuple) else raw
    if ":" in ip:
        return [(socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 443))]


def test_public_https_ipv4_destination_passes_validation(monkeypatch):
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V4)
    assert external_registry._public_url("https://agent.example/card") == (True, None)


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.8", "169.254.169.254", "::1", "fe80::1"],
)
def test_non_global_destinations_are_rejected(monkeypatch, address):
    monkeypatch.setattr(
        external_registry._socket,
        "getaddrinfo",
        lambda *args, **kwargs: _one_address(address),
    )
    assert external_registry._public_url("https://agent.example/card") == (
        False,
        f"non_public_address:{address}",
    )


def test_mixed_public_and_private_dns_answer_is_rejected(monkeypatch):
    monkeypatch.setattr(
        external_registry._socket,
        "getaddrinfo",
        lambda *args, **kwargs: PUBLIC_V4 + PRIVATE_V4,
    )
    assert external_registry._public_url("https://agent.example/card") == (
        False,
        "non_public_address:127.0.0.1",
    )


def test_dns_rebinding_cannot_change_the_actual_connection_destination(monkeypatch):
    resolutions = iter([PUBLIC_V4, PRIVATE_V4])
    resolution_calls = []

    def resolve(*args, **kwargs):
        resolution_calls.append(args[0])
        return next(resolutions)

    _Connection.responses = {"agent.example": _Response(payload={"name": "Pinned"})}
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", resolve)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    status, payload, error = external_registry._read_json("GET", "https://agent.example/card")
    assert (status, payload, error) == (200, {"name": "Pinned"}, None)
    assert resolution_calls == ["agent.example"]
    assert len(_Connection.instances) == 1
    assert _Connection.instances[0].candidate[3] == ("93.184.216.34", 443)


def test_pinned_connection_uses_numeric_sockaddr_and_original_tls_hostname(monkeypatch):
    events = []

    class _Socket:
        def settimeout(self, timeout):
            events.append(("timeout", timeout))

        def connect(self, sockaddr):
            events.append(("connect", sockaddr))

        def close(self):
            events.append(("close",))

    class _TLSContext:
        check_hostname = True
        verify_mode = ssl.CERT_REQUIRED

        def wrap_socket(self, raw, server_hostname):
            events.append(("tls", server_hostname, self.check_hostname, self.verify_mode))
            return raw

    monkeypatch.setattr(external_registry._socket, "socket", lambda *args: _Socket())
    monkeypatch.setattr(
        external_registry._socket,
        "getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("connection must not resolve hostname")),
    )
    monkeypatch.setattr(external_registry._ssl, "create_default_context", lambda: _TLSContext())

    candidate = (PUBLIC_V4[0][0], PUBLIC_V4[0][1], PUBLIC_V4[0][2], PUBLIC_V4[0][4])
    connection = external_registry._PinnedHTTPSConnection(
        "agent.example", candidate, timeout=4
    )
    connection.connect()
    assert ("connect", ("93.184.216.34", 443)) in events
    assert ("tls", "agent.example", True, ssl.CERT_REQUIRED) in events


def test_redirect_to_private_location_is_rejected_without_following(monkeypatch):
    _Connection.responses = {"agent.example": _Response(status=302, raw=b"")}
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V4)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    assert external_registry._read_json("GET", "https://agent.example/card") == (
        302,
        None,
        "redirect_rejected",
    )
    assert len(_Connection.instances) == 1
    assert len(_Connection.instances[0].requests) == 1


def test_registry_redirect_is_rejected_without_following(monkeypatch):
    _Connection.responses = {"api.a2a-registry.org": _Response(status=302, raw=b"")}
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V4)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    assert external_registry._discover_external_agents_resolved("research", 5) == []
    assert len(_Connection.instances) == 1
    assert len(_Connection.instances[0].requests) == 1


def test_registry_mixed_public_private_resolution_is_rejected(monkeypatch):
    monkeypatch.setattr(
        external_registry._socket,
        "getaddrinfo",
        lambda *args, **kwargs: PUBLIC_V4 + PRIVATE_V4,
    )
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    assert external_registry._discover_external_agents_resolved("research", 5) == []
    assert _Connection.instances == []


def test_registry_response_byte_limit_is_enforced(monkeypatch):
    _Connection.responses = {
        "api.a2a-registry.org": _Response(
            raw=b"x" * (external_registry._AION_MAX_EXTERNAL_BYTES + 1)
        )
    }
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V4)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    assert external_registry._discover_external_agents_resolved("research", 5) == []
    assert len(_Connection.instances) == 1


def test_registry_attempts_stop_at_policy_and_request_budget(monkeypatch):
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V4)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)
    budget = external_registry._OutboundBudget(1)

    status, payload, error = external_registry._read_json(
        "GET",
        external_registry.A2A_REGISTRY_SEARCH,
        budget=budget,
    )
    assert status is None
    assert payload is None
    assert error.startswith("KeyError:")
    assert len(_Connection.instances) == 1
    assert budget.used == 1


def test_manifest_and_interaction_destinations_are_validated_independently(monkeypatch):
    manifest = "https://manifest.example/card"
    interaction = "https://interaction.example/a2a/v1"
    card = {
        "name": "External Agent",
        "supportedInterfaces": [
            {"url": interaction, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
    }
    _Connection.responses = {"manifest.example": _Response(payload=card)}

    def resolve(hostname, *args, **kwargs):
        return PUBLIC_V4 if hostname == "manifest.example" else PRIVATE_V4

    monkeypatch.setattr(external_registry._socket, "getaddrinfo", resolve)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    result = external_registry._validate_external({"url": manifest, "followable": True})
    assert result["reachable"] is True
    assert result["interaction_success"] is False
    assert result["verified_external_agent"] is False
    assert result["failure_reason"] == "non_public_address:127.0.0.1"
    assert [item.hostname for item in _Connection.instances] == ["manifest.example"]


def test_valid_a2a_declaration_does_not_contact_interaction_url(monkeypatch):
    manifest = "https://manifest.example/card"
    interaction = "https://interaction.example/a2a/v1"
    card = {
        "name": "External Agent",
        "supportedInterfaces": [
            {"url": interaction, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
    }
    _Connection.responses = {"manifest.example": _Response(payload=card)}
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V6)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    result = external_registry._validate_external({"url": manifest, "followable": True})
    assert result["manifest_reachable"] is True
    assert result["card_parseable"] is True
    assert result["declared_a2a_v1_jsonrpc"] is True
    assert result["interaction_url_validated"] is True
    assert result["interaction_contacted"] is False
    assert result["interaction_success"] is False
    assert result["callable"] is False
    assert result["verified_outcome"] is False
    assert result["evidence_state"] == "reachable_a2a_v1_declaration"
    assert [connection.hostname for connection in _Connection.instances] == ["manifest.example"]
    assert _Connection.instances[0].candidate[0] == socket.AF_INET6
    assert _Connection.instances[0].candidate[3] == ("2606:4700:4700::1111", 443, 0, 0)
    assert _Connection.instances[0].requests[0][0] == "GET"


def test_external_response_size_limit_is_preserved(monkeypatch):
    _Connection.responses = {
        "agent.example": _Response(raw=b"x" * (external_registry._AION_MAX_EXTERNAL_BYTES + 1))
    }
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V4)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)
    assert external_registry._read_json("GET", "https://agent.example/card") == (
        200,
        None,
        "response_too_large",
    )


def test_validation_cache_has_bounded_lru_eviction_and_expiry(monkeypatch):
    monkeypatch.setattr(external_registry, "_AION_VALIDATION_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(external_registry, "_AION_VALIDATION_TTL", 10)
    external_registry._cache_put("one", {"value": 1}, 100)
    external_registry._cache_put("two", {"value": 2}, 100)
    assert external_registry._cache_get("one", 101) == {"value": 1}
    external_registry._cache_put("three", {"value": 3}, 102)

    assert list(external_registry._AION_VALIDATION_CACHE) == ["one", "three"]
    assert external_registry._cache_get("one", 110) is None
    assert external_registry._cache_get("three", 111) == {"value": 3}
    assert external_registry._cache_get("three", 112) is None


def test_per_request_outbound_budget_stops_excess_work(monkeypatch):
    calls = []

    def resolved(query, limit, budget):
        calls.append(("registry", query, limit))
        budget.consume(1)
        return [{"url": f"https://agent-{index}.example/card"} for index in range(3)]

    def validate(row, budget):
        calls.append(("card", row["url"]))
        budget.consume(1)
        return dict(row)

    monkeypatch.setattr(external_registry, "_AION_OUTBOUND_ATTEMPT_BUDGET", 2)
    monkeypatch.setattr(external_registry, "_AION_RESOLVED_DISCOVER", resolved)
    monkeypatch.setattr(external_registry, "_validate_external", validate)

    results = external_registry.discover_external_agents("research", 5)
    assert len(results) == 1
    assert calls == [
        ("registry", "research", 5),
        ("card", "https://agent-0.example/card"),
    ]
    assert results[0]["resource_bounds"]["outbound_attempts_used"] == 2


@pytest.mark.parametrize("query", ["", "   ", "bad\nquery", "x" * 129, None, 123])
def test_invalid_or_oversized_query_performs_no_outbound_work(monkeypatch, query):
    monkeypatch.setattr(
        external_registry,
        "_AION_RESOLVED_DISCOVER",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    assert external_registry.discover_external_agents(query, 5) == []


def test_process_local_discovery_rate_guard_is_bounded(monkeypatch):
    monkeypatch.setattr(external_registry, "_AION_DISCOVERY_RATE_LIMIT", 2)
    monkeypatch.setattr(external_registry, "_AION_DISCOVERY_RATE_WINDOW_SECONDS", 60)

    assert external_registry._allow_discovery(100) is True
    assert external_registry._allow_discovery(101) is True
    assert external_registry._allow_discovery(102) is False
    assert external_registry._allow_discovery(161) is True
