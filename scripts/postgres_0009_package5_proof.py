"""Seed and verify the disposable PostgreSQL 0009 -> Package 5 head path."""

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

DATABASE_NAME = "aion_package5_0009"


def _guard() -> None:
    if os.getenv("AION_POSTGRES_GATE") != "1":
        raise SystemExit("AION_POSTGRES_GATE=1 is required")
    url = make_url(os.environ["DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost"} or url.database != DATABASE_NAME:
        raise SystemExit(f"Package 5 migration proof requires loopback {DATABASE_NAME}")


def seed() -> None:
    from app.db import engine

    with engine.begin() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009_continuous_learning_v1"
        connection.execute(text("""
            INSERT INTO agents
              (id, external_id, name, description, endpoint, protocol,
               acquisition_source, referrer, owner_required, api_key_hash,
               reputation, trust_level, created_at, last_seen_at,
               first_useful_action_at, authenticated_calls)
            VALUES
              (52001, 'package5-0009-sentinel', 'Package 5 0009 Sentinel',
               'preserved Package 4 row', NULL, 'A2A', NULL, NULL, false,
               'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
               0, 'declared', '2026-09-10 00:00:00+00', NULL, NULL, 1)
        """))
        connection.execute(text("""
            INSERT INTO action_runs
              (id, action_id, requester_agent_id, idempotency_key, request_digest,
               requested_query, requested_candidate_identifier,
               authorize_external_contact, state, failure_class, created_at,
               started_at, completed_at, duration_ms, discovery_attempt_count,
               action_attempt_count, request_bytes, response_bytes,
               cost_amount, cost_currency)
            VALUES
              (52002, '00000000-0000-0000-0000-000000005202', 52001,
               'package5-0009-action',
               'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
               'legacy-callability', NULL, true, 'completed', NULL,
               '2026-09-10 00:01:00+00', '2026-09-10 00:01:00+00',
               '2026-09-10 00:01:01+00', 1000, 1, 1, 100, 100, NULL, NULL)
        """))
        connection.execute(text("""
            INSERT INTO action_outcomes
              (id, action_run_id, outcome_type, protocol_response_received,
               callability_verified, capability_verified, verified_outcome,
               normalized_result_kind, failure_class, response_digest,
               protocol_task_id, protocol_message_id, proof_present, completed_at)
            VALUES
              (52003, 52002, 'callability_challenge_verified', true, true, false,
               true, 'message', NULL,
               'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',
               NULL, 'package5-0009-message', true, '2026-09-10 00:01:01+00')
        """))
        connection.execute(text("""
            INSERT INTO action_verifications
              (id, action_run_id, action_outcome_id, verification_method, state,
               challenge_digest, proof_digest, verified_at, details)
            VALUES
              (52004, 52002, 52003, 'a2a_nonce_roundtrip_v1', 'verified',
               'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff',
               'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
               '2026-09-10 00:01:01+00', '{}'::json)
        """))


def verify() -> None:
    from app import models
    from app.db import SessionLocal, engine
    from app.main import _readiness_payload

    schema = inspect(engine)
    assert {"package5_participation_assessments", "package5_vuo_proofs"} <= set(schema.get_table_names())
    with SessionLocal.begin() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "0011_economic_execution_kernel_v1"
        assert db.scalar(text("SELECT COUNT(*) FROM economic_operations")) == 0
        assert db.scalar(text("SELECT COUNT(*) FROM economic_transitions")) == 0
        assert db.get(models.Agent, 52001).external_id == "package5-0009-sentinel"
        assert db.get(models.ActionRun, 52002).action_id == "00000000-0000-0000-0000-000000005202"
        assert db.get(models.ActionOutcome, 52003).verified_outcome is True
        assert db.get(models.ActionVerification, 52004).state == "verified"
        assert db.scalar(text("SELECT COUNT(*) FROM package5_participation_assessments")) == 0
        assert db.scalar(text("SELECT COUNT(*) FROM package5_vuo_proofs")) == 0
        db.execute(text("INSERT INTO machine_entries (source, created_at) VALUES ('package5-old-source-write', CURRENT_TIMESTAMP)"))
    with SessionLocal() as db:
        ready = _readiness_payload(db, a2a_status="mounted")
        assert ready["status"] == "ready", ready
        assert ready["schema_current"] is True, ready


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "verify"))
    args = parser.parse_args(argv)
    _guard()
    seed() if args.mode == "seed" else verify()
    print(f"PACKAGE5 POSTGRES 0009 {args.mode.upper()} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
