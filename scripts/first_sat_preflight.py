"""Print the read-only first-SAT activation preflight as secret-safe JSON."""

from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.services.first_sat_activation import first_sat_activation_preflight  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only first-SAT activation preflight")
    parser.add_argument(
        "--expected-release-sha",
        help="Exact independently approved release SHA; missing or invalid SHA blocks readiness",
    )
    arguments = parser.parse_args()
    with SessionLocal() as db:
        result = first_sat_activation_preflight(
            db, expected_release_sha=arguments.expected_release_sha
        )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0 if result["activation_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
