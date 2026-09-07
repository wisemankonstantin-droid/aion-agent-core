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


def test_v062_database_upgrades_forward_to_reconciled_head(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0003_activation_funnel")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        indexes = connection.execute("PRAGMA index_list('reputation_events')").fetchall()

    assert revision == "0004_reputation_idempotency"
    assert any(row[1] == "uq_reputation_events_agent_reason" and row[2] == 1 for row in indexes)
