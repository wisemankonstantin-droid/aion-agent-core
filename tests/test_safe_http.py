import json
import socket

from app.services import safe_http


PUBLIC = [
    (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))
]


class Response:
    def __init__(self, *, status=200, payload=None, encoding=None):
        self.status = status
        self.raw = json.dumps(payload or {}).encode()
        self.encoding = encoding

    def read(self, limit):
        return self.raw

    def getheader(self, name):
        return self.encoding if name == "Content-Encoding" else None


class Connection:
    response = Response()
    instances = []
    failures = 0

    def __init__(self, hostname, candidate, timeout):
        self.hostname = hostname
        self.candidate = candidate
        self.requests = []
        self.instances.append(self)

    def request(self, method, target, body=None, headers=None):
        self.requests.append((method, target, headers))

    def getresponse(self):
        if self.failures:
            type(self).failures -= 1
            raise TimeoutError("timed out")
        return self.response

    def close(self):
        pass


def _patch(monkeypatch):
    Connection.instances = []
    Connection.failures = 0
    Connection.response = Response(payload={"ok": True})
    monkeypatch.setattr(safe_http._socket, "getaddrinfo", lambda *a, **k: PUBLIC)


def test_fetch_resolves_once_pins_peer_and_preserves_host(monkeypatch):
    _patch(monkeypatch)
    calls = []
    monkeypatch.setattr(
        safe_http._socket,
        "getaddrinfo",
        lambda *a, **k: calls.append(a[0]) or PUBLIC,
    )

    result, payload = safe_http.fetch_json(
        "GET",
        "https://official.example/releases/latest",
        headers={"Host": "attacker.invalid", "Accept-Encoding": "gzip"},
        connection_factory=Connection,
    )

    assert result.error is None and payload == {"ok": True}
    assert calls == ["official.example"]
    assert Connection.instances[0].candidate[3] == ("93.184.216.34", 443)
    headers = Connection.instances[0].requests[0][2]
    assert headers["Host"] == "official.example"
    assert headers["Accept-Encoding"] == "identity"


def test_fetch_preserves_valid_explicit_https_port(monkeypatch):
    _patch(monkeypatch)
    calls = []
    monkeypatch.setattr(
        safe_http._socket,
        "getaddrinfo",
        lambda host, port, **kwargs: calls.append((host, port)) or [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", port))
        ],
    )

    result = safe_http.fetch_bytes(
        "GET", "https://official.example:8443/a2a", connection_factory=Connection
    )

    assert result.error is None
    assert calls == [("official.example", 8443)]
    assert Connection.instances[0].candidate[3] == ("93.184.216.34", 8443)
    assert Connection.instances[0].requests[0][2]["Host"] == "official.example:8443"


def test_retry_count_is_bounded_without_dns_reresolution(monkeypatch):
    _patch(monkeypatch)
    calls = []
    Connection.failures = 2
    monkeypatch.setattr(
        safe_http._socket,
        "getaddrinfo",
        lambda *a, **k: calls.append(a[0]) or PUBLIC,
    )

    result = safe_http.fetch_bytes(
        "GET",
        "https://official.example/data",
        policy=safe_http.FetchPolicy(max_attempts=2),
        connection_factory=Connection,
    )

    assert result.attempts == 2
    assert result.error.startswith("TimeoutError")
    assert calls == ["official.example"]
    assert len(Connection.instances) == 2


def test_redirect_and_compressed_response_are_rejected(monkeypatch):
    _patch(monkeypatch)
    Connection.response = Response(status=302)
    redirected = safe_http.fetch_bytes(
        "GET", "https://official.example/data", connection_factory=Connection
    )
    Connection.response = Response(encoding="gzip")
    compressed = safe_http.fetch_bytes(
        "GET", "https://official.example/data", connection_factory=Connection
    )

    assert redirected.error == "redirect_rejected"
    assert compressed.error == "content_encoding_rejected"


def test_byte_limit_is_enforced(monkeypatch):
    _patch(monkeypatch)
    Connection.response.raw = b"x" * 11

    result = safe_http.fetch_bytes(
        "GET",
        "https://official.example/data",
        policy=safe_http.FetchPolicy(max_response_bytes=10),
        connection_factory=Connection,
    )

    assert result.error == "response_too_large"
