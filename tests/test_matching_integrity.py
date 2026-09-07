import uuid

from app import models
from app.db import SessionLocal
from app.services.matching import find_matches


def _agent(db, name, endpoint=None, trust="declared", reputation=0.0):
    token = uuid.uuid4().hex
    agent = models.Agent(
        external_id="matching-" + token,
        name=name + token[:6],
        endpoint=endpoint,
        protocol="A2A" if endpoint else "REST",
        api_key_hash=token * 2,
        trust_level=trust,
        reputation=reputation,
    )
    db.add(agent)
    db.flush()
    return agent


def test_unverified_endpoint_is_neutral_and_not_directly_callable():
    with SessionLocal() as db:
        requester = _agent(db, "Requester")
        direct = _agent(db, "Direct", endpoint="https://provider.example/a2a")
        internal = _agent(db, "Internal")
        need = models.Need(
            agent_id=requester.id,
            capability="analysis",
            description="Need analysis",
        )
        db.add(need)
        db.flush()
        db.add_all(
            [
                models.Offer(agent_id=direct.id, capability="analysis", description="Direct"),
                models.Offer(agent_id=internal.id, capability="analysis", description="Internal"),
            ]
        )
        db.commit()
        first = find_matches(db, need.id)
        second = find_matches(db, need.id)
        direct_id = direct.id
        internal_id = internal.id

    by_provider = {row["provider"]["agent_id"]: row for row in first}
    direct_match = by_provider[direct_id]
    internal_match = by_provider[internal_id]
    assert direct_match["match_score"] == internal_match["match_score"]
    assert direct_match["match_score"] == 0.85
    assert direct_match["provider"]["route"] == {
        "type": "declared_direct_endpoint",
        "endpoint": "https://provider.example/a2a",
        "protocol": "A2A",
        "availability": "declared_unverified",
        "directly_callable": False,
    }
    assert direct_match["integrity"]["endpoint_liveness_verified"] is False
    assert [row["match_id"] for row in first] == [row["match_id"] for row in second]


def test_trust_level_does_not_imply_endpoint_liveness_or_callability():
    with SessionLocal() as db:
        requester = _agent(db, "Requester")
        provider = _agent(
            db,
            "Trusted Provider",
            endpoint="https://trusted.example/a2a",
            trust="verified",
        )
        need = models.Need(
            agent_id=requester.id,
            capability="planning",
            description="Need planning",
        )
        db.add(need)
        db.flush()
        db.add(models.Offer(agent_id=provider.id, capability="planning", description="Planning"))
        db.commit()
        match = find_matches(db, need.id)[0]

    assert match["match_score"] == 0.9
    assert match["integrity"]["endpoint_liveness_verified"] is False
    assert match["provider"]["route"]["directly_callable"] is False
    assert match["provider"]["route"]["availability"] == "declared_unverified"
    assert {reason["type"] for reason in match["reasons"]} == {
        "exact_capability",
        "trust_evidence",
        "active_offer",
    }
