import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _alembic(root, database_url, *args):
    env = dict(os.environ, DATABASE_URL=database_url)
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_existing_0005_database_upgrades_to_live_utility_data_engine_head(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0005_live_utility_persistence")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO machine_entries (source, created_at) VALUES (?, ?)",
            ("migration-sentinel", "2026-09-08 12:00:00"),
        )
        connection.execute(
            """INSERT INTO live_utility_sources
            (source_id, display_name, tier, source_kind, canonical_locator,
             refresh_strategies, stale_after_seconds, expires_after_seconds, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "migration-source",
                "Migration source",
                "tier_1",
                "fixture",
                "fixture:migration",
                '["ttl"]',
                60,
                120,
                1,
            ),
        )
        connection.execute(
            """INSERT INTO live_utility_observations
            (observation_id, source_id, subject_key, source_revision,
             previous_observation_id, observed_at, verified_at, valid_from,
             stale_after, expires_at, verification_method, content_digest)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "migration-observation",
                "migration-source",
                "protocol.release",
                "v1",
                None,
                "2026-09-08 12:00:00",
                "2026-09-08 12:00:00",
                "2026-09-08 12:00:00",
                "2026-09-08 12:01:00",
                "2026-09-08 12:02:00",
                "fixture",
                "sha256:migration",
            ),
        )
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        source_indexes = connection.execute(
            "PRAGMA index_list('live_utility_sources')"
        ).fetchall()
        source_unique_index_columns = {
            tuple(
                row[2]
                for row in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                ).fetchall()
            )
            for index in source_indexes
            if index[2] == 1
        }
        observation_indexes = connection.execute(
            "PRAGMA index_list('live_utility_observations')"
        ).fetchall()
        observation_unique_index_columns = {
            tuple(
                row[2]
                for row in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                ).fetchall()
            )
            for index in observation_indexes
            if index[2] == 1
        }
        observation_foreign_keys = connection.execute(
            "PRAGMA foreign_key_list('live_utility_observations')"
        ).fetchall()
        source_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='live_utility_sources'"
        ).fetchone()[0]
        observation_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='live_utility_observations'"
        ).fetchone()[0]
        sentinel = connection.execute(
            "SELECT source FROM machine_entries WHERE source='migration-sentinel'"
        ).fetchone()
        observation_sentinel = connection.execute(
            "SELECT content_digest, normalized_data FROM live_utility_observations "
            "WHERE observation_id='migration-observation'"
        ).fetchone()
        verification_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='live_utility_verifications'"
        ).fetchone()[0]
        verification_indexes = connection.execute(
            "PRAGMA index_list('live_utility_verifications')"
        ).fetchall()
        verification_foreign_keys = connection.execute(
            "PRAGMA foreign_key_list('live_utility_verifications')"
        ).fetchall()
        verification_unique_index_columns = {
            tuple(
                row[2]
                for row in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                ).fetchall()
            )
            for index in verification_indexes
            if index[2] == 1
        }

    assert revision == "0012_ambassador_pilot_v1"
    assert {
        "agents",
        "machine_entries",
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
        "package5_participation_assessments",
        "package5_vuo_proofs",
    } <= tables
    assert ("source_id",) in source_unique_index_columns
    assert ("observation_id",) in observation_unique_index_columns
    assert {
        "ix_live_utility_observations_source_id",
        "ix_live_utility_observations_source_subject_observed",
    } <= {row[1] for row in observation_indexes}
    assert {row[2] for row in observation_foreign_keys} == {
        "live_utility_sources",
        "live_utility_observations",
    }
    assert "ck_live_utility_sources_window_order" in source_sql
    assert "ck_live_utility_observations_verified_order" in observation_sql
    assert sentinel == ("migration-sentinel",)
    assert observation_sentinel == ("sha256:migration", None)
    assert "ck_live_utility_verifications_stale_expires_order" in verification_sql
    assert ("verification_id",) in verification_unique_index_columns
    assert "ix_live_utility_verifications_source_subject_verified" in {
        row[1] for row in verification_indexes
    }
    assert {row[2] for row in verification_foreign_keys} == {
        "live_utility_sources",
        "live_utility_observations",
    }


