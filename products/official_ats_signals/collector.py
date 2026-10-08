"""Bounded normalization of PUBLIC, company-hosted job postings.

No cross-company crawling, no login, no personal enrichment, no browser/proxies.
A source result is evidence of a public listing, NOT an employer hiring guarantee.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BOARDS = 5
MAX_RESULTS = 100
MAX_RESPONSE_BYTES = 2_000_000
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,74}$")
_PROVIDERS = {"greenhouse", "lever", "ashby"}


def source_url(provider: str, slug: str) -> str:
    """Strictly fixed domains prevent user-controlled URLs / SSRF."""
    if provider not in _PROVIDERS or not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ValueError("unsupported_provider_or_board_slug")
    if provider == "greenhouse":
        return f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    if provider == "lever":
        return f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=100"
    return f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"


def fetch_public_json(url: str) -> object:
    """One bounded GET, without redirects to arbitrary customer-supplied hosts."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "AION-Hiring-Signals/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            # Redirect targets must remain one of the official ATS domains.
            from urllib.parse import urlsplit
            hostname = (urlsplit(response.url).hostname or "").lower()
            if hostname not in {"boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com"}:
                raise ValueError("unexpected_upstream_redirect")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError("official_ats_source_unavailable") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("official_ats_response_too_large")
    try:
        return json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("official_ats_invalid_json") from exc


def _text(value: object, limit: int = 250) -> str:
    return " ".join(str(value or "").split())[:limit]


def _job_url(value: object) -> str | None:
    from urllib.parse import urlsplit
    value = _text(value, 800)
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return value


def normalize(provider: str, slug: str, payload: object) -> list[dict[str, Any]]:
    """Select transparent fields only; never infer contact details or salaries."""
    if provider == "lever":
        rows = payload if isinstance(payload, list) else []
    else:
        rows = payload.get("jobs", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("invalid_vendor_response_shape")
    output: list[dict[str, Any]] = []
    for row in rows[:500]:
        if not isinstance(row, dict):
            continue
        if provider == "greenhouse":
            location = row.get("location") if isinstance(row.get("location"), dict) else {}
            title, location_name = row.get("title"), location.get("name")
            url, job_id = row.get("absolute_url"), row.get("id")
            department = ", ".join(_text(x.get("name"), 70) for x in row.get("departments", []) if isinstance(x, dict)) if isinstance(row.get("departments"), list) else ""
            published = None  # updated_at is NOT the first publication time
            compensation = None
        elif provider == "lever":
            categories = row.get("categories") if isinstance(row.get("categories"), dict) else {}
            title, location_name = row.get("text"), categories.get("location")
            url, job_id = row.get("hostedUrl"), row.get("id")
            department = _text(categories.get("team"), 100)
            published = row.get("createdAt")  # epoch milliseconds
            compensation = None
        else:
            if row.get("isListed") is False:
                continue
            title, location_name = row.get("title"), row.get("location")
            url, job_id = row.get("jobUrl"), row.get("id")
            department = _text(row.get("department"), 100)
            published = row.get("publishedAt")
            compensation = _text(row.get("compensation"), 400) if row.get("compensation") else None
        safe_url = _job_url(url)
        if not safe_url or not _text(title):
            continue
        output.append({
            "provider": provider,
            "board": slug,
            "source_id": _text(job_id, 180) or safe_url,
            "title": _text(title),
            "location": _text(location_name),
            "department": department,
            "job_url": safe_url,
            "published_at": published,
            "compensation_as_published": compensation,
            "evidence": "public_official_ats_listing",
        })
    return output


def collect(
    boards: list[dict[str, str]],
    *,
    title_keywords: list[str] | None = None,
    max_results: int = 50,
    fetch: Callable[[str], object] = fetch_public_json,
) -> dict[str, object]:
    if not isinstance(boards, list) or not 1 <= len(boards) <= MAX_BOARDS:
        raise ValueError("boards_count_out_of_range")
    if not isinstance(max_results, int) or not 1 <= max_results <= MAX_RESULTS:
        raise ValueError("max_results_out_of_range")
    keywords = title_keywords or []
    if not isinstance(keywords, list) or len(keywords) > 10 or any(not isinstance(k, str) or len(k) > 60 for k in keywords):
        raise ValueError("invalid_title_keywords")
    terms = [_text(k, 60).casefold() for k in keywords if _text(k, 60)]
    found: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    for board in boards:
        if not isinstance(board, dict):
            raise ValueError("invalid_board")
        provider, slug = board.get("provider"), board.get("slug")
        url = source_url(provider, slug)  # validate BEFORE network access
        try:
            rows = normalize(provider, slug, fetch(url))
        except (ValueError, RuntimeError) as exc:
            errors.append({"provider": provider, "board": slug, "reason": str(exc)[:100]})
            continue
        for item in rows:
            if terms and not any(term in item["title"].casefold() for term in terms):
                continue
            if item["job_url"] in seen:
                continue
            seen.add(item["job_url"])
            found.append(item)
            if len(found) >= max_results:
                break
        if len(found) >= max_results:
            break
    return {
        "jobs": found,
        "errors": errors,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "boards_checked": len(boards),
        "results": len(found),
        "limits": {"max_boards": MAX_BOARDS, "max_results": MAX_RESULTS, "max_response_bytes": MAX_RESPONSE_BYTES},
    }
