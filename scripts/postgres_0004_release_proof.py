"""Seed and verify the disposable Package 4 PostgreSQL 0004 -> 0009 path."""

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


LEGACY_AGENT_IDS = (41001, 41002)
ROLLBACK_COMPAT_AGENT_ID = 41003


def _guard_disposable_database() -> None:
    if os.getenv("AION_POSTGRES_GATE") != "1":
        raise SystemExit("AION_POSTGRES_GATE=1 is required")
    url = make_url(os.environ["DATABASE_URL"])
    if url.host not in {"127.0.0.1", "localhost"}:
        raise SystemExit("Package 4 migration proof requires loopback PostgreSQL")
    if url.database != "aion_package4_legacy":
        raise SystemExit("Package 4 migration proof requires aion_package4_legacy")


def seed_0004() -> None:
    from app.db import engine

    created = "2026-09-01 00:00:00+00"
    with engine.begin() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0004_reputation_idempotency", revision
        connection.execute(text("""
            INSERT INTO agents
              (id, external_id, name, description, endpoint, protocol,
               acquisition_source, referrer, owner_required, api_key_hash,
               reputation, trust_level, created_at, last_seen_at,
               first_useful_action_at, authenticated_calls)
            VALUES
              (41001, 'package4-legacy-requester', 'Legacy Requester',
               'representative requester', 'https://requester.example/a2a', 'A2A',
               'legacy-import', 'package4-gate', false,
               'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
               1.5, 'observed', :created, :created, :created, 3),
              (41002, 'package4-legacy-provider', 'Legacy Provider',
               'representative provider', 'https://provider.example/a2a', 'A2A',
               'legacy-import', 'package4-gate', false,
               'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
               2.5, 'observed', :created, :created, :created, 4)
        """), {"created": created})
        connection.execute(text("""
            INSERT INTO capabilities (id, agent_id, name, description, verification)
            VALUES (41101, 41002, 'document-analysis', 'legacy capability', 'declared')
        """))
        connection.execute(text("""
            INSERT INTO needs (id, agent_id, capability, description, status, created_at)
            VALUES (41201, 41001, 'document-analysis', 'legacy need', 'open', :created)
        """), {"created": created})
        connection.execute(text("""
            INSERT INTO offers (id, agent_id, capability, description, price_hint, created_at)
            VALUES (41301, 41002, 'document-analysis', 'legacy offer', '10 units', :created)
        """), {"created": created})
        connection.execute(text("""
            INSERT INTO interactions
              (id, requester_agent_id, provider_agent_id, need_id, result, score, created_at)
            VALUES (41401, 41001, 41002, 41201, 'completed', 4.5, :created)
        """), {"created": created})
        connection.execute(text("""
            INSERT INTO reputation_events (id, agent_id, delta, reason, created_at)
            VALUES (41501, 41002, 1.0, 'package4-legacy-completion', :created)
        """), {"created": created})
        connection.execute(text("""
            INSERT INTO payment_intents
              (id, agent_id, purpose, amount, protocol, status, created_at)
            VALUES (41601, 41001, 'legacy-intent', '10 units', 'manual', 'created', :created)
        """), {"created": created})
        connection.execute(text("""
            INSERT INTO machine_entries (id, source, created_at)
            VALUES (41701, 'package4-legacy-gate', :created)
        """), {"created": created})


def verify_0009_and_rollback_compatibility() -> None:
    from app import models
    from app.db import SessionLocal, engine
    from app.main import _readiness_payload

    expected_tables = {
        "live_utility_sources",
        "live_utility_observations",
        "live_utility_verifications",
        "agent_utility_checkpoints",
        "action_runs",
        "action_attempts",
        "action_outcomes",
        "action_verifications",
        "learning_runs",
        "learning_source_watch_states",
        "agent_evidence_claims",
        "learning_opportunity_candidates",
    }
    schema = inspect(engine)
    assert expected_tables <= set(schema.get_table_names())
    assert "normalized_data" in {
        column["name"] for column in schema.get_columns("live_utility_observations")
    }
    assert "uq_agent_utility_checkpoints_agent_subject" in {
        item["name"] for item in schema.get_unique_constraints("agent_utility_checkpoints")
    }
    assert "uq_action_runs_requester_idempotency" in {
        item["name"] for item in schema.get_unique_constraints("action_runs")
    }
    assert "uq_agent_evidence_claims_requester_material" in {
        item["name"] for item in schema.get_unique_constraints("agent_evidence_claims")
    }
    assert "ix_learning_opportunities_priority" in {
        item["name"] for item in schema.get_indexes("learning_opportunity_candidates")
    }

    with SessionLocal.begin() as db:
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        assert revision == "0009_continuous_learning_v1", revision
        requester = db.get(models.Agent, LEGACY_AGENT_IDS[0])
        provider = db.get(models.Agent, LEGACY_AGENT_IDS[1])
        assert requester.external_id == "package4-legacy-requester"
        assert provider.external_id == "package4-legacy-provider"
        assert db.get(models.Capability, 41101).agent_id == provider.id
        assert db.get(models.Need, 41201).agent_id == requester.id
        assert db.get(models.Offer, 41301).agent_id == provider.id
        interaction = db.get(models.Interaction, 41401)
        assert (interaction.requester_agent_id, interaction.provider_agent_id, interaction.need_id) == (41001, 41002, 41201)
        assert db.get(models.ReputationEvent, 41501).reason == "package4-legacy-completion"
        assert db.get(models.PaymentIntent, 41601).status == "created"
        assert db.get(models.MachineEntry, 41701).source == "package4-legacy-gate"

        # These statements use only the 0004-era columns.  Success after the
        # upgrade is the rollback-compatibility proof for the old application.
        db.execute(text("""
            INSERT INTO agents
              (id, external_id, name, description, endpoint, protocol,
               acquisition_source, referrer, owner_required, api_key_hash,
               reputation, trust_level, created_at, last_seen_at,
               first_useful_action_at, authenticated_calls)
            VALUES
              (41003, 'package4-rollback-compatible', 'Rollback Compatible',
               '0004-era write after 0009', NULL, 'REST', 'legacy-import',
               'package4-gate', false,
               'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
               0.0, 'declared', CURRENT_TIMESTAMP, NULL, NULL, 0)
        """))
        db.execute(text("""
            INSERT INTO capabilities (id, agent_id, name, description, verification)
            VALUES (41103, 41003, 'rollback-check', 'legacy write', 'declared')
        """))
    with SessionLocal() as db:
        assert db.get(models.Agent, ROLLBACK_COMPAT_AGENT_ID).name == "Rollback Compatible"
        ready = _readiness_payload(db, a2a_status="mounted")
        assert ready["status"] == "ready", ready
        assert ready["schema_current"] is True, ready


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("seed", "verify"))
    args = parser.parse_args(argv)
    _guard_disposable_database()
    if args.mode == "seed":
        seed_0004()
    else:
        verify_0009_and_rollback_compatibility()
    print(f"PACKAGE4 POSTGRES 0004 {args.mode.upper()} PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
