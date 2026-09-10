from datetime import datetime
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator
from typing import Dict, Optional, List, Literal
from .machine_journey import post_join_next_actions

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
    next_actions: List[str] = Field(default_factory=post_join_next_actions)

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


class UtilityCompatibilityContext(BaseModel):
    supported_protocols: List[str] = Field(default_factory=list, max_length=8)
    supported_protocol_versions: Dict[str, List[str]] = Field(
        default_factory=dict,
        max_length=8,
    )
    capabilities: List[str] = Field(default_factory=list, max_length=16)
    auth_modes: List[str] = Field(default_factory=list, max_length=8)
    permissions: List[str] = Field(default_factory=list, max_length=16)
    payment_methods: List[str] = Field(default_factory=list, max_length=8)
    constraints: List[str] = Field(default_factory=list, max_length=16)

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    @field_validator(
        "supported_protocols",
        "capabilities",
        "auth_modes",
        "permissions",
        "payment_methods",
        "constraints",
    )
    @classmethod
    def bounded_items(cls, values: List[str]) -> List[str]:
        for value in values:
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError("context list items must be non-empty strings of at most 200 characters")
        return values

    @field_validator("supported_protocol_versions")
    @classmethod
    def bounded_versions(cls, values: Dict[str, List[str]]) -> Dict[str, List[str]]:
        for protocol, versions in values.items():
            if not protocol.strip() or len(protocol) > 40:
                raise ValueError("protocol keys must be 1 to 40 characters")
            if len(versions) > 16:
                raise ValueError("at most 16 versions may be supplied per protocol")
            for version in versions:
                if not isinstance(version, str) or not version.strip() or len(version) > 80:
                    raise ValueError("versions must be non-empty strings of at most 80 characters")
        return values


class UtilityQuery(BaseModel):
    subject: Literal["all", "a2a", "mcp"] = "all"
    context: UtilityCompatibilityContext = Field(
        default_factory=UtilityCompatibilityContext
    )

    model_config = {"extra": "forbid"}


class VerifyCallabilityRequest(BaseModel):
    query: str = Field(min_length=1, max_length=128)
    candidate_identifier: Optional[str] = Field(default=None, min_length=1, max_length=240)
    authorize_external_contact: bool

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    @field_validator("query", "candidate_identifier")
    @classmethod
    def no_control_characters(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and any(ord(character) < 32 for character in value):
            raise ValueError("control characters are not allowed")
        return value


EvidenceCategory = Literal[
    "capability_claim",
    "endpoint_change",
    "provider_failure",
    "compatibility_issue",
    "missing_capability",
    "source_suggestion",
    "pricing_observation",
]


class AgentEvidenceSubmission(BaseModel):
    category: EvidenceCategory
    subject_key: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=2000)
    reference_url: Optional[str] = Field(default=None, max_length=1000)
    provider_identifier: Optional[str] = Field(default=None, max_length=240)
    protocol: Optional[str] = Field(default=None, max_length=40)
    failure_class: Optional[Literal[
        "no_result",
        "capability_not_found",
        "incompatible",
        "rate_limited",
        "unavailable",
        "endpoint_unreachable",
        "protocol_failure",
        "invocation_failed",
        "verification_failed",
        "stale_evidence",
    ]] = None
    observed_at: Optional[datetime] = None

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    @field_validator("description")
    @classmethod
    def bounded_description(cls, value: str) -> str:
        if value is not None and any(ord(character) < 32 and character not in "\n\t" for character in value):
            raise ValueError("control characters are not allowed")
        return value

    @field_validator("subject_key", "reference_url", "provider_identifier", "protocol")
    @classmethod
    def no_control_characters(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and any(ord(character) < 32 for character in value):
            raise ValueError("control characters are not allowed")
        return value

    @field_validator("reference_url")
    @classmethod
    def passive_reference_only(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("reference_url must be an absolute HTTP(S) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("reference_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("reference_url must not contain query parameters or fragments")
        return value

    @field_validator("observed_at")
    @classmethod
    def observed_at_must_be_aware(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("observed_at must include a timezone")
        return value


class Package5VuoSubmission(BaseModel):
    action_id: str = Field(min_length=36, max_length=36)
    goal_kind: Literal["verify_external_agent_callability"]
    product_goal: Literal["find_verify_invoke_external_a2a_agent"]
    delivered_outcome: Literal["verified_external_agent_callability"]
    usefulness_confirmed: Literal[True]
    usefulness_evidence: Literal["requester_confirms_goal_was_useful"]

    model_config = {"str_strip_whitespace": True, "extra": "forbid"}

    @field_validator("action_id", "product_goal", "delivered_outcome", "usefulness_evidence")
    @classmethod
    def package5_no_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 and character not in "\n\t" for character in value):
            raise ValueError("control characters are not allowed")
        return value
