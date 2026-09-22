from __future__ import annotations

from app.services import acquisition_swarm, ambassador, moltbook_acquisition, safe_http


def test_moltbook_search_is_pinned_to_official_www_origin(monkeypatch):
    monkeypatch.setenv("MOLTBOOK_API_KEY", "moltbook_test_secret")
    seen = {}

    def fake_fetch_json(method, url, *, payload=None, headers=None, policy=None, **kwargs):
        seen["method"] = method
        seen["url"] = url
        seen["headers"] = dict(headers or {})
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
    assert seen["headers"]["Authorization"] == "Bearer moltbook_test_secret"
    assert len(result["candidates"]) == 1
    candidate = result["candidates"][0]
    assert candidate["source"] == "moltbook"
    assert candidate["identifier"] == "moltbook:BuyerBot"
    assert candidate["interaction_url"] == (
        "https://www.moltbook.com/api/v1/posts/post-123/comments"
    )


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


def test_moltbook_outreach_leads_with_zero_cost_pre_spend_value():
    text = moltbook_acquisition.build_outreach_comment(
        public_base_url="https://aion.example"
    )

    assert "commercial/route-intelligence/preflight" in text
    assert "zero-cost pre-spend check" in text
    assert "no membership" in text
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


def test_moltbook_is_primary_but_platform_contact_budget_is_hard_bounded():
    assert set(acquisition_swarm.MOLTBOOK_INTENT_QUERIES) == set(
        acquisition_swarm.INTENT_WORKERS
    )
    assert len(acquisition_swarm.INTENT_WORKERS) == 10
    assert acquisition_swarm.MOLTBOOK_DAILY_CONTACT_LIMIT == 40
    assert acquisition_swarm.MOLTBOOK_MAX_CONTACTS_PER_CYCLE == 2


def test_moltbook_policy_allows_official_cdn_dns_fanout_within_global_bound():
    policy = moltbook_acquisition._policy()

    assert policy.max_resolved_addresses == 32
    assert policy.max_attempts == 1


def test_moltbook_missing_secret_is_fail_closed(monkeypatch):
    monkeypatch.delenv("MOLTBOOK_API_KEY", raising=False)

    status = moltbook_acquisition.account_status()

    assert status["configured"] is False
    assert status["claimed"] is False
    assert status["status"] == "not_configured"
