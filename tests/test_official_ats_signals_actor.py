"""Offline regression tests for the proposed market-listed Apify product."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from products.official_ats_signals.collector import collect, normalize, source_url


def test_first_run_input_schema_uses_known_bounded_public_board():
    path = Path(__file__).parents[1] / "products" / "official_ats_signals" / ".actor" / "input_schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    defaults = schema["properties"]["boards"]["default"]
    assert defaults == [{"provider": "greenhouse", "slug": "greenhouse"}]
    assert source_url(defaults[0]["provider"], defaults[0]["slug"]) == (
        "https://boards-api.greenhouse.io/v1/boards/greenhouse/jobs"
    )


def test_source_urls_are_fixed_allowlisted_hosts():
    assert source_url("greenhouse", "example") == "https://boards-api.greenhouse.io/v1/boards/example/jobs"
    assert source_url("lever", "example").startswith("https://api.lever.co/v0/postings/example")
    assert source_url("ashby", "Example").startswith("https://api.ashbyhq.com/posting-api/job-board/Example")
    for provider, slug in [
        ("custom", "x"), ("greenhouse", "https://127.0.0.1"), ("ashby", "../admin"),
        ("lever", "a?token=secret"), ("greenhouse", ""), (None, "some-company"),
    ]:
        with pytest.raises(ValueError):
            source_url(provider, slug)


def test_greenhouse_normalizes_only_public_sourced_fields():
    payload = {"jobs": [
        {"id": 11, "title": "API Integration Engineer", "absolute_url": "https://boards.greenhouse.io/jobs/11",
         "location": {"name": "Remote"}, "updated_at": "2026-10-08T00:00:00Z",
         "departments": [{"name": "Engineering"}]},
        {"id": 12, "title": "Fake", "absolute_url": "javascript:alert(1)"},
    ]}
    rows = normalize("greenhouse", "example", payload)
    assert len(rows) == 1
    assert rows[0]["department"] == "Engineering"
    assert rows[0]["published_at"] is None  # updated != first posted time
    assert rows[0]["evidence"] == "public_official_ats_listing"


def test_ashby_respects_hidden_jobs_and_explicit_compensation():
    rows = normalize("ashby", "corp", {"jobs": [
        {"id": "a1", "title": "AI Engineer", "jobUrl": "https://jobs.ashbyhq.com/corp/a1",
         "location": "Remote", "compensation": "$120k-$180k", "isListed": True},
        {"id": "a2", "title": "Hidden Role", "jobUrl": "https://jobs.ashbyhq.com/corp/a2",
         "isListed": False},
    ]})
    assert len(rows) == 1
    assert rows[0]["compensation_as_published"] == "$120k-$180k"


def test_hidden_ashby_compensation_is_never_exposed():
    public_url = "https://jobs.ashbyhq.com/corp/role"
    rows = normalize("ashby", "corp", {"jobs": [
        {"id": "hidden", "title": "Staff Engineer", "jobUrl": public_url,
         "shouldDisplayCompensationOnJobPostings": False,
         "compensation": {"compensationTierSummary": "$1000k secret"}},
        {"id": "public", "title": "Staff Engineer", "jobUrl": public_url + "/public",
         "shouldDisplayCompensationOnJobPostings": True,
         "compensation": {"compensationTierSummary": "$150k public",
                          "compensationTiers": [{"confidential": "do-not-publish"}]}},
    ]})
    assert rows[0]["compensation_as_published"] is None
    assert rows[1]["compensation_as_published"] == "$150k public"
    assert "do-not-publish" not in str(rows)


def test_lever_uses_published_postings_without_claiming_accepted_application():
    rows = normalize("lever", "corp", [{
        "id": "123", "text": "Senior Data Engineer",
        "hostedUrl": "https://jobs.lever.co/corp/123",
        "createdAt": 1760000000000,
        "categories": {"location": "Remote", "team": "Data"},
    }])
    assert rows[0]["title"] == "Senior Data Engineer"
    assert rows[0]["published_at"] == 1760000000000
    assert "application" not in rows[0]["evidence"]


def test_bounded_5_board_calls_and_deduplicated_filtered_results():
    called = []
    fixture = {"jobs": [
        {"id": 1, "title": "ML Engineer", "absolute_url": "https://boards.greenhouse.io/jobs/1"},
        {"id": 1, "title": "ML Engineer", "absolute_url": "https://boards.greenhouse.io/jobs/1"},
        {"id": 2, "title": "Office Manager", "absolute_url": "https://boards.greenhouse.io/jobs/2"},
    ]}
    def fake_fetch(url):
        called.append(url)
        return fixture
    result = collect([{"provider": "greenhouse", "slug": "company"}] * 5,
                     title_keywords=["engineer"], max_results=20, fetch=fake_fetch)
    assert len(called) == 5
    assert result["results"] == 1
    assert result["jobs"][0]["title"] == "ML Engineer"
    assert result["limits"]["max_boards"] == 5


def test_invalid_input_fails_before_network():
    calls = []
    def fake_fetch(url):
        calls.append(url)
        return {}
    with pytest.raises(ValueError):
        collect([{"provider": "greenhouse", "slug": "../internal"}], fetch=fake_fetch)
    with pytest.raises(ValueError):
        collect([{"provider": "ashby", "slug": "valid"}] * 6, fetch=fake_fetch)
    with pytest.raises(ValueError):
        collect([{"provider": "ashby", "slug": "valid"}], max_results=10_000, fetch=fake_fetch)
    assert calls == []


def test_failed_source_is_reported_without_fake_jobs():
    def fake_fetch(url):
        raise RuntimeError("official_ats_source_unavailable")
    result = collect([{"provider": "greenhouse", "slug": "corp"}], fetch=fake_fetch)
    assert result["results"] == 0
    assert result["errors"][0]["reason"] == "official_ats_source_unavailable"


@pytest.mark.parametrize(
    ("charged_count", "limit_reached_after_charge", "expected_status", "should_deliver"),
    [
        (1, True, "fulfilled", True),
        (0, False, "payment_not_charged", False),
    ],
)
def test_paid_actor_delivers_iff_one_charge_succeeded(
    monkeypatch, charged_count, limit_reached_after_charge, expected_status, should_deliver
):
    """A one-order buyer can exhaust their budget AFTER paying: deliver anyway."""
    actor_dir = Path(__file__).parents[1] / "products" / "official_ats_signals"

    class FakeActor:
        def __init__(self):
            self.pushed = []
            self.values = {}
            self.log = SimpleNamespace(error=lambda *args: None)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get_input(self):
            return {"boards": [{"provider": "greenhouse", "slug": "greenhouse"}]}

        async def charge(self, *, event_name):
            assert event_name == "verified-batch"
            return SimpleNamespace(
                charged_count=charged_count,
                event_charge_limit_reached=limit_reached_after_charge,
            )

        async def push_data(self, rows):
            self.pushed.extend(rows)

        async def set_value(self, key, value):
            self.values[key] = value

    fake_actor = FakeActor()
    monkeypatch.setitem(sys.modules, "apify", SimpleNamespace(Actor=fake_actor))
    monkeypatch.syspath_prepend(str(actor_dir))
    monkeypatch.setenv("AION_HIRING_PPE_ENABLED", "1")
    spec = importlib.util.spec_from_file_location("ats_actor_payment_test", actor_dir / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "collect", lambda *args, **kwargs: {
        "jobs": [{"title": "Published Engineer", "evidence": "public_official_ats_listing"}],
        "results": 1,
        "boards_checked": 1,
        "retrieved_at": "2026-10-09T00:00:00Z",
        "errors": [],
    })
    asyncio.run(module.main())
    assert fake_actor.values["OUTPUT"]["status"] == expected_status
    assert bool(fake_actor.pushed) is should_deliver
