"""Run one bounded Package 3B learning cycle and print JSON."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.learning_engine import run_learning_cycle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded AION learning cycle")
    parser.add_argument(
        "--trigger",
        choices=("scheduled", "operator", "demand", "usage", "impact"),
        default="operator",
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="source_ids",
        help="Configured watched source ID; may be provided at most twice",
    )
    arguments = parser.parse_args()
    context = {"trigger": arguments.trigger}
    if arguments.source_ids:
        context["source_ids"] = arguments.source_ids
    result = run_learning_cycle(datetime.now(timezone.utc), context)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
