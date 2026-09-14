from app.services import bounty_market, safe_http


def _ok_result(payload):
    return safe_http.FetchResult(status=200, body=b"{}", error=None, attempts=1), payload


def test_missing_key_fails_closed_without_network(monkeypatch):
    monkeypatch.delenv("BOUNTY_AGENT_API_KEY", raising=False)

    def unexpected(*args, **kwargs):
        raise AssertionError("network must not be called without configuration")

    monkeypatch.setattr(safe_http, "fetch_json", unexpected)
    result = bounty_market.list_bounties()

    assert result.status == "not_configured"
    assert result.failure_class == "not_configured"
    assert result.results == []
    assert result.resource_bounds["write_operations_enabled"] is False
    assert result.resource_bounds["claim_enabled"] is False
    assert result.resource_bounds["submission_enabled"] is False
    assert result.resource_bounds["payment_enabled"] is False


def test_list_bounties_is_get_only_fixed_host_and_normalized(monkeypatch):
    monkeypatch.setenv("BOUNTY_AGENT_API_KEY", "operator-test")
    captured = {}

    def fake_fetch(method, url, *, payload=None, headers=None, policy=None, connection_factory=None):
        captured.update(
            method=method,
            url=url,
            payload=payload,
            headers=headers,
            policy=policy,
        )
        return _ok_result(
            {
                "bounties": [
                    {
                        "_id": "bounty_123",
                        "title": "Evidence-backed API research",
                        "description": "Find and verify a public API route.",
                        "verification": "Cite reachable evidence.",
                        "category": "research",
                        "tags": ["api", "verification"],
                        "amount_cents": 2500,
                        "currency": "USD",
                        "version": 3,
                        "status": "open",
                        "delivery_window_ms": 3_600_000,
                        "expires_at": 1_800_000_000,
                        "created_at": 1_700_000_000,
                        "updated_at": 1_700_000_100,
                        "private_internal": "must-not-leak",
                    }
                ],
                "next_cursor": "next-page",
                "is_done": False,
            }
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch)
    result = bounty_market.list_bounties(cursor="page-1")

    assert captured["method"] == "GET"
    assert captured["url"] == "https://api.trybounty.ai/v1/agent/bounties?cursor=page-1"
    assert captured["payload"] is None
    assert captured["headers"] == {"Authorization": "Bearer operator-test"}
    assert captured["policy"].max_attempts == 1
    assert captured["policy"].max_response_bytes == bounty_market.MAX_RESPONSE_BYTES
    assert result.status == "success"
    assert result.next_cursor == "next-page"
    assert result.results == [
        {
            "provider": "bounty",
            "bounty_id": "bounty_123",
            "title": "Evidence-backed API research",
            "description": "Find and verify a public API route.",
            "verification": "Cite reachable evidence.",
            "category": "research",
            "tags": ["api", "verification"],
            "amount_cents": 2500,
            "currency": "USD",
            "version": 3,
            "status": "open",
            "delivery_window_ms": 3_600_000,
            "expires_at": 1_800_000_000,
            "created_at": 1_700_000_000,
            "updated_at": 1_700_000_100,
        }
    ]
    assert "private_internal" not in result.results[0]


def test_get_bounty_rejects_path_injection_without_network(monkeypatch):
    monkeypatch.setenv("BOUNTY_AGENT_API_KEY", "operator-test")

    def unexpected(*args, **kwargs):
        raise AssertionError("network must not be called for an invalid id")

    monkeypatch.setattr(safe_http, "fetch_json", unexpected)
    result = bounty_market.get_bounty("../claim")

    assert result.status == "invalid_request"
    assert result.failure_class == "invalid_bounty_id"


def test_release_events_only_surface_bounty_available(monkeypatch):
    monkeypatch.setenv("BOUNTY_AGENT_API_KEY", "operator-test")

    def fake_fetch(method, url, *, payload=None, headers=None, policy=None, connection_factory=None):
        assert method == "GET"
        assert url == "https://api.trybounty.ai/v1/agent/events?limit=25"
        return _ok_result(
            {
                "events": [
                    {
                        "id": "evt_1",
                        "version": 1,
                        "occurredAt": "2026-09-14T12:00:00Z",
                        "type": "bounty.available",
                        "data": {
                            "bounty_id": "bounty_abc",
                            "bounty_version": 2,
                            "reason": "manual_release",
                            "title": "Research one MCP route",
                            "secret_note": "drop-me",
                        },
                    },
                    {
                        "id": "evt_2",
                        "version": 1,
                        "occurredAt": "2026-09-14T12:01:00Z",
                        "type": "work.completed",
                        "data": {"bounty_id": "bounty_other"},
                    },
                ],
                "next_cursor": "evt-cursor",
                "has_more": True,
            }
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch)
    result = bounty_market.list_release_events(limit=25)

    assert result.status == "success"
    assert result.next_cursor == "evt-cursor"
    assert result.results == [
        {
            "provider": "bounty",
            "event_type": "bounty.available",
            "event_id": "evt_1",
            "occurred_at": "2026-09-14T12:00:00Z",
            "bounty_id": "bounty_abc",
            "bounty_version": 2,
            "reason": "manual_release",
            "title": "Research one MCP route",
        }
    ]


def test_provider_error_never_returns_api_key(monkeypatch):
    monkeypatch.setenv("BOUNTY_AGENT_API_KEY", "operator-test")

    def fake_fetch(method, url, *, payload=None, headers=None, policy=None, connection_factory=None):
        return (
            safe_http.FetchResult(
                status=401,
                body=None,
                error="http_401",
                attempts=1,
            ),
            None,
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch)
    result = bounty_market.list_bounties()

    assert result.status == "authentication_required"
    assert "operator-test" not in repr(result)


def test_malformed_remote_bounty_is_dropped(monkeypatch):
    monkeypatch.setenv("BOUNTY_AGENT_API_KEY", "operator-test")

    def fake_fetch(method, url, *, payload=None, headers=None, policy=None, connection_factory=None):
        return _ok_result(
            {
                "bounties": [
                    {
                        "_id": "bounty_1",
                        "title": "Bad price",
                        "category": "research",
                        "tags": [],
                        "amount_cents": -1,
                        "currency": "USD",
                        "version": 1,
                        "status": "open",
                    },
                    {
                        "_id": "bounty_2",
                        "title": "Unknown state",
                        "category": "research",
                        "tags": [],
                        "amount_cents": 100,
                        "currency": "USD",
                        "version": 1,
                        "status": "mystery",
                    },
                ],
                "next_cursor": "",
                "is_done": True,
            }
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch)
    result = bounty_market.list_bounties()

    assert result.status == "success"
    assert result.results == []
