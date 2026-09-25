from __future__ import annotations

from app.services import acquisition_swarm, ambassador, moltbook_acquisition, safe_http


def test_moltbook_search_is_pinned_to_official_www_origin(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    seen = {}

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["headers"] = dict(headers or {})
        seen["retain_http_error_json"] = kwargs.get("retain_http_error_json")
        return (
            safe_http.FetchResult(200, b"{}", None, 1),
            {
                "success": True,
                "results": [
                    {
                        "type": "post",
                        "id": "post-123",
                        "author": {"name": "BuyerBot"},
                        "title": "Need a paid browser provider",
                    }
                ],
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)

    result = moltbook_acquisition.search_intent(
        "I need a paid browser provider",
        5,
    )

    assert result["status"] == "success"
    assert seen["method"] == "GET"
    assert seen["url"].startswith(
        "https://www.moltbook.com/api/v1/search?"
    )
    assert "moltbook.com/api/v1" in seen["url"]
    assert "type=all" in seen["url"]
    assert seen["headers"]["Authorization"] == "Bearer moltbook_test_secret"
    assert seen["retain_http_error_json"] is True
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["source"] == "moltbook"
    assert candidate["identifier"] == "moltbook:BuyerBot"
    assert candidate["interaction_url"] == (
        "https://www.moltbook.com/api/v1/posts/post-123/comments"
    )


def test_moltbook_semantic_search_filters_topical_non_buyer_matches(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        return (
            safe_http.FetchResult(200, b"{}", None, 1),
            {
                "success": True,
                "results": [
                    {
                        "type": "post",
                        "id": "post-chat",
                        "author": {"name": "ChatterBot"},
                        "title": "Browser agents are interesting",
                        "content": "A general discussion of automation trends.",
                    },
                    {
                        "type": "post",
                        "id": "post-buy",
                        "author": {"name": "BuyerBot"},
                        "title": "Need a paid browser automation API",
                        "content": "Looking for a reliable provider before we spend.",
                    },
                ],
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result = moltbook_acquisition.search_intent("browser automation provider", 5)

    assert [row["identifier"] for row in result["candidates"]] == [
        "moltbook:BuyerBot"
    ]


def test_moltbook_semantic_search_rejects_commercial_discussion_without_buyer_request(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        return (
            safe_http.FetchResult(200, b"{}", None, 1),
            {
                "success": True,
                "results": [
                    {
                        "type": "comment",
                        "id": "comment-discussion",
                        "post_id": "post-discussion",
                        "author": {"name": "DiscussionBot"},
                        "content": (
                            "The cost of agent API decay is real. Paid monitoring "
                            "services can help teams understand the problem."
                        ),
                    },
                    {
                        "type": "comment",
                        "id": "comment-buyer",
                        "post_id": "post-buyer",
                        "author": {"name": "BuyerBot"},
                        "content": (
                            "I need a paid monitoring API and I am looking for a "
                            "reliable provider before we spend."
                        ),
                    },
                ],
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result = moltbook_acquisition.search_intent("paid monitoring provider", 5)

    assert [row["identifier"] for row in result["candidates"]] == [
        "moltbook:BuyerBot"
    ]


def test_moltbook_semantic_search_discovers_buyer_intent_in_comments(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        return (
            safe_http.FetchResult(200, b"{}", None, 1),
            {
                "success": True,
                "results": [
                    {
                        "type": "comment",
                        "id": "comment-funded-buyer",
                        "post_id": "post-buyer-thread",
                        "author": {"name": "FundedBuyer"},
                        "content": (
                            "I have a funded wallet on Base and I am looking to buy "
                            "small API services over x402."
                        ),
                    },
                    {
                        "type": "agent",
                        "id": "agent-seller",
                        "name": "SellerProfile",
                        "description": "I sell paid API services.",
                    },
                ],
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result = moltbook_acquisition.search_intent("buy paid API with x402", 5)

    assert [row["identifier"] for row in result["candidates"]] == [
        "moltbook:FundedBuyer"
    ]
    candidate = result["candidates"][0]
    assert candidate["url"] == (
        "https://www.moltbook.com/post/post-buyer-thread"
    )
    assert candidate["interaction_url"] == (
        "https://www.moltbook.com/api/v1/posts/post-buyer-thread/comments"
    )
    assert result["resource_bounds"]["search_type"] == "all"


def test_moltbook_recent_global_scan_filters_for_real_spend_intent(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    seen = {}

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen["method"] = method
        seen["url"] = url
        return (
            safe_http.FetchResult(200, b"{}", None, 1),
            {
                "posts": [
                    {
                        "type": "post",
                        "id": "post-buy",
                        "author": {"name": "BuyerBot"},
                        "title": "Need a paid browser automation API",
                        "content": "Looking for a reliable provider before we spend.",
                    },
                    {
                        "type": "post",
                        "id": "post-chat",
                        "author": {"name": "ChatterBot"},
                        "title": "Hello Moltbook",
                        "content": "Just sharing a thought about agents today.",
                    },
                    {
                        "type": "post",
                        "id": "post-self",
                        "author": {"name": "aion_temple_herald"},
                        "title": "Need a paid API",
                        "content": "Self content must never become a target.",
                    },
                ]
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result = moltbook_acquisition.browse_recent_intent(15)

    assert result["status"] == "success"
    assert seen["method"] == "GET"
    assert (
        seen["url"]
        == "https://www.moltbook.com/api/v1/posts?sort=new&limit=15"
    )
    assert [row["identifier"] for row in result["candidates"]] == [
        "moltbook:BuyerBot"
    ]
    assert (
        result["candidates"][0]["evidence_state"]
        == "recent_global_public_intent_match"
    )
    assert result["resource_bounds"]["recent_posts_scanned"] == 3


def test_moltbook_semantic_query_and_recent_scan_lane_rotate_each_cycle():
    bank = acquisition_swarm.MOLTBOOK_INTENT_QUERIES["paid_api_buyers"]
    q0 = acquisition_swarm._moltbook_query_for_cycle(
        "paid_api_buyers",
        bank,
        now_seconds=0,
    )
    q1 = acquisition_swarm._moltbook_query_for_cycle(
        "paid_api_buyers",
        bank,
        now_seconds=acquisition_swarm.DEFAULT_INTERVAL_SECONDS,
    )

    assert q0 != q1
    lane0 = acquisition_swarm._recent_global_scan_lane(now_seconds=0)
    lane1 = acquisition_swarm._recent_global_scan_lane(
        now_seconds=acquisition_swarm.DEFAULT_INTERVAL_SECONDS
    )
    assert lane0 != lane1
    assert lane0 in acquisition_swarm.INTENT_WORKERS
    assert lane1 in acquisition_swarm.INTENT_WORKERS


def test_moltbook_adapter_never_accepts_arbitrary_request_origin(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    called = False

    def fail_fetch(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("network must not be called")

    monkeypatch.setattr(safe_http, "fetch_json", fail_fetch)
    result, payload = moltbook_acquisition._request_json(
        "GET",
        "https://evil.example/steal",
    )

    assert payload is None
    assert result.error == "invalid_moltbook_path"
    assert called is False


def test_moltbook_outreach_leads_with_buyer_invoked_zero_cost_preflight():
    text = moltbook_acquisition.build_outreach_comment(
        public_base_url="https://aion.example",
        preflight_decision="GO",
    )

    assert "commercial/route-intelligence/preflight" in text
    assert "run your own free AION preflight now" in text
    assert "zero-cost preflight for this intent category: GO" not in text
    assert "A2A action pre_spend_preflight" in text
    assert "MCP tool pre_spend_preflight" in text
    assert "JSON field named need" in text
    assert "set it to the exact need from this thread" in text
    assert "<exact need" not in text
    assert '{"need":" "}' not in text
    assert "no membership" in text
    assert "If GO, follow next_action" in text
    assert len(text) <= moltbook_acquisition.MAX_COMMENT_CHARS


def test_moltbook_target_has_separate_non_a2a_qualification(monkeypatch):
    monkeypatch.setattr(
        ambassador,
        "canonical_aion_public_base_url",
        lambda: "https://aion.example",
    )
    state, reasons = ambassador._qualification(
        {
            "source": "moltbook",
            "identifier": "moltbook:BuyerBot",
            "interaction_url": (
                "https://www.moltbook.com/api/v1/posts/post-123/comments"
            ),
            "interaction_url_validated": True,
            "authentication_requirement": "moltbook_bearer",
            "payment_required": False,
            "manifest_reachable": False,
            "declared_a2a_v1_jsonrpc": False,
        }
    )

    assert state == "qualified"
    assert reasons == ["qualified_moltbook_public_intent_thread"]


def test_moltbook_contact_budget_stays_bounded_inside_multichannel_swarm():
    assert set(acquisition_swarm.MOLTBOOK_INTENT_QUERIES) == set(
        acquisition_swarm.INTENT_WORKERS
    )
    assert len(acquisition_swarm.INTENT_WORKERS) == 15
    assert set(acquisition_swarm.INTENT_WORKERS).issubset(
        moltbook_acquisition._INTENT_LABELS
    )
    assert acquisition_swarm.MOLTBOOK_DAILY_COMMENT_LIMIT == 50
    assert acquisition_swarm.MOLTBOOK_MAX_COMMENTS_PER_CYCLE == 2
    assert acquisition_swarm.MOLTBOOK_DM_DAILY_REQUEST_LIMIT == 20
    assert acquisition_swarm.MOLTBOOK_DM_MAX_REQUESTS_PER_CYCLE == 2


def test_moltbook_policy_allows_official_cdn_dns_fanout_within_global_bound():
    policy = moltbook_acquisition._policy()

    assert policy.max_resolved_addresses == 32
    assert policy.max_attempts == 1


def test_moltbook_candidate_uses_expanded_url_validation_only_for_moltbook(monkeypatch):
    calls = []

    def fake_canonical(value, *, max_addresses=4):
        calls.append((value, max_addresses))
        return value

    class FakeDB:
        def scalar(self, statement):
            return object()

    monkeypatch.setattr(ambassador, "_canonical_public_url", fake_canonical)
    row, outcome = ambassador._insert_candidate(
        FakeDB(),
        object(),
        {
            "source": "moltbook",
            "identifier": "moltbook:BuyerBot",
            "url": "https://www.moltbook.com/post/post-123",
            "interaction_url": (
                "https://www.moltbook.com/api/v1/posts/post-123/comments"
            ),
        },
    )

    assert outcome == "duplicate_target_fingerprint"
    assert row is not None
    assert calls == [
        ("https://www.moltbook.com/post/post-123", 32),
        ("https://www.moltbook.com/api/v1/posts/post-123/comments", 32),
    ]


def test_moltbook_dm_request_is_consent_based_and_official_origin_only(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    monkeypatch.setenv("AION_MOLTBOOK_DM_ENABLED", "1")
    seen = {}

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["payload"] = payload
        seen["headers"] = dict(headers or {})
        return safe_http.FetchResult(201, b"{}", None, 1), {"success": True}

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result = moltbook_acquisition.dm_request(
        "BuyerBot",
        "AION can run a free pre-spend check before an external purchase.",
    )

    assert result["accepted"] is True
    assert seen["method"] == "POST"
    assert seen["url"] == "https://www.moltbook.com/api/v1/agents/dm/request"
    assert seen["payload"]["to"] == "BuyerBot"
    assert seen["headers"]["Authorization"] == "Bearer moltbook_test_secret"


def test_moltbook_dm_request_rejects_self_or_unbounded_message(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    monkeypatch.setenv("AION_MOLTBOOK_DM_ENABLED", "1")

    assert moltbook_acquisition.dm_request(
        "aion-supreme", "this is long enough"
    )["accepted"] is False
    assert moltbook_acquisition.dm_request("BuyerBot", "short")["accepted"] is False


def test_moltbook_platform_error_summary_is_bounded_and_non_secret():
    result = safe_http.FetchResult(403, b"", "http_403", 1)

    summary = moltbook_acquisition.platform_error_summary(
        result,
        {"code": "comment_forbidden", "message": "Commenting is temporarily unavailable"},
    )

    assert summary == (
        "code=comment_forbidden; "
        "message=Commenting is temporarily unavailable"
    )
    assert len(summary) <= 400

    redacted = moltbook_acquisition.platform_error_summary(
        result,
        {"message": "Bearer definitely-not-safe"},
    )
    assert redacted == "redacted_platform_error"


def test_moltbook_comment_pacing_handles_naive_persisted_timestamp():
    from datetime import datetime

    class FakeDB:
        def scalar(self, statement):
            return datetime.utcnow()

    wait = acquisition_swarm._seconds_until_moltbook_comment_allowed(FakeDB())

    assert 0 <= wait <= acquisition_swarm.MOLTBOOK_MIN_COMMENT_INTERVAL_SECONDS


def test_moltbook_comment_pacing_exceeds_official_twenty_second_floor():
    assert acquisition_swarm.MOLTBOOK_MIN_COMMENT_INTERVAL_SECONDS == 21
    assert acquisition_swarm.MOLTBOOK_MIN_COMMENT_INTERVAL_SECONDS > 20


def test_moltbook_missing_secret_is_fail_closed(monkeypatch):
    monkeypatch.delenv("MOLTBOOK_API_KEY", raising=False)

    status = moltbook_acquisition.account_status()

    assert status["configured"] is False
    assert status["claimed"] is False
    assert status["status"] == "not_configured"

def test_moltbook_outreach_is_contextual_per_target_and_intent():
    first = moltbook_acquisition.build_outreach_comment(
        public_base_url="https://aion.example",
        recipient="BuyerAlpha",
        intent="provider_selection",
    )
    second = moltbook_acquisition.build_outreach_comment(
        public_base_url="https://aion.example",
        recipient="BuyerBeta",
        intent="mcp_buyers",
    )

    assert first != second
    assert first.startswith("@BuyerAlpha,")
    assert "provider-selection decision" in first
    assert second.startswith("@BuyerBeta,")
    assert "paid MCP-tool decision" in second
    assert "commercial/route-intelligence/preflight" in first
    assert "commercial/route-intelligence/preflight" in second
    assert "A2A action pre_spend_preflight" in first
    assert "MCP tool pre_spend_preflight" in second
    assert "exact need stated in this thread" in first
    assert "will not contact this target again" in first
    assert len(first) <= moltbook_acquisition.MAX_COMMENT_CHARS
    assert len(second) <= moltbook_acquisition.MAX_COMMENT_CHARS


def test_moltbook_suspension_stops_writes_but_keeps_read_discovery(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    moltbook_acquisition._SUSPENDED_UNTIL = None
    seen = []

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen.append((method, url))
        return safe_http.FetchResult(200, b"{}", None, 1), {"results": []}

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    until = (
        datetime.now(timezone.utc) + timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")
    moltbook_acquisition._note_suspension(
        {"error": "Forbidden", "message": f"Agent is suspended until {until}. Reason: duplicate_comment"}
    )

    status = moltbook_acquisition.outbound_status()
    assert status["suspended"] is True
    assert status["suspended_until"] is not None

    write_result, write_payload = moltbook_acquisition._request_json(
        "POST",
        "/posts/post-123/comments",
        payload={"content": "bounded outreach"},
    )
    assert write_result.error == "moltbook_suspended"
    assert write_result.attempts == 0
    assert write_payload["suspended_until"] == status["suspended_until"]
    assert seen == []

    read_result, _ = moltbook_acquisition._request_json(
        "GET",
        "/search",
        params={"q": "paid api", "type": "posts", "limit": 1},
    )
    assert read_result.status == 200
    assert len(seen) == 1
    assert seen[0][0] == "GET"

    moltbook_acquisition._SUSPENDED_UNTIL = None


def test_moltbook_403_records_platform_suspension(monkeypatch):
    from datetime import datetime, timedelta, timezone

    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    moltbook_acquisition._SUSPENDED_UNTIL = None
    until = (
        datetime.now(timezone.utc) + timedelta(hours=2)
    ).isoformat().replace("+00:00", "Z")

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        return (
            safe_http.FetchResult(403, b"", "http_403", 1),
            {
                "error": "Forbidden",
                "message": f"Agent is suspended until {until}. Reason: duplicate_comment",
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result, _ = moltbook_acquisition.post_comment(
        "https://www.moltbook.com/api/v1/posts/post-123/comments",
        "AION-operated contextual outreach",
    )

    assert result.status == 403
    assert moltbook_acquisition.outbound_status()["suspended"] is True
    moltbook_acquisition._SUSPENDED_UNTIL = None

def test_moltbook_dm_is_fail_closed_until_verified_endpoint(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    monkeypatch.delenv("AION_MOLTBOOK_DM_ENABLED", raising=False)
    called = False

    def fail_fetch(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("disabled DM must not call the network")

    monkeypatch.setattr(safe_http, "fetch_json", fail_fetch)
    result = moltbook_acquisition.dm_request(
        "BuyerBot",
        "AION can run a free pre-spend check before an external purchase.",
    )

    assert result["accepted"] is False
    assert result["error"] == "moltbook_dm_disabled"
    assert result["http_status"] is None
    assert called is False

