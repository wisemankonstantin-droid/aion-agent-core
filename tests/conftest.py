import os
import sys
from pathlib import Path
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_DB = ROOT / ".aion-test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

POSTGRES_GATE = os.getenv("AION_POSTGRES_GATE") == "1"
if POSTGRES_GATE:
    # Only the disposable loopback CI service is allowed; no production URL.
    os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres@127.0.0.1:5432/aion_gate"
else:
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["AION_DISABLE_EXTERNAL_DISCOVERY"] = "1"
os.environ["AION_RETURN_THRESHOLD_MINUTES"] = "1"
os.environ["AION_JOIN_RATE_PER_MINUTE"] = "500"

from app.db import Base, engine  # noqa: E402
from app import models  # noqa: E402,F401

if not POSTGRES_GATE:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(64) NOT NULL)"))
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('0009_continuous_learning_v1')"))


def pytest_sessionfinish(session, exitstatus):
    # Keep release trees clean after local/CI test runs.
    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
