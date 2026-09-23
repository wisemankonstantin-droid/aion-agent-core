from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


LATEST_REVISION = "0018_acquisition_agent_minds_v1"


def _alembic(root: Path, database_url: str, *args: str) -> None:
    env = dict(os.environ, DATABASE_URL=database_url)
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_existing_0013_upgrades_additively_to_conversation_intelligence(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "package-5f-upgrade-path.db"
    url = "sqlite:///" + database.as_posix()

    _alembic(root, url, "upgrade", "0013_ambassador_control_v1")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO ambassador_campaigns "
            "(campaign_id, name, purpose, state, maximum_targets, maximum_contacts, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "package-5f-sentinel",
                "Package 5F Sentinel",
                "preserve Package 5E state",
                "draft",
                1,
                0,
                "2026-09-13 12:00:00",
                "2026-09-13 12:00:00",
            ),
        )
        connection.execute(
            "INSERT INTO ambassador_operator_actions "
            "(action_id, operation_kind, campaign_id, target_id, idempotency_key, request_digest, result_class, created_at, completed_at) "
            "SELECT ?, ?, id, NULL, ?, ?, ?, ?, ? FROM ambassador_campaigns WHERE campaign_id=?",
            (
                "11111111-1111-4111-8111-111111111111",
                "set_campaign_state",
                "package5f-sentinel",
                "sha256:sentinel",
                "succeeded",
                "2026-09-13 12:01:00",
                "2026-09-13 12:01:01",
                "package-5f-sentinel",
            ),
        )
        connection.commit()

    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "upgrade", "head")
    _alembic(root, url, "check")

    with sqlite3.connect(database) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        sentinel = connection.execute(
            "SELECT campaign_id FROM ambassador_campaigns WHERE campaign_id='package-5f-sentinel'"
        ).fetchone()
        audits = connection.execute("SELECT COUNT(*) FROM ambassador_operator_actions").fetchone()[0]
        evidence_count = connection.execute("SELECT COUNT(*) FROM conversation_evidence").fetchone()[0]
        intelligence_count = connection.execute("SELECT COUNT(*) FROM conversation_intelligence").fetchone()[0]
        evidence_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='conversation_evidence'"
        ).fetchone()[0]

    assert revision == LATEST_REVISION
    assert {"conversation_evidence", "conversation_intelligence"} <= tables
    assert sentinel == ("package-5f-sentinel",)
    assert audits == 1
    assert evidence_count == intelligence_count == 0
    assert "ck_conversation_evidence_no_text_bytes" in evidence_sql
    assert "digest_only" in evidence_sql
