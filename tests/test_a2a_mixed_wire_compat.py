import json
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import A2A_RUNTIME, app


client = TestClient(app)


def test_mislabeled_legacy_a2a_message_kind_is_normalized_on_v1_ingress():
    if A2A_RUNTIME.get("status") != "mounted":
        pytest.skip("a2a-sdk not installed in this local test environment")

    payload = {
        "jsonrpc": "2.0",
        "id": "legacy-kind-regression",
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "messageId": "msg-" + uuid.uuid4().hex,
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": "help",
                    }
                ],
            }
        },
    }

    response = client.post(
        "/a2a/v1",
        json=payload,
        headers={"A2A-Version": "1.0"},
    )

    assert response.status_code == 200, response.text
    rpc = response.json()
    assert "error" not in rpc, rpc

    result = rpc["result"]
    answer = json.loads(result["message"]["parts"][0]["text"])
    assert answer["action"] == "first_contact"
    assert answer["membership_required"] is False

def test_mislabeled_legacy_a2a_part_type_is_normalized_on_v1_ingress():
    if A2A_RUNTIME.get("status") != "mounted":
        pytest.skip("a2a-sdk not installed in this local test environment")

    payload = {
        "jsonrpc": "2.0",
        "id": "legacy-part-type-regression",
        "method": "message/send",
        "params": {
            "message": {
                "messageId": "msg-" + uuid.uuid4().hex,
                "role": "user",
                "parts": [
                    {
                        "type": "text",
                        "text": "help",
                    }
                ],
            }
        },
    }

    response = client.post(
        "/a2a/v1",
        json=payload,
        headers={"A2A-Version": "1.0"},
    )

    assert response.status_code == 200, response.text
    rpc = response.json()
    assert "error" not in rpc, rpc

    result = rpc["result"]
    answer = json.loads(result["message"]["parts"][0]["text"])
    assert answer["action"] == "first_contact"
    assert answer["membership_required"] is False