def test_fresh_database_upgrades_to_live_utility_head(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "fresh-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert revision == "0012_ambassador_pilot_v1"
    assert {
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
        "package5_participation_assessments",
        "package5_vuo_proofs",
    } <= tables


def test_existing_0006_database_upgrades_to_agent_utility_checkpoints(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "package-2-upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0006_live_utility_data")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO agents (external_id, name, description, protocol, owner_required, "
            "api_key_hash, reputation, trust_level, authenticated_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("migration-agent", "Migration Agent", "", "A2A", 0, "migration-hash", 0, "declared", 0, "2026-09-09 12:00:00"),
        )
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        checkpoint_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' "
            "AND name='agent_utility_checkpoints'"
        ).fetchone()[0]
        unique_indexes = connection.execute(
            "PRAGMA index_list('agent_utility_checkpoints')"
        ).fetchall()
        unique_columns = {
            tuple(
                row[2]
                for row in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                ).fetchall()
            )
            for index in unique_indexes
            if index[2] == 1
        }
        agent = connection.execute(
            "SELECT external_id FROM agents WHERE external_id='migration-agent'"
        ).fetchone()

    assert revision == "0012_ambassador_pilot_v1"
    assert "FOREIGN KEY(agent_id)" in checkpoint_sql
    assert ("agent_id", "subject_key") in unique_columns
    assert agent == ("migration-agent",)


def test_existing_0007_database_upgrades_to_action_outcome_evidence(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "package-3-upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0007_agent_utility_checkpoints")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO agents (external_id, name, description, protocol, owner_required, "
            "api_key_hash, reputation, trust_level, authenticated_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("package-3-sentinel", "Package 3 Sentinel", "", "A2A", 0,
             "package-3-hash", 0, "declared", 0, "2026-09-09 12:00:00"),
        )
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        action_indexes = connection.execute(
            "PRAGMA index_list('action_runs')"
        ).fetchall()
        unique_columns = {
            tuple(
                row[2]
                for row in connection.execute(
                    f"PRAGMA index_info('{index[1]}')"
                ).fetchall()
            )
            for index in action_indexes
            if index[2] == 1
        }
        sentinel = connection.execute(
            "SELECT external_id FROM agents WHERE external_id='package-3-sentinel'"
        ).fetchone()

    assert revision == "0012_ambassador_pilot_v1"
    assert {"action_runs", "action_attempts", "action_outcomes", "action_verifications"} <= tables
    assert ("requester_agent_id", "idempotency_key") in unique_columns
    assert ("action_id",) in unique_columns
    assert sentinel == ("package-3-sentinel",)


def test_existing_0008_database_upgrades_to_continuous_learning_v1(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "package-3b-upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0008_action_outcome_evidence")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO agents (external_id, name, description, protocol, owner_required, "
            "api_key_hash, reputation, trust_level, authenticated_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("package-3b-sentinel", "Package 3B Sentinel", "", "A2A", 0,
             "package-3b-hash", 0, "declared", 0, "2026-09-09 12:00:00"),
        )
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        evidence_indexes = connection.execute("PRAGMA index_list('agent_evidence_claims')").fetchall()
        evidence_unique_columns = {
            tuple(row[2] for row in connection.execute(f"PRAGMA index_info('{index[1]}')").fetchall())
            for index in evidence_indexes if index[2] == 1
        }
        sentinel = connection.execute(
            "SELECT external_id FROM agents WHERE external_id='package-3b-sentinel'"
        ).fetchone()

    assert revision == "0012_ambassador_pilot_v1"
    assert {
        "learning_runs", "learning_source_watch_states", "agent_evidence_claims",
        "learning_opportunity_candidates",
        "package5_participation_assessments", "package5_vuo_proofs",
    } <= tables
    assert ("requester_agent_id", "idempotency_key") in evidence_unique_columns
    assert ("requester_agent_id", "evidence_digest") in evidence_unique_columns
    assert sentinel == ("package-3b-sentinel",)


def test_existing_0009_database_upgrades_additively_without_fake_package5_proof(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "package-5-upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0009_continuous_learning_v1")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO agents (external_id, name, description, protocol, owner_required, "
            "api_key_hash, reputation, trust_level, authenticated_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("package-5-sentinel", "Package 5 Sentinel", "", "A2A", 0,
             "package-5-hash", 0, "declared", 0, "2026-09-10 12:00:00"),
        )
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assessments = connection.execute("SELECT COUNT(*) FROM package5_participation_assessments").fetchone()[0]
        vuos = connection.execute("SELECT COUNT(*) FROM package5_vuo_proofs").fetchone()[0]
        sentinel = connection.execute(
            "SELECT external_id FROM agents WHERE external_id='package-5-sentinel'"
        ).fetchone()
        vuo_indexes = connection.execute("PRAGMA index_list('package5_vuo_proofs')").fetchall()
        assessment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('package5_participation_assessments')")
        }
        vuo_foreign_keys = {
            (row[3], row[2]) for row in connection.execute("PRAGMA foreign_key_list('package5_vuo_proofs')")
        }
        vuo_unique_columns = {
            tuple(row[2] for row in connection.execute(f"PRAGMA index_info('{index[1]}')").fetchall())
            for index in vuo_indexes if index[2] == 1
        }

    assert revision == "0012_ambassador_pilot_v1"
    assert {"package5_participation_assessments", "package5_vuo_proofs"} <= tables
    assert assessments == vuos == 0
    assert sentinel == ("package-5-sentinel",)
    assert ("action_run_id",) in vuo_unique_columns
    assert ("canonical_requester_agent_id", "idempotency_key") in vuo_unique_columns
    assert "evidence_summary_digest" in assessment_columns
    assert "evidence_summary" not in assessment_columns
    assert ("participation_assessment_id", "package5_participation_assessments") in vuo_foreign_keys


