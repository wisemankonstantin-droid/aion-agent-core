from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class CapabilityIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    verification: str = "declared"

class AgentCreate(BaseModel):
    external_id: str = Field(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9._:@/\-]+$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=5000)
    endpoint: Optional[str] = Field(default=None, max_length=500)
    protocol: str = Field(default="REST", min_length=1, max_length=40)
    acquisition_source: Optional[str] = Field(default=None, max_length=120)
    referrer: Optional[str] = Field(default=None, max_length=160)
    owner_required: bool = False
    capabilities: List[CapabilityIn] = Field(default_factory=list, max_length=100)

class AgentOut(BaseModel):
    id: int
    external_id: str
    name: str
    description: str
    endpoint: Optional[str]
    protocol: str
    acquisition_source: Optional[str]
    referrer: Optional[str]
    owner_required: bool
    reputation: float
    trust_level: str
    model_config = {"from_attributes": True}

class AgentJoinOut(BaseModel):
    agent: AgentOut
    agent_key: str
    message: str = "Store this key securely. AION will not return it again."
    next_actions: List[str] = Field(default_factory=lambda: [
        "GET /onboarding",
        "PUT /agents/me/capabilities",
        "POST /offers or POST /needs",
        "GET /matches/{need_id}",
        "return later to check new matches and opportunities",
    ])

class NeedCreate(BaseModel):
    capability: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=5000)

class OfferCreate(BaseModel):
    capability: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=5000)
    price_hint: Optional[str] = Field(default=None, max_length=120)

class InteractionCreate(BaseModel):
    provider_agent_id: int = Field(gt=0)
    need_id: Optional[int] = Field(default=None, gt=0)

class PaymentIntentCreate(BaseModel):
    purpose: str = Field(min_length=1, max_length=120)
    amount: str = Field(min_length=1, max_length=120)
    protocol: str = Field(default="x402", min_length=1, max_length=40)

class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=160)
    description: Optional[str] = Field(default=None, max_length=5000)
    endpoint: Optional[str] = Field(default=None, max_length=500)
    protocol: Optional[str] = Field(default=None, min_length=1, max_length=40)


class InteractionUpdate(BaseModel):
    result: Literal["completed", "cancelled", "failed"] = "completed"
    score: Optional[float] = Field(default=None, ge=0, le=5)
