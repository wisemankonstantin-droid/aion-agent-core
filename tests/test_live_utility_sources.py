import pytest

from app.services.live_utility import RefreshStrategy, SourceTier
from app.services.live_utility_sources import (
    SourceValidationError,
    configured_tier1_adapters,
)


def _payload(repository, *, tag="v1.0.0"):
    return {
        "id": 42,
        "tag_name": tag,
        "name": f"Release {tag}",
        "published_at": "2026-03-12T16:34:00Z",
        "html_url": f"https://github.com/{repository}/releases/tag/{tag}",
        "prerelease": False,
        "draft": False,
        "body": "Untrusted release prose is intentionally not normalized.",
    }


def test_exact_two_authoritative_sources_have_bounded_policies():
    adapters = configured_tier1_adapters()

    assert [adapter.source.source_id for adapter in adapters] == [
        "official-a2a-protocol-release",
        "official-mcp-specification-release",
    ]
    for adapter in adapters:
        assert adapter.source.tier is SourceTier.TIER_1
        assert adapter.source.canonical_locator.startswith("https://api.github.com/repos/")
        assert adapter.fetch_policy.timeout_seconds == 8
        assert adapter.fetch_policy.max_response_bytes == 256_000
        assert adapter.fetch_policy.max_attempts == 2
        assert adapter.fetch_policy.max_resolved_addresses == 4
        assert RefreshStrategy.TTL in adapter.source.refresh_policy.strategies
        assert RefreshStrategy.DEMAND_DRIVEN in adapter.source.refresh_policy.strategies
        assert adapter.source.refresh_policy.stale_after_seconds == 7 * 24 * 60 * 60
        assert adapter.source.refresh_policy.expires_after_seconds == 30 * 24 * 60 * 60


@pytest.mark.parametrize("adapter", configured_tier1_adapters())
def test_adapter_normalizes_only_bounded_release_fields(adapter):
    normalized = adapter.normalize(_payload(adapter.repository))

    assert normalized["version"] == "v1.0.0"
    assert normalized["published_at"].endswith("+00:00")
    assert "body" not in normalized
    assert len(normalized) == 8


def test_adapter_rejects_release_url_from_wrong_repository():
    adapter = configured_tier1_adapters()[0]
    payload = _payload("attacker/project")

    with pytest.raises(SourceValidationError, match="does not match"):
        adapter.normalize(payload)


def test_adapter_rejects_draft_and_malformed_release():
    adapter = configured_tier1_adapters()[0]
    draft = dict(_payload(adapter.repository), draft=True)

    with pytest.raises(SourceValidationError, match="draft"):
        adapter.normalize(draft)
    with pytest.raises(SourceValidationError, match="tag_name"):
        adapter.normalize({"name": "missing fields"})
