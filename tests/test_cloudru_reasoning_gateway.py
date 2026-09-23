from __future__ import annotations

import importlib
import json

import httpx
from fastapi.testclient import TestClient


gateway = importlib.import_module("deploy.cloudru_reasoning_gateway.app")
client = TestClient(gateway.app)


def _env(monkeypatch):
    monkeypatch.setenv("AION_GATEWAY_TOKEN", "gateway-secret")
    monkeypatch.setenv("CLOUDRU_FOUNDATION_API_KEY", "cloudru-secret")
    monkeypatch.setenv(
        "AION_GATEWAY_ALLOWED_MODELS",
        "ai-sage/GigaChat3-10B-A1.8B,openai/gpt-oss-120b",
    )


def test_health_never_exposes_secrets(monkeypatch):
    _env(monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["configured"] is True
    serialized = json.dumps(data)
    assert "gateway-secret" not in serialized
    assert "cloudru-secret" not in serialized


def test_gateway_requires_its_own_bearer_token(monkeypatch):
    _env(monkeypatch)
    response = client.post(
        "/v1/chat/completions",
        json={"model": "ai-sage/GigaChat3-10B-A1.8B", "messages": []},
    )
    assert response.status_code == 401


def test_gateway_forwards_only_allowed_non_streaming_model(monkeypatch):
    _env(monkeypatch)
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [
                    {"message": {"content": '{"decision_summary":"ok"}'}}
                ]
            }

    def fake_post(url, *, headers, json, timeout):
        seen.update(url=url, headers=dict(headers), json=json, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(gateway.httpx, "post", fake_post)
    body = {
        "model": "ai-sage/GigaChat3-10B-A1.8B",
        "messages": [{"role": "user", "content": "safe observation"}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "x"}},
    }
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gateway-secret"},
        json=body,
    )

    assert response.status_code == 200
    assert seen["url"] == (
        "https://foundation-models.api.cloud.ru/v1/chat/completions"
    )
    assert seen["headers"]["Authorization"] == "Bearer cloudru-secret"
    assert seen["json"] == body
    assert "gateway-secret" not in json.dumps(seen["json"])
    assert "cloudru-secret" not in json.dumps(seen["json"])


def test_gateway_rejects_unknown_model_and_streaming(monkeypatch):
    _env(monkeypatch)
    unknown = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gateway-secret"},
        json={"model": "unapproved/model", "messages": []},
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "model_not_allowed"

    streaming = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gateway-secret"},
        json={
            "model": "openai/gpt-oss-120b",
            "messages": [],
            "stream": True,
        },
    )
    assert streaming.status_code == 400
    assert streaming.json()["detail"] == "streaming_not_supported"


def test_gateway_maps_upstream_timeout_without_secret_leak(monkeypatch):
    _env(monkeypatch)

    def fail(*args, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(gateway.httpx, "post", fail)
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer gateway-secret"},
        json={"model": "openai/gpt-oss-120b", "messages": []},
    )
    assert response.status_code == 504
    serialized = response.text
    assert "gateway-secret" not in serialized
    assert "cloudru-secret" not in serialized
