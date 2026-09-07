import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / ".aion-test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["AION_DISABLE_EXTERNAL_DISCOVERY"] = "1"
os.environ["AION_RETURN_THRESHOLD_MINUTES"] = "1"
os.environ["AION_JOIN_RATE_PER_MINUTE"] = "500"

from app.db import Base, engine  # noqa: E402
from app import models  # noqa: E402,F401

Base.metadata.create_all(bind=engine)


def pytest_sessionfinish(session, exitstatus):
    # Keep release trees clean after local/CI test runs.
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
