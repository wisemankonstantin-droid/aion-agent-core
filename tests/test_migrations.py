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

    assert revision == "0007_agent_utility_checkpoints"
    assert {
        "agents",
        "machine_entries",
        "live_utility_sources",
        "live_utility_observations",
        "live_utility_verifications",
        "agent_utility_checkpoints",
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

    assert revision == "0007_agent_utility_checkpoints"
    assert {
        "live_utility_sources",
        "live_utility_observations",
        "live_utility_verifications",
        "agent_utility_checkpoints",
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

    assert revision == "0007_agent_utility_checkpoints"
    assert "FOREIGN KEY(agent_id)" in checkpoint_sql
    assert ("agent_id", "subject_key") in unique_columns
    assert agent == ("migration-agent",)