def test_existing_0010_upgrades_additively_without_promoting_legacy_intent(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "package-6a-upgrade-path.db"
    url = "sqlite:///" + database.as_posix()
    _alembic(root, url, "upgrade", "0010_package5_proof_v1")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO agents (external_id, name, description, protocol, owner_required, "
            "api_key_hash, reputation, trust_level, authenticated_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("package-6a-sentinel", "Package 6A Sentinel", "", "REST", 0,
             "package-6a-hash", 0, "declared", 0, "2026-09-11 12:00:00"),
        )
        agent_id = connection.execute("SELECT id FROM agents WHERE external_id='package-6a-sentinel'").fetchone()[0]
        connection.execute(
            "INSERT INTO payment_intents (agent_id, purpose, amount, protocol, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (agent_id, "legacy-only", "untrusted-string", "manual", "created", "2026-09-11 12:00:00"),
        )
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        legacy = connection.execute("SELECT amount, status FROM payment_intents WHERE purpose='legacy-only'").fetchone()
        operations = connection.execute("SELECT COUNT(*) FROM economic_operations").fetchone()[0]
        transitions = connection.execute("SELECT COUNT(*) FROM economic_transitions").fetchone()[0]
        indexes = connection.execute("PRAGMA index_list('economic_operations')").fetchall()
        unique_columns = {
            tuple(row[2] for row in connection.execute(f"PRAGMA index_info('{index[1]}')").fetchall())
            for index in indexes if index[2] == 1
        }
        operation_foreign_keys = {
            (row[3], row[2]) for row in connection.execute("PRAGMA foreign_key_list('economic_operations')")
        }
    assert revision == "0012_ambassador_pilot_v1"
    assert {"economic_operations", "economic_transitions"} <= tables
    assert legacy == ("untrusted-string", "created")
    assert operations == transitions == 0
    assert ("requester_agent_id", "idempotency_key") in unique_columns
    assert ("operation_id",) in unique_columns
    assert ("action_run_id",) in unique_columns
    assert ("parent_economic_operation_id", "economic_operations") in operation_foreign_keys
    assert ("action_run_id", "action_runs") in operation_foreign_keys


def test_existing_0011_upgrades_additively_to_ambassador_pilot(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "package-5d-upgrade-path.db"
    url = "sqlite:///" + database.as_posix()
    _alembic(root, url, "upgrade", "0011_economic_kernel_v1")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO agents (external_id, name, description, protocol, owner_required, "
            "api_key_hash, reputation, trust_level, authenticated_calls, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("package-5d-sentinel", "Package 5D Sentinel", "", "REST", 0,
             "package-5d-hash", 0, "declared", 0, "2026-09-12 12:00:00"),
        )
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")
    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "ambassador_campaigns", "ambassador_targets", "ambassador_contact_attempts",
                "distribution_tokens", "distribution_join_attributions",
            )
        }
        sentinel = connection.execute(
            "SELECT external_id FROM agents WHERE external_id='package-5d-sentinel'"
        ).fetchone()
        target_indexes = connection.execute("PRAGMA index_list('ambassador_targets')").fetchall()
        target_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('ambassador_targets')").fetchall()
        }
        target_unique_columns = {
            tuple(row[2] for row in connection.execute(f"PRAGMA index_info('{index[1]}')").fetchall())
            for index in target_indexes if index[2] == 1
        }
    assert revision == "0012_ambassador_pilot_v1"
    assert set(counts) <= tables
    assert all(value == 0 for value in counts.values())
    assert sentinel == ("package-5d-sentinel",)
    assert "prepared_message_digest" in target_columns
    assert ("target_fingerprint",) in target_unique_columns
