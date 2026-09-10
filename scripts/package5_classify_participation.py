"""Human-gated operator CLI for Package 5 participation evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.services.package5_proof import (  # noqa: E402
    Package5ProofError,
    record_participation_assessment,
)


CLASSIFICATIONS = (
    "aion_operated_internal",
    "synthetic_probe_test",
    "coordinated_design_partner",
    "operator_invited_coordinated_test",
    "independent_external_candidate",
    "independent_external_countable",
)


def main(argv=None) -> int:
    if os.getenv("AION_PACKAGE5_OPERATOR") != "1":
        raise SystemExit("AION_PACKAGE5_OPERATOR=1 is required; this is not a public agent API")
    parser = argparse.ArgumentParser(description="Record reviewed Package 5 participation evidence")
    parser.add_argument("--agent-id", required=True, type=int)
    parser.add_argument("--classification", required=True, choices=CLASSIFICATIONS)
    parser.add_argument("--evidence-reference", required=True)
    parser.add_argument("--evidence-summary", required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args(argv)
    try:
        with SessionLocal() as db:
            result = record_participation_assessment(
                db,
                agent_id=args.agent_id,
                classification=args.classification,
                evidence_reference=args.evidence_reference,
                evidence_summary=args.evidence_summary,
                idempotency_key=args.idempotency_key,
            )
    except Package5ProofError as exc:
        raise SystemExit(f"{exc.code}: {exc.message}") from exc
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
