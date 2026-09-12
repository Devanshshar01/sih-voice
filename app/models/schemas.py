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
    # Identity evidence: raw similarity to the enrolled reference (None when
    # no reference exists) and the derived risk term (1 - similarity).
    speaker_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    identity_mismatch: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    hard_trigger: Optional[bool] = None
    degraded: Optional[dict] = None
    fusion: Optional[dict] = None
    # Contextual ASR/intent evidence (SIH multilingual phase). Optional so
    # legacy frames without these keys stay valid.
    transcript: Optional[str] = None
    detected_language: Optional[str] = None
    intent_risks: Optional[List[dict]] = None
    # VAD stage telemetry (SIH Phase 1). Present on every streaming message.
    vad_active: Optional[bool] = None
    vad_coverage: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    vad_backend: Optional[str] = None
    vad_skipped: Optional[bool] = None
    malformed_frames: Optional[int] = None
    # Per-window stage timings (ms) and rolling p50/p95 per stage.
    latency_ms: Optional[dict] = None
    latency_stats: Optional[dict] = None


class AudioAnalyzeResponse(BaseModel):
    classification: str  # AI_GENERATED | HUMAN
    confidence: float
    explanation: str


class SpeakerEnrollRequest(BaseModel):
    speaker_id: str = Field(..., min_length=1)
    # Optional tenant/user scoping (persistent vault). Defaults keep the
    # original single-tenant contract working unchanged.
    tenant_id: str = Field(default="default", min_length=1)
    display_name: Optional[str] = None


class SpeakerEnrollResponse(BaseModel):
    speaker_id: str
    embedding_dim: int
    vault_size: int
    match_threshold: float
    method: str
    checkpoint_status: str
    enrolled: bool
    # Persistent vault additions (optional fields keep old clients working).
    tenant_id: str = "default"
    sample_count: int = 1
    enrollment_version: int = 1
    model_version: str = ""


class SpeakerMatchResponse(BaseModel):
    speaker_id: Optional[str] = None
    # None when the vault has no reference: identity evidence is unknown
    # (neutral in fusion), not a zero-similarity mismatch.
    speaker_match_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    matched: bool
    vault_size: int
    method: str
    checkpoint_status: str
    # Verification contract additions: the threshold and model version that
    # produced the decision (auditability without exposing embeddings).
    threshold: Optional[float] = None
    model_version: Optional[str] = None
    # True when enrollments exist but were enrolled with a different encoder
    # version, so no similarity was computed.
    model_version_mismatch: Optional[bool] = None


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
