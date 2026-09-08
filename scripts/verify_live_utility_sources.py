"""Opt-in controlled verification of the two configured official sources."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Base  # noqa: E402
from app import models  # noqa: E402,F401
from app.services.live_utility_engine import LiveUtilityEngine  # noqa: E402
from app.services.live_utility_sources import configured_tier1_adapters  # noqa: E402


def main() -> int:
    database = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(database)
    engine = LiveUtilityEngine(configured_tier1_adapters())
    checked_at = datetime.now(timezone.utc)
    evidence = []
    with Session(database) as session, session.begin():
        engine.ensure_sources(session)
        for adapter in configured_tier1_adapters():
            result = engine.refresh_source(
                session,
                source_id=adapter.source.source_id,
                now=checked_at,
                demand=True,
            )
            state = result.current_state
            evidence.append(
                {
                    "source_id": adapter.source.source_id,
                    "status": result.status.value,
                    "attempts": result.attempts,
                    "version": (
                        state.normalized_data.get("version")
                        if state and state.normalized_data
                        else None
                    ),
                    "freshness": state.freshness.state.value if state else None,
                    "content_digest": (
                        state.observation.content_digest if state else None
                    ),
                    "error": result.error,
                }
            )
    database.dispose()
    print(json.dumps({"checked_at": checked_at.isoformat(), "sources": evidence}, indent=2))
    return 0 if all(item["freshness"] == "fresh" for item in evidence) else 1


if __name__ == "__main__":
    raise SystemExit(main())
