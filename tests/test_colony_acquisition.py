from __future__ import annotations

from app.services import (
    acquisition_swarm,
    ambassador,
    colony_acquisition,
    safe_http,
)


def test_colony_public_search_is_read_only_and_pinned_to_official_origin(monkeypatch):
    monkeypatch.delenv("COLONY_API_KEY", raising=False)
    seen = {}

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["headers"] = dict(headers or {})
        return (
            safe_http.FetchResult(200, b"{}", None, 1),
            {
                "posts": [
                    {
                        "type": "post",
                        "id": "seller-123",
                        "author": {"username": "SellerBot"},
                        "title": "For hire: paid browser automation",
                        "body": "What I sell: browser automation services.",
                        "tags": ["for-hire"],
                    },
                    {
                        "type": "post",
                        "id": "post-123",
                        "author": {"username": "BuyerBot"},
                        "title": "Need a paid browser provider",
                        "body": "Looking for a provider for a current workflow.",
                    },
                ]
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result = colony_acquisition.search_intent("paid browser provider", 5)

    assert result["status"] == "success"
    assert seen["method"] == "GET"
    assert seen["url"].startswith("https://thecolony.ai/api/v1/search?")
    assert seen["headers"] == {}
    assert result["resource_bounds"]["demand_filter"] == "conservative_buyer_intent"
    assert result["resource_bounds"]["filtered_supply_like"] == 1
    assert [row["identifier"] for row in result["candidates"]] == [
        "colony:BuyerBot"
    ]
    assert result["candidates"][0]["evidence_state"] == (
        "colony_public_agent_buyer_intent_match"
    )
    assert result["candidates"][0]["interaction_url"] == (
        "https://thecolony.ai/api/v1/posts/post-123/comments"
    )


def test_colony_paid_task_discovery_keeps_buyer_demand_and_rejects_for_hire(monkeypatch):
    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        assert method == "GET"
        assert "/api/v1/marketplace/tasks?" in url
        assert "sort=budget" in url
        return (
            safe_http.FetchResult(200, b"{}", None, 1),
            {
                "items": [
                    {
                        "id": "seller-1",
                        "author": {"username": "SellerBot"},
                        "title": "For hire: API audits and research",
                        "body": "What I sell: fixed-price agent services.",
                        "tags": ["for-hire"],
                        "accepting_submissions": True,
                    },
                    {
                        "id": "task-1",
                        "author": {"username": "TaskBuyer"},
                        "title": "Need an agent to verify an integration",
                        "body": "Looking for an agent. Please submit your bids with approach.",
                        "metadata_": {
                            "budget_min_sats": 1000,
                            "budget_max_sats": 5000,
                            "deadline": "2026-12-01T00:00:00Z",
                        },
                        "accepting_submissions": True,
                    },
                ]
            },
        )

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result = colony_acquisition.browse_paid_tasks(5)

    assert result["status"] == "success"
    assert result["resource_bounds"]["surface"] == "marketplace_tasks"
    assert result["resource_bounds"]["demand_filter"] == "conservative_buyer_intent"
    assert result["resource_bounds"]["filtered_supply_like"] == 1
    assert [row["identifier"] for row in result["candidates"]] == [
        "colony:TaskBuyer"
    ]
    assert result["candidates"][0]["evidence_state"] == (
        "colony_marketplace_buyer_demand"
    )


def test_colony_demand_filter_fails_closed_on_ambiguous_seller_copy():
    assert colony_acquisition._buyer_demand_task(
        {
            "title": "For hire: data cleanup",
            "body": "Services & pricing. I am available for immediate work.",
            "tags": ["for-hire"],
            "accepting_submissions": True,
        }
    ) is False
    assert colony_acquisition._buyer_demand_task(
        {
            "title": "需要构建情感分析模型",
            "body": "Looking for experts to build a sentiment analysis model. Please submit your bids.",
            "accepting_submissions": True,
        }
    ) is True
    assert colony_acquisition._buyer_demand_task(
        {
            "title": "Potential task",
            "body": "Maybe something useful.",
            "accepting_submissions": True,
        }
    ) is False
    assert colony_acquisition._buyer_demand_task(
        {
            "title": "Need an agent to build a model",
            "body": "Looking for experts. Please submit your bids.",
            "metadata_": {"deadline": "2026-06-20T23:59:59Z"},
            "accepting_submissions": True,
        },
        now=__import__("datetime").datetime(
            2026, 9, 23, tzinfo=__import__("datetime").timezone.utc
        ),
    ) is False
    assert colony_acquisition._buyer_demand_task(
        {
            "title": "Need an agent to build a model",
            "body": "Looking for experts. Please submit your bids.",
            "metadata_": {"deadline": "2026-12-01T00:00:00Z"},
            "accepting_submissions": True,
        },
        now=__import__("datetime").datetime(
            2026, 9, 23, tzinfo=__import__("datetime").timezone.utc
        ),
    ) is True


def test_colony_missing_secret_keeps_discovery_but_fails_write_auth_closed(monkeypatch):
    monkeypatch.delenv("COLONY_API_KEY", raising=False)

    status = colony_acquisition.account_status()

    assert status == {
        "configured": False,
        "authenticated": False,
        "status": "read_only",
        "error": "colony_api_key_missing",
    }


def test_colony_comment_reads_context_and_blocks_existing_aion_comment(monkeypatch):
    monkeypatch.setenv("COLONY_API_KEY", "colony_test_secret")
    seen = []

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen.append((method, url, payload, dict(headers or {})))
        if url.endswith("/auth/token"):
            assert payload == {"api_key": "colony_test_secret"}
            return (
                safe_http.FetchResult(200, b"{}", None, 1),
                {"access_token": "jwt-test"},
            )
        if url.endswith("/posts/post-123/context"):
            assert headers["Authorization"] == "Bearer jwt-test"
            return (
                safe_http.FetchResult(200, b"{}", None, 1),
                {
                    "post": {"id": "post-123", "title": "Need provider"},
                    "comments": [
                        {"author": {"username": "aion-supreme"}, "body": "already here"}
                    ],
                },
            )
        raise AssertionError("existing AION comment must suppress a second write")

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result, payload = colony_acquisition.post_comment(
        "https://thecolony.ai/api/v1/posts/post-123/comments",
        "AION-operated contextual reply",
    )

    assert result.status == 409
    assert result.error == "colony_aion_comment_already_exists"
    assert payload["error"] == "colony_aion_comment_already_exists"
    assert [row[0] for row in seen] == ["POST", "GET"]


def test_colony_comment_posts_only_after_context_read(monkeypatch):
    monkeypatch.setenv("COLONY_API_KEY", "colony_test_secret")
    seen = []

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen.append((method, url, payload, dict(headers or {})))
        if url.endswith("/auth/token"):
            return (
                safe_http.FetchResult(200, b"{}", None, 1),
                {"access_token": "jwt-test"},
            )
        if url.endswith("/posts/post-123/context"):
            return (
                safe_http.FetchResult(200, b"{}", None, 1),
                {
                    "post": {"id": "post-123", "title": "Need provider"},
                    "comments": [],
                },
            )
        if url.endswith("/posts/post-123/comments"):
            assert payload == {"body": "AION-operated contextual reply"}
            return safe_http.FetchResult(201, b"{}", None, 1), {"id": "comment-1"}
        raise AssertionError(url)

    monkeypatch.setattr(safe_http, "fetch_json", fake_fetch_json)
    result, payload = colony_acquisition.post_comment(
        "https://thecolony.ai/api/v1/posts/post-123/comments",
        "AION-operated contextual reply",
    )

    assert result.status == 201
    assert payload["id"] == "comment-1"
    assert [row[0] for row in seen] == ["POST", "GET", "POST"]


def test_colony_target_has_separate_public_thread_qualification(monkeypatch):
    monkeypatch.setattr(
        ambassador,
        "canonical_aion_public_base_url",
        lambda: "https://aion.example",
    )
    state, reasons = ambassador._qualification(
        {
            "source": "colony",
            "identifier": "colony:BuyerBot",
            "interaction_url": (
                "https://thecolony.ai/api/v1/posts/post-123/comments"
            ),
            "interaction_url_validated": True,
            "authentication_requirement": "colony_bearer",
            "payment_required": False,
            "manifest_reachable": False,
            "declared_a2a_v1_jsonrpc": False,
        }
    )

    assert state == "qualified"
    assert reasons == ["qualified_colony_public_intent_thread"]


def test_colony_outreach_is_contextual_and_bounded():
    first = colony_acquisition.build_outreach_comment(
        public_base_url="https://aion.example",
        recipient="BuyerAlpha",
        intent="provider_selection",
    )
    second = colony_acquisition.build_outreach_comment(
        public_base_url="https://aion.example",
        recipient="BuyerBeta",
        intent="mcp_buyers",
    )

    assert first != second
    assert first.startswith("@BuyerAlpha,")
    assert "provider-selection decision" in first
    assert "paid MCP-tool decision" in second
    assert "commercial/route-intelligence/preflight" in first
    assert "will not contact this target again" in first
    assert len(first) <= colony_acquisition.MAX_COMMENT_CHARS


def test_colony_swarm_write_budget_is_conservative_until_platform_limit_is_known():
    assert acquisition_swarm.MAX_COLONY_SCOUT_WORKERS_PER_CYCLE == 5
    assert acquisition_swarm.MAX_COLONY_COMMENTS_PER_CYCLE == 2
    assert acquisition_swarm.MAX_COLONY_COMMENTS_PER_DAY == 20
