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
def _clear_test_state():
    _Connection.responses = {}
    _Connection.instances = []
    external_registry._AION_VALIDATION_CACHE.clear()


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


def test_ipv6_a2a_handshake_uses_pinned_public_address(monkeypatch):
    response = {"jsonrpc": "2.0", "id": "probe", "result": {"message": {"parts": []}}}
    _Connection.responses = {"interaction.example": _Response(payload=response)}
    monkeypatch.setattr(external_registry._socket, "getaddrinfo", lambda *args, **kwargs: PUBLIC_V6)
    monkeypatch.setattr(external_registry, "_PinnedHTTPSConnection", _Connection)

    ok, status, response_type, error = external_registry._handshake(
        "https://interaction.example/a2a/v1"
    )
    assert (ok, status, response_type, error) == (True, 200, "message", None)
    assert _Connection.instances[0].candidate[0] == socket.AF_INET6
    assert _Connection.instances[0].candidate[3] == ("2606:4700:4700::1111", 443, 0, 0)
    assert _Connection.instances[0].requests[0][3]["Host"] == "interaction.example"


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
