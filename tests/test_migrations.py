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


def test_existing_0004_database_upgrades_to_live_utility_head(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0004_reputation_idempotency")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO machine_entries (source, created_at) VALUES (?, ?)",
            ("migration-sentinel", "2026-09-08 12:00:00"),
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

    assert revision == "0005_live_utility_persistence"
    assert {"agents", "machine_entries", "live_utility_sources", "live_utility_observations"} <= tables
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

    assert revision == "0005_live_utility_persistence"
    assert {"live_utility_sources", "live_utility_observations"} <= tables
