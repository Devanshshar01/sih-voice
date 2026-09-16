"""
Batch analysis endpoint for a single uploaded audio sample -- lets judges
or teammates sanity-check the detector without spinning up a full call.
"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app import config
from app.models.schemas import AudioAnalyzeResponse
from app.services.ml_detector import get_detector
from app.tasks import generate_forensic_report

router = APIRouter(prefix="/audio", tags=["audio"])

detector = get_detector(
    config.VOICE_DETECTOR_MODE,
    model_path=config.VOICE_MODEL_PATH or None,
    model_id=config.VOICE_MODEL_ID,
    device=config.VOICE_MODEL_DEVICE,
    revision=config.VOICE_MODEL_REVISION,
)


@router.post("/analyze", response_model=AudioAnalyzeResponse)
async def analyze_audio(audio_file: UploadFile = File(...), language: str = Form("en-IN")):
    raw = await audio_file.read()
    # Phase 1 assumes raw PCM float32 bytes for simplicity. Swap in a proper
    # WAV/MP3 decoder (soundfile/pydub) before wiring this up to arbitrary
    # judge-supplied files.
    samples = np.frombuffer(raw, dtype=np.float32) if raw else np.array([], dtype=np.float32)

    result = detector.predict(samples)
    score = result["acoustic_score"]
    if (
        not result.get("success", True)
        or score is None
        or not np.isfinite(score)
        or not 0.0 <= score <= 1.0
    ):
        # A failed detector is not evidence of either class.  Preserve the
        # explicit degraded state instead of converting None into a verdict.
        raise HTTPException(
            status_code=503,
            detail={
                "status": "error",
                "error_code": result.get("error_code", "INFERENCE_UNAVAILABLE"),
                "error_message": result.get(
                    "error_message", "Audio inference did not produce a valid score"
                ),
                "detector_status": result.get("detector_status", "unavailable"),
            },
        )
    classification = "AI_GENERATED" if score >= 0.5 else "HUMAN"
    confidence = score if classification == "AI_GENERATED" else 1 - score

    task = generate_forensic_report.delay(
        call_id="batch-analysis",
        payload={
            "summary": (
                f"Batch analysis completed for {audio_file.filename or 'uploaded sample'}"
            ),
            "generated_at": None,
        },
    )

    return AudioAnalyzeResponse(
        classification=classification,
        confidence=round(confidence, 4),
        explanation=(
            f"Acoustic synthesis likelihood {score:.0%} "
            f"based on the {result['details'].get('mode', 'mock')} detector "
            f"({result['details'].get('model', 'deterministic demo')}). "
            f"Background task queued: {task.id}."
        ),
    )
