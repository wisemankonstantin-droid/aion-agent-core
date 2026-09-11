from sqlalchemy.orm import Session
from ..models import PaymentIntent

def create_payment_intent(db: Session, agent_id: int, purpose: str, amount: str, protocol: str):
    # Adapter point. In production this can be connected to x402, a normal PSP,
    # crypto rails, or owner-authorized payment flows.
    intent = PaymentIntent(
        agent_id=agent_id,
        purpose=purpose,
        amount=amount,
        protocol=protocol,
        status="created",
    )
    db.add(intent)
    db.commit()
    db.refresh(intent)
    return intent

def machine_payment_requirements(intent: PaymentIntent):
    if intent.protocol.lower() == "x402":
        return {
            "status": 402,
            "payment_protocol": "x402",
            "purpose": intent.purpose,
            "amount": intent.amount,
            "note": "Legacy intent-only scaffolding: not authorization, reserve, payment, settlement, revenue, or Package 6A funding evidence. A future verified rail adapter is required."
        }
    return {
        "status": 200,
        "payment_protocol": intent.protocol,
        "purpose": intent.purpose,
        "amount": intent.amount,
        "note": "Legacy intent-only scaffolding; no payment or settlement is claimed.",
    }
