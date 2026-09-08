"""Two bounded Tier-1 adapters for official protocol release metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping
from urllib.parse import urlparse

from app.services.live_utility import (
    RefreshPolicy,
    RefreshStrategy,
    SourceDefinition,
    SourceTier,
)
from app.services.safe_http import FetchPolicy, FetchResult, fetch_json


VERIFICATION_METHOD = "official_github_release_api+pinned_https+schema_v1"


class SourceValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    transport: FetchResult
    payload: object | None


@dataclass(frozen=True, slots=True)
class GitHubReleaseAdapter:
    source: SourceDefinition
    subject_key: str
    repository: str
    fetch_policy: FetchPolicy

    def retrieve(self) -> AdapterResponse:
        result, payload = fetch_json(
            "GET",
            self.source.canonical_locator,
            headers={"X-GitHub-Api-Version": "2022-11-28"},
            policy=self.fetch_policy,
        )
        return AdapterResponse(result, payload)

    def normalize(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, Mapping):
            raise SourceValidationError("release payload must be an object")

        tag = payload.get("tag_name")
        name = payload.get("name")
        published = payload.get("published_at")
        official_url = payload.get("html_url")
        prerelease = payload.get("prerelease")
        draft = payload.get("draft")
        release_id = payload.get("id")
        if not isinstance(tag, str) or not tag.strip():
            raise SourceValidationError("tag_name is missing")
        if not isinstance(name, str) or not name.strip():
            raise SourceValidationError("release name is missing")
        if not isinstance(published, str):
            raise SourceValidationError("published_at is missing")
        try:
            published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError as exc:
            raise SourceValidationError("published_at is invalid") from exc
        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise SourceValidationError("published_at must be timezone-aware")
        if not isinstance(prerelease, bool) or not isinstance(draft, bool):
            raise SourceValidationError("release state fields are invalid")
        if draft:
            raise SourceValidationError("draft releases are not accepted")
        if not isinstance(release_id, int) or isinstance(release_id, bool):
            raise SourceValidationError("release id is invalid")
        if not isinstance(official_url, str):
            raise SourceValidationError("official release URL is missing")
        parsed = urlparse(official_url)
        expected_prefix = f"/{self.repository}/releases/tag/"
        if (
            parsed.scheme != "https"
            or parsed.hostname != "github.com"
            or not parsed.path.startswith(expected_prefix)
        ):
            raise SourceValidationError("official release URL does not match repository")

        return {
            "protocol": self.subject_key.split(".", 1)[0],
            "version": tag.strip(),
            "release_name": name.strip(),
            "published_at": published_at.astimezone(timezone.utc).isoformat(),
            "official_url": official_url,
            "prerelease": prerelease,
            "draft": draft,
            "release_id": release_id,
        }

    def source_revision(self, normalized: Mapping[str, object]) -> str:
        return str(normalized["version"])


def _source(
    source_id: str,
    display_name: str,
    repository: str,
) -> SourceDefinition:
    return SourceDefinition(
        source_id=source_id,
        display_name=display_name,
        tier=SourceTier.TIER_1,
        source_kind="official_github_release_api",
        canonical_locator=f"https://api.github.com/repos/{repository}/releases/latest",
        refresh_policy=RefreshPolicy(
            strategies=frozenset(
                {
                    RefreshStrategy.TTL,
                    RefreshStrategy.DEMAND_DRIVEN,
                    RefreshStrategy.SCHEDULED,
                }
            ),
            stale_after_seconds=7 * 24 * 60 * 60,
            expires_after_seconds=30 * 24 * 60 * 60,
        ),
    )


def configured_tier1_adapters() -> tuple[GitHubReleaseAdapter, ...]:
    policy = FetchPolicy(
        timeout_seconds=8,
        max_response_bytes=256_000,
        max_attempts=2,
        max_resolved_addresses=4,
    )
    return (
        GitHubReleaseAdapter(
            source=_source(
                "official-a2a-protocol-release",
                "Official A2A protocol release",
                "a2aproject/A2A",
            ),
            subject_key="a2a.protocol_release",
            repository="a2aproject/A2A",
            fetch_policy=policy,
        ),
        GitHubReleaseAdapter(
            source=_source(
                "official-mcp-specification-release",
                "Official Model Context Protocol specification release",
                "modelcontextprotocol/modelcontextprotocol",
            ),
            subject_key="mcp.protocol_release",
            repository="modelcontextprotocol/modelcontextprotocol",
            fetch_policy=policy,
        ),
    )
