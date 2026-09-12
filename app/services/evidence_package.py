"""Canonical forensic evidence package (SIH forensic layer).

One authoritative, versioned schema for a flagged-call evidence package. The
backend is the sole author of evidence packages: the frontend only submits the
raw call identifiers, and the package is built exclusively from persisted
backend state (sessions, risk events, evidence payloads). The frontend PDF is
generated from the immutable stored package — never from ad-hoc UI state.

Privacy: the package contains hashes and derived metrics only. Raw audio and
full transcripts are never part of the package (transcripts contribute a
SHA-256 digest, not the text).

Integrity properties (see README "Forensic evidence & integrity"):
  * evidence_hash       = SHA-256 over the canonical JSON of the full package
  * ledger chain        = each record links previous_record_hash -> record_hash
                          (global, append-only, spans all packages in order)
  * local_chain_root    = final chain root covering this package's record(s)
  * blockchain anchor   = an external witness for local_chain_root
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "forensic-v1"

# Package format label. Deliberately NOT phrased as a legal certificate: the
# system establishes technical integrity of derived evidence, not admissibility.
PACKAGE_FORMAT = "satyavoice-technical-integrity-evidence-package"


def canonical_json(data: Any) -> str:
    """Deterministic serialization used for every hash in the evidence layer.

    Sort keys, no whitespace, preserve non-ASCII (Indic transcripts digest
    consistently regardless of ensure_ascii), fixed float formatting via JSON.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_hash(data: Any) -> str:
    return sha256_hex(canonical_json(data))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelProvenance(BaseModel):
    """Which model/artifact produced the derived evidence."""

    detector_mode: str = "mock"  # mock | real
    acoustic_model_id: str = ""
    acoustic_model_revision: str = ""
    asr_model: str = ""
    speaker_model: str = ""
    speaker_model_version: str = ""
    model_artifact_hashes: Dict[str, str] = Field(default_factory=dict)
    risk_config_fingerprint: str = ""  # hash of the risk fusion config version


class IntentFinding(BaseModel):
    """One structured contextual-risk finding (from the intent analyzer)."""

    category: str
    confidence: float
    severity: str
    speech_act: str
    matched_phrase: str
    language: str


class WindowEvidence(BaseModel):
    """Per-window derived evidence (no audio, no raw transcript)."""

    window_index: int
    timestamp: float
    relative_time_seconds: float
    risk_score: int
    acoustic_score: float
    intent_score: float
    speaker_similarity: Optional[float] = None
    identity_mismatch: Optional[float] = None
    status: str
    transcript_hash: Optional[str] = None  # SHA-256 of transcript text
    language: Optional[str] = None
    codec: Optional[str] = None
    vad_active: Optional[bool] = None
    rationale: List[str] = Field(default_factory=list)
    intent_findings: List[IntentFinding] = Field(default_factory=list)


class EvidencePackageInput(BaseModel):
    """Everything needed to author a canonical package (backend-authored)."""

    schema_version: str = SCHEMA_VERSION
    package_format: str = PACKAGE_FORMAT
    call_id: str = Field(..., min_length=1)
    caller_id: str = ""
    recipient_id: str = ""
    session_start: Optional[str] = None
    session_end: Optional[str] = None
    duration_seconds: float = 0.0
    generated_at: str = Field(default_factory=utc_now_iso)
    codec: str = "pcm"
    language: Optional[str] = None
    detected_languages: List[str] = Field(default_factory=list)
    model_provenance: ModelProvenance = Field(default_factory=ModelProvenance)
    windows: List[WindowEvidence] = Field(default_factory=list)
    peak_risk_score: int = 0
    fused_risk_score: int = 0
    action_taken: str = "none"
    verification_result: Optional[str] = None  # e.g. "challenge_succeeded"
    disposition: str = "closed"

    # Contextual intent findings consolidated across windows.
    intent_findings: List[IntentFinding] = Field(default_factory=list)

    def compute_evidence_hash(self) -> str:
        """Deterministic hash over the canonical form of this package.

        Excludes ledger/anchor fields (added after registration) so the hash
        covers exactly the evidence the system observed — not its downstream
        publication status.
        """
        return canonical_hash(self.model_dump(mode="json"))


def build_window_evidence_from_telemetry(point: Dict[str, Any], index: int, time_zero: float) -> WindowEvidence:
    """Adapt one stored telemetry frame into canonical window evidence."""
    transcript = point.get("transcript")
    return WindowEvidence(
        window_index=index,
        timestamp=float(point.get("timestamp", 0.0)),
        relative_time_seconds=round(max(0.0, float(point.get("timestamp", 0.0)) - time_zero), 3),
        risk_score=int(point.get("risk_score", 0)),
        acoustic_score=float(point.get("acoustic_score", 0.0)),
        intent_score=float(point.get("intent_score", 0.0)),
        speaker_similarity=point.get("speaker_score"),
        identity_mismatch=point.get("identity_mismatch"),
        status=str(point.get("status", "ALLOW")),
        transcript_hash=sha256_hex(transcript) if transcript else None,
        language=point.get("detected_language"),
        codec=point.get("codec"),
        vad_active=point.get("vad_active"),
        rationale=list(point.get("rationale") or []),
        intent_findings=[
            IntentFinding(
                category=r.get("category", "unknown"),
                confidence=float(r.get("confidence", 0.0)),
                severity=str(r.get("severity", "info")),
                speech_act=str(r.get("speech_act", "mention")),
                matched_phrase=str(r.get("matched_phrase", "")),
                language=str(r.get("language", "unknown")),
            )
            for r in (point.get("intent_risks") or [])
        ],
    )
