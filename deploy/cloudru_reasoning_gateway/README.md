# AION Cloud.ru Reasoning Gateway

Purpose: bridge the existing AION reasoning adapter to Cloud.ru Foundation
Models when the Render production service cannot establish a direct connection
to foundation-models.api.cloud.ru.

This component is transport only. It contains no agent logic, acquisition
strategy, persistent memory, payment authority, or discovery logic.

## Runtime contract

Public endpoints:

- GET /health — secret-free health/configuration truth.
- POST /v1/chat/completions — Bearer-authenticated, non-streaming proxy.

Required environment variables in Cloud.ru Container Apps:

- CLOUDRU_FOUNDATION_API_KEY — Foundation Models API key. Keep only in Cloud.ru.
- AION_GATEWAY_TOKEN — random shared token used by Render.
- AION_GATEWAY_ALLOWED_MODELS — optional comma-separated allowlist.
- AION_GATEWAY_UPSTREAM_TIMEOUT_SECONDS — optional, default 90.

Optional:

- CLOUDRU_FOUNDATION_BASE_URL — defaults to
  https://foundation-models.api.cloud.ru/v1.

Default allowed models:

- ai-sage/GigaChat3-10B-A1.8B
- openai/gpt-oss-120b

## Container Apps settings

- Build for linux/amd64.
- Port: 8080.
- Public address: enabled.
- Minimum instances: 0.
- Maximum instances: 1.

## Render settings after gateway deployment

Set:

- AION_REASONING_PROVIDER=cloudru_chat_completions
- AION_REASONING_BASE_URL=https://<container-public-url>/v1
- AION_REASONING_API_KEY=<same AION_GATEWAY_TOKEN>
- AION_AGENT_MINDS_ENABLED=1

Keep CLOUDRU_FOUNDATION_API_KEY out of Render.
