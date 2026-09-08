"""
Pydantic request/response schemas for the VoiceTrust API surface.
Field shapes mirror the API design table in the prototype blueprint exactly,
so frontend and backend can be built in parallel against this contract.
"""
from typing import List, Optional

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
    rationale: List[str] = []


class AudioAnalyzeResponse(BaseModel):
    classification: str  # AI_GENERATED | HUMAN
    confidence: float
    explanation: str


class RiskTimelinePoint(BaseModel):
    t: int
    score: int


class CallRiskResponse(BaseModel):
    call_id: str
    current_risk_score: int
    timeline: List[RiskTimelinePoint]


class VerificationChallengeRequest(BaseModel):
    call_id: str
    code: str


class VerificationChallengeResponse(BaseModel):
    success: bool
    new_risk_state: str
    message: str


class CallActionRequest(BaseModel):
    call_id: str
    action: str  # e.g. "WIRE_TRANSFER"
    amount: Optional[float] = None


class CallActionResponse(BaseModel):
    executed: bool
    message: str
