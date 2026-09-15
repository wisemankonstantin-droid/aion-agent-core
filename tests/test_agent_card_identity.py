from a2a.types import AgentCard
from a2a.utils.proto_utils import validate_proto_required_fields
from fastapi.testclient import TestClient
from google.protobuf.json_format import ParseDict

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

    # A2A SDK 1.x types are Protobuf messages, not Pydantic models. Parse the
    # hand-authored ProtoJSON card and run the SDK's required-field validator.
    parsed = ParseDict(card, AgentCard())
    validate_proto_required_fields(parsed)
    assert parsed.provider.organization == "AION SUPREME"
    assert parsed.provider.url == base_url


def test_well_known_agent_card_exposes_provider_identity_without_auth_claims():
    client = TestClient(app)
    response = client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    card = response.json()
    assert card["provider"]["organization"] == "AION SUPREME"
    assert card["securitySchemes"] == {}
    assert card["securityRequirements"] == []
