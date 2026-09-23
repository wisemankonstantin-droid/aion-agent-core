"""Minimal Cloud.ru-local reasoning gateway for AION.

This is a transport bridge only. It keeps the Cloud.ru Foundation Models key
inside Cloud.ru and exposes a narrow authenticated OpenAI-compatible
/chat/completions endpoint to the existing AION reasoning adapter.

No prompts or responses are logged. The gateway cannot initiate network writes
other than forwarding one bounded request to Foundation Models.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse


DEFAULT_UPSTREAM_BASE = "https://foundation-models.api.cloud.ru/v1"
DEFAULT_ALLOWED_MODELS = (
    "ai-sage/GigaChat3-10B-A1.8B",
    "openai/gpt-oss-120b",
)
MAX_REQUEST_BYTES = 64 * 1024

app = FastAPI(title="AION Cloud.ru Reasoning Gateway", version="1")


def _secret(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _allowed_models() -> set[str]:
    raw = _secret("AION_GATEWAY_ALLOWED_MODELS")
    if not raw:
        return set(DEFAULT_ALLOWED_MODELS)
    return {item.strip() for item in raw.split(",") if item.strip()}


def _upstream_base() -> str:
    return (_secret("CLOUDRU_FOUNDATION_BASE_URL") or DEFAULT_UPSTREAM_BASE).rstrip("/")


def _timeout_seconds() -> float:
    try:
        value = float(_secret("AION_GATEWAY_UPSTREAM_TIMEOUT_SECONDS") or "90")
    except ValueError:
        value = 90.0
    return max(10.0, min(value, 180.0))


def _require_gateway_auth(authorization: str | None) -> None:
    expected = _secret("AION_GATEWAY_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="gateway_not_configured")
    prefix = "Bearer "
    supplied = ""
    if authorization and authorization.startswith(prefix):
        supplied = authorization[len(prefix) :]
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "aion-cloudru-reasoning-gateway",
        "upstream": "cloudru_foundation_models",
        "configured": bool(_secret("CLOUDRU_FOUNDATION_API_KEY"))
        and bool(_secret("AION_GATEWAY_TOKEN")),
        "allowed_models": sorted(_allowed_models()),
        "request_logging": False,
        "secret_exposure": False,
    }


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: str | None = Header(default=None),
):
    _require_gateway_auth(authorization)

    cloudru_key = _secret("CLOUDRU_FOUNDATION_API_KEY")
    if not cloudru_key:
        raise HTTPException(status_code=503, detail="upstream_not_configured")

    raw = await request.body()
    if len(raw) > MAX_REQUEST_BYTES:
        raise HTTPException(status_code=413, detail="request_too_large")
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid_json") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid_body")

    model = str(body.get("model") or "").strip()
    if model not in _allowed_models():
        raise HTTPException(status_code=400, detail="model_not_allowed")

    # AION currently uses non-streaming structured outputs. Fail closed if a
    # caller tries to turn this bridge into a generic streaming proxy.
    if body.get("stream"):
        raise HTTPException(status_code=400, detail="streaming_not_supported")

    try:
        response = httpx.post(
            f"{_upstream_base()}/chat/completions",
            headers={
                "Authorization": f"Bearer {cloudru_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=_timeout_seconds(),
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="upstream_timeout") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="upstream_connect_error") from exc

    # Return only the upstream JSON body. Never echo either secret.
    try:
        payload = response.json()
    except ValueError:
        payload = {"error": {"message": "upstream_non_json_response"}}

    return JSONResponse(status_code=response.status_code, content=payload)
