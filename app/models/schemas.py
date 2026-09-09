"""
Pydantic request/response schemas for the SatyaVoice API surface.
Field shapes mirror the API design table in the prototype blueprint exactly,
so frontend and backend can be built in parallel against this contract.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class CallStartRequest(BaseModel):
    caller_id: str
    recipient_id: str


class CallStartResponse(BaseModel):
    call_id: str
    status: str
    ws_url: str


class RiskTelemetry(BaseModel):
    timestamp: float
    risk_score: int = Field(..., ge=0, le=100)
    acoustic_score: float = Field(..., ge=0.0, le=1.0)
    intent_score: float = Field(..., ge=0.0, le=1.0)
    status: str  # ALLOW | WARN | LOCK_VERIFY
    rationale: List[str] = Field(default_factory=list)


class AudioAnalyzeResponse(BaseModel):
    classification: str  # AI_GENERATED | HUMAN
    confidence: float
    explanation: str


class SpeakerEnrollRequest(BaseModel):
    speaker_id: str = Field(..., min_length=1)


class SpeakerEnrollResponse(BaseModel):
    speaker_id: str
    embedding_dim: int
    vault_size: int
    match_threshold: float
    method: str
    checkpoint_status: str
    enrolled: bool


class SpeakerMatchResponse(BaseModel):
    speaker_id: Optional[str] = None
    speaker_match_score: float
    matched: bool
    vault_size: int
    method: str
    checkpoint_status: str


class RiskTimelinePoint(BaseModel):
    t: int
    score: int


class CallRiskResponse(BaseModel):
    call_id: str
    current_risk_score: int
    timeline: List[RiskTimelinePoint]


class VerificationChallengeRequest(BaseModel):
    call_id: str
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


class VerificationRequest(BaseModel):
    call_id: str


class VerificationRequestResponse(BaseModel):
    code: str
    expires_in_seconds: int
    delivery_channel: str


class VerificationChallengeResponse(BaseModel):
    success: bool
    new_risk_state: str
    message: str


class CallActionRequest(BaseModel):
    call_id: str
    action: Literal["WIRE_TRANSFER"]
    amount: Optional[float] = Field(default=None, gt=0, le=10_000_000)


class CallActionResponse(BaseModel):
    executed: bool
    message: str
