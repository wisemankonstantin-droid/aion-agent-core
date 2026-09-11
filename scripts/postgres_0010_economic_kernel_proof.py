"""Seed and verify the disposable PostgreSQL 0010 -> Package 6A head path."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE_NAME = "aion_package6a_0010"


def _guard() -> None:
    if os.getenv("AION_POSTGRES_GATE") != "1":
        raise SystemExit("AION_POSTGRES_GATE=1 is required")
    url = make_url(os.environ["DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost"} or url.database != DATABASE_NAME:
        raise SystemExit(f"Package 6A migration proof requires loopback {DATABASE_NAME}")


def seed() -> None:
    from app.db import engine

    with engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0010_package5_proof_v1"
        connection.execute(text("""
            INSERT INTO agents
              (id, external_id, name, description, endpoint, protocol,
               acquisition_source, referrer, owner_required, api_key_hash,
               reputation, trust_level, created_at, last_seen_at,
               first_useful_action_at, authenticated_calls)
            VALUES
              (61001, 'package6a-0010-sentinel', 'Package 6A 0010 Sentinel',
               'preserved Package 5 row', NULL, 'REST', NULL, NULL, false,
               'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
               0, 'declared', '2026-09-11 00:00:00+00', NULL, NULL, 1)
        """))
        connection.execute(text("""
            INSERT INTO payment_intents
              (id, agent_id, purpose, amount, protocol, status, created_at)
            VALUES
              (61002, 61001, 'legacy-intent-only', 'historical-untrusted-value',
               'manual', 'created', '2026-09-11 00:01:00+00')
        """))
        connection.execute(text("""
            INSERT INTO package5_participation_assessments
              (id, assessment_id, canonical_agent_id, idempotency_key,
               assessment_digest, classification, reason_code,
               evidence_authority, evidence_reference_digest,
               evidence_summary_digest, release_sha, assessed_at)
            VALUES
              (61003, '00000000-0000-4000-8000-000000006103', 61001,
               'package6a-0010-assessment',
               'sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
               'coordinated_design_partner', 'coordinated_design_partner',
               'operator_reviewed_evidence',
               'sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
               'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
               NULL, '2026-09-11 00:02:00+00')
        """))


def verify() -> None:
    from app.db import engine

    schema = inspect(engine)
    assert {"economic_operations", "economic_transitions"} <= set(schema.get_table_names())
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0011_economic_kernel_v1"
        assert connection.scalar(text("SELECT COUNT(*) FROM economic_operations")) == 0
        assert connection.scalar(text("SELECT COUNT(*) FROM economic_transitions")) == 0
        assert connection.execute(text(
            "SELECT external_id FROM agents WHERE id=61001"
        )).scalar_one() == "package6a-0010-sentinel"
        assert connection.execute(text(
            "SELECT amount, status FROM payment_intents WHERE id=61002"
        )).one() == ("historical-untrusted-value", "created")
        assert connection.execute(text(
            "SELECT classification FROM package5_participation_assessments WHERE id=61003"
        )).scalar_one() == "coordinated_design_partner"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "verify"))
    args = parser.parse_args(argv)
    _guard()
    seed() if args.mode == "seed" else verify()
    print(f"PACKAGE6A POSTGRES 0010 {args.mode.upper()} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
