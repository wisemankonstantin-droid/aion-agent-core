"""Safe immutable release and schema identity for release gates."""

from __future__ import annotations

import os
import re


EXPECTED_SCHEMA_REVISION = "0011_economic_execution_kernel_v1"
_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")


def release_identity() -> dict[str, str | None]:
    """Return only validated release metadata, never arbitrary environment data."""

    for variable, source in (
        ("RENDER_GIT_COMMIT", "render_git_commit"),
        ("AION_RELEASE_SHA", "aion_release_sha"),
    ):
        raw = os.getenv(variable)
        if raw is None:
            continue
        value = raw.strip()
        if _SHA_PATTERN.fullmatch(value):
            return {"release_sha": value.lower(), "release_source": source}
        return {"release_sha": None, "release_source": f"{source}_invalid"}
    return {"release_sha": None, "release_source": "unknown"}
