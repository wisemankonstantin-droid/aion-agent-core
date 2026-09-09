import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models
from app.db import SessionLocal
from app.db import get_db
from app.main import _readiness_payload, app
from app.release_identity import EXPECTED_SCHEMA_REVISION, release_identity
from app.services import learning_engine, safe_http
from scripts import learning_cycle, postgres_0004_release_proof, smoke_live


client = TestClient(app)
RELEASE_SHA = "a" * 40


class FakeDatabase:
    def __init__(self, revisions=None, *, unavailable=False):
        self.revisions = [EXPECTED_SCHEMA_REVISION] if revisions is None else revisions
        self.unavailable = unavailable

    def execute(self, statement):
        if self.unavailable:
            raise RuntimeError("database unavailable")
        return object()

    def scalars(self, statement):
        if self.unavailable:
            raise RuntimeError("database unavailable")
        return iter(self.revisions)


class FakeLiveClient:
    def __init__(self, *, release_sha=RELEASE_SHA, schema=EXPECTED_SCHEMA_REVISION):
        self.release_sha = release_sha
        self.schema = schema
        self.calls = []

    @staticmethod
    def _a2a(payload):
        raw = payload["params"]["message"]["parts"][0]["text"]
        if raw == "help":
            result = {
                "action": "first_contact",
                "membership_required": False,
                "join_is_optional": True,
            }
        else:
            result = {"join_over_a2a": {"action": "join_aion"}}
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {"message": {"parts": [{"text": json.dumps(result)}]}},
        }

    def request(self, method, path, payload=None, headers=None):
        self.calls.append((method, path, payload, headers or {}))
        if path == "/stats":
            return 200, {"agents_raw_rows": 7}
        if path == "/health":
            return 200, {
                "status": "ok",
                "version": "0.7.1",
                "a2a_runtime": "mounted",
                "release_sha": self.release_sha,
                "release_source": "render_git_commit",
            }
        if path == "/readiness":
            checks = {
                "database": True,
                "a2a_runtime": True,
                "schema_current": self.schema == EXPECTED_SCHEMA_REVISION,
                "package_3b_config": True,
                "release_identity": True,
            }
            return 200, {
                "status": "ready" if all(checks.values()) else "not_ready",
                "checks": checks,
                "expected_schema_revision": EXPECTED_SCHEMA_REVISION,
                "database_schema_revision": self.schema,
                "schema_current": checks["schema_current"],
                "release_sha": self.release_sha,
            }
        if path == "/.well-known/agent-card.json":
            return 200, {"supportedInterfaces": [{"protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]}
        if path in {"/.well-known/aion.json", "/llms.txt", "/openapi.json", "/funnel", "/a2a/status"}:
            return 200, {}
        if path == "/utility/query":
            return 200, {
                "action": "live_utility",
                "membership_required": False,
                "network_fetch_performed": False,
                "results": [{"source": {}, "evidence": {}, "freshness": {}, "compatibility": {}}],
            }
        if path == "/a2a/v1":
            return 200, self._a2a(payload)
        if path in {"/actions/verify-callability", "/learning/evidence"}:
            return 401, {"detail": "authentication required"}
        if path == "/mcp":
            rpc_method = payload["method"]
            if rpc_method == "server/discover":
                result = {"supportedVersions": ["2026-07-28"]}
            elif rpc_method == "tools/list":
                result = {"tools": [{"name": name} for name in (
                    "get_live_utility", "verify_external_callability",
                    "get_action_status", "submit_learning_evidence",
                )]}
            else:
                result = {"structuredContent": {
                    "action": "live_utility", "membership_required": False,
                    "network_fetch_performed": False,
                }}
            return 200, {"jsonrpc": "2.0", "id": payload["id"], "result": result}
        raise AssertionError((method, path))


def test_release_identity_precedence_validation_and_no_environment_leak(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "A" * 40)
    monkeypatch.setenv("AION_RELEASE_SHA", "b" * 40)
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret.invalid/leak")
    assert release_identity() == {
        "release_sha": "a" * 40,
        "release_source": "render_git_commit",
    }
    assert "secret" not in json.dumps(release_identity())
    monkeypatch.setenv("RENDER_GIT_COMMIT", "garbage")
    assert release_identity() == {
        "release_sha": None,
        "release_source": "render_git_commit_invalid",
    }
    monkeypatch.delenv("RENDER_GIT_COMMIT")
    assert release_identity()["release_source"] == "aion_release_sha"
    monkeypatch.delenv("AION_RELEASE_SHA")
    assert release_identity() == {"release_sha": None, "release_source": "unknown"}


def test_health_is_cheap_and_unknown_release_is_explicit(monkeypatch):
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("AION_RELEASE_SHA", raising=False)
    monkeypatch.setattr(safe_http, "fetch_bytes", lambda *a, **k: pytest.fail("health performed network work"))
    monkeypatch.setattr(learning_engine, "run_learning_cycle", lambda *a, **k: pytest.fail("health ran learning"))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["release_sha"] is None
    assert response.json()["release_source"] == "unknown"


@pytest.mark.parametrize("revisions", [["0008_action_outcome_evidence"], ["unexpected_revision"], []])
def test_readiness_rejects_behind_unexpected_or_missing_schema(revisions):
    payload = _readiness_payload(FakeDatabase(revisions), a2a_status="mounted")
    assert payload["status"] == "not_ready"
    assert payload["checks"]["database"] is True
    assert payload["checks"]["schema_current"] is False
    assert payload["schema_current"] is False


def test_readiness_rejects_database_unavailable_and_a2a_unmounted():
    unavailable = _readiness_payload(FakeDatabase(unavailable=True), a2a_status="mounted")
    assert unavailable["status"] == "not_ready"
    assert unavailable["checks"]["database"] is False
    unmounted = _readiness_payload(FakeDatabase(), a2a_status="not_mounted")
    assert unmounted["status"] == "not_ready"
    assert unmounted["checks"]["a2a_runtime"] is False


def test_readiness_requires_valid_identity_on_managed_runtime(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("AION_RELEASE_SHA", raising=False)
    missing = _readiness_payload(FakeDatabase(), a2a_status="mounted")
    assert missing["status"] == "not_ready"
    assert missing["checks"]["release_identity"] is False
    monkeypatch.setenv("AION_RELEASE_SHA", RELEASE_SHA)
    valid = _readiness_payload(FakeDatabase(), a2a_status="mounted")
    assert valid["status"] == "ready"
    assert valid["checks"]["release_identity"] is True


def test_readiness_http_is_503_when_schema_is_not_current():
    def behind_database():
        yield FakeDatabase(["0008_action_outcome_evidence"])

    app.dependency_overrides[get_db] = behind_database
    try:
        response = client.get("/readiness")
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert response.json()["schema_current"] is False


def test_current_readiness_has_no_migration_network_learning_or_secret_side_effect(monkeypatch):
    import alembic.command

    monkeypatch.setattr(alembic.command, "upgrade", lambda *a, **k: pytest.fail("readiness migrated"))
    monkeypatch.setattr(safe_http, "fetch_bytes", lambda *a, **k: pytest.fail("readiness used network"))
    monkeypatch.setattr(learning_engine, "run_learning_cycle", lambda *a, **k: pytest.fail("readiness ran learning"))
    monkeypatch.setenv("DATABASE_URL", "postgresql://private.invalid/release_gate_marker")
    response = client.get("/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database_schema_revision"] == EXPECTED_SCHEMA_REVISION
    assert body["schema_current"] is True
    assert "release_gate_marker" not in response.text and "private.invalid" not in response.text


def test_live_smoke_checks_stack_without_join_action_or_evidence_mutation():
    fake = FakeLiveClient()
    result = smoke_live.run_live_smoke(fake, RELEASE_SHA.upper())
    assert result == {
        "status": "pass",
        "release_sha": RELEASE_SHA,
        "schema_revision": EXPECTED_SCHEMA_REVISION,
        "membership_created": False,
        "external_action_dispatched": False,
        "evidence_submitted": False,
        "learning_cycle_run": False,
    }
    paths = [(method, path) for method, path, _, _ in fake.calls]
    assert ("POST", "/agents") not in paths
    assert paths.count(("POST", "/actions/verify-callability")) == 1
    assert paths.count(("POST", "/learning/evidence")) == 1
    assert all(not headers.get("Authorization") for _, _, _, headers in fake.calls)


def test_live_smoke_rejects_release_or_schema_mismatch():
    with pytest.raises(AssertionError):
        smoke_live.run_live_smoke(FakeLiveClient(release_sha="b" * 40), RELEASE_SHA)
    with pytest.raises(AssertionError):
        smoke_live.run_live_smoke(FakeLiveClient(schema="0008_action_outcome_evidence"), RELEASE_SHA)
    with pytest.raises(SystemExit, match="exact 40-hex"):
        smoke_live.run_live_smoke(FakeLiveClient(), "main")


def test_learning_plan_has_zero_side_effects_and_exact_policy(monkeypatch, capsys):
    with SessionLocal() as db:
        before = (
            db.scalar(select(func.count()).select_from(models.LearningRun)),
            db.scalar(select(func.count()).select_from(models.LearningSourceWatchState)),
        )
    monkeypatch.setattr(learning_cycle, "run_learning_cycle", lambda *a, **k: pytest.fail("plan ran cycle"))
    monkeypatch.setattr(safe_http, "fetch_bytes", lambda *a, **k: pytest.fail("plan used network"))
    assert learning_cycle.main(["--plan"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["watched_source_ids"] == [
        "official-a2a-protocol-release", "official-mcp-specification-release"
    ]
    assert plan["maximum_watched_sources"] == 2
    assert plan["maximum_outbound_attempts_per_cycle"] == 4
    assert plan["maximum_response_bytes_per_source"] == 256_000
    assert plan["maximum_paid_external_spend"] == 0
    assert plan["paid_external_execution_enabled"] is False
    assert plan["side_effects"] is False
    with SessionLocal() as db:
        after = (
            db.scalar(select(func.count()).select_from(models.LearningRun)),
            db.scalar(select(func.count()).select_from(models.LearningSourceWatchState)),
        )
    assert after == before


def test_postgres_0004_proof_refuses_non_gate_or_non_loopback_database(monkeypatch):
    monkeypatch.delenv("AION_POSTGRES_GATE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user@db.example/aion")
    with pytest.raises(SystemExit, match="AION_POSTGRES_GATE"):
        postgres_0004_release_proof._guard_disposable_database()
    monkeypatch.setenv("AION_POSTGRES_GATE", "1")
    with pytest.raises(SystemExit, match="loopback"):
        postgres_0004_release_proof._guard_disposable_database()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1/not_the_gate")
    with pytest.raises(SystemExit, match="aion_package4_legacy"):
        postgres_0004_release_proof._guard_disposable_database()
