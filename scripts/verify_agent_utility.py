"""Controlled Package 2 proof using real configured sources and public REST."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aion-package-2-") as directory:
        database_path = Path(directory) / "proof.db"
        os.environ["DATABASE_URL"] = "sqlite:///" + database_path.as_posix()
        os.environ["AION_DISABLE_EXTERNAL_DISCOVERY"] = "1"

        from fastapi.testclient import TestClient
        from sqlalchemy import func, select

        from app import models
        from app.db import Base, SessionLocal, engine
        from app.main import app
        from app.services.live_utility_engine import LiveUtilityEngine
        from app.services.live_utility_sources import configured_tier1_adapters

        Base.metadata.create_all(engine)
        checked_at = datetime.now(timezone.utc)
        refresh = LiveUtilityEngine(configured_tier1_adapters())
        versions = {}
        with SessionLocal.begin() as db:
            refresh.ensure_sources(db)
            for adapter in configured_tier1_adapters():
                result = refresh.refresh_source(
                    db,
                    source_id=adapter.source.source_id,
                    now=checked_at,
                    demand=True,
                )
                if result.current_state and result.current_state.normalized_data:
                    versions[adapter.subject_key.split(".", 1)[0]] = (
                        result.current_state.normalized_data["version"]
                    )

        with SessionLocal() as db:
            before_agents = db.scalar(select(func.count()).select_from(models.Agent))

        response = TestClient(app).post(
            "/utility/query",
            json={
                "subject": "all",
                "context": {
                    "supported_protocols": sorted(versions),
                    "supported_protocol_versions": {
                        protocol: [version] for protocol, version in versions.items()
                    },
                },
            },
        )
        response.raise_for_status()
        payload = response.json()

        with SessionLocal() as db:
            after_agents = db.scalar(select(func.count()).select_from(models.Agent))

        proof = {
            "checked_at": checked_at.isoformat(),
            "http_status": response.status_code,
            "utility_status": payload["status"],
            "anonymous_membership_created": after_agents != before_agents,
            "results": [
                {
                    "subject": item["subject"],
                    "source_id": item["source"]["source_id"],
                    "source_revision": item["source"]["source_revision"],
                    "source_tier": item["source"]["tier"],
                    "verification_level": item["evidence"]["verification_level"],
                    "freshness": item["freshness"]["state"],
                    "compatibility": item["compatibility"]["decision"],
                    "current_eligibility": item["current_eligibility"],
                }
                for item in payload["results"]
            ],
        }
        print(json.dumps(proof, indent=2))
        passed = (
            payload["status"] == "ok"
            and after_agents == before_agents
            and len(payload["results"]) == 2
            and all(
                item["freshness"] == "fresh"
                and item["verification_level"] == "source_observation_verified"
                and item["compatibility"] == "compatible"
                and item["current_eligibility"]
                for item in proof["results"]
            )
        )
        engine.dispose()
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
