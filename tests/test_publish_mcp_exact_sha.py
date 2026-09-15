from pathlib import Path


def test_mcp_publication_uses_exact_deployed_release_source_before_metadata():
    workflow = Path(".github/workflows/publish-mcp.yml").read_text(encoding="utf-8")

    checkout_ref = "ref: ${{ inputs.expected_release_sha }}"
    verify_head = 'test "$(git rev-parse HEAD)" = "$AION_EXPECTED_RELEASE_SHA"'
    live_gate = "- name: Live gate first"
    generate_metadata = "- name: Generate MCP Registry metadata"
    publish = "- name: Publish"

    assert checkout_ref in workflow
    assert verify_head in workflow

    positions = [
        workflow.index(checkout_ref),
        workflow.index(verify_head),
        workflow.index(live_gate),
        workflow.index(generate_metadata),
        workflow.index(publish),
    ]
    assert positions == sorted(positions)
