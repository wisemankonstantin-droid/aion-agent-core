from a2a.types import AgentCard
from fastapi.testclient import TestClient

from app.agent_card import get_agent_card
from app.main import app


def test_agent_card_declares_truthful_provider_and_public_security():
    base_url = "https://aion.example"
    card = get_agent_card(base_url)

    assert card["provider"] == {
        "organization": "AION SUPREME",
        "url": base_url,
    }
    assert card["securitySchemes"] == {}
    assert card["securityRequirements"] == []

    # Keep the hand-authored public card inside the official A2A v1 schema.
    parsed = AgentCard.model_validate(card)
    assert parsed.provider is not None
    assert parsed.provider.organization == "AION SUPREME"


def test_well_known_agent_card_exposes_provider_identity_without_auth_claims():
    client = TestClient(app)
    response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    card = response.json()
    assert card["provider"]["organization"] == "AION SUPREME"
    assert card["securitySchemes"] == {}
    assert card["securityRequirements"] == []
