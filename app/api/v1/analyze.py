"""
Batch analysis endpoint for a single uploaded audio sample -- lets judges
or teammates sanity-check the detector without spinning up a full call.
"""
from __future__ import annotations

import logging

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
import soundfile as sf
from io import BytesIO

from app import config
from app.models.schemas import AudioAnalyzeResponse
from app.services.ml_detector import get_detector
from app.tasks import CELERY_AVAILABLE, generate_forensic_report

logger = logging.getLogger(__name__)
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
    if not raw or len(raw) > config.MAX_ANALYZE_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail={"status": "error", "error_code": "AUDIO_TOO_LARGE_OR_EMPTY"})
    try:
        if raw[:4] == b"RIFF":
            samples, sample_rate = sf.read(BytesIO(raw), dtype="float32", always_2d=False)
            if samples.ndim > 1:
                samples = samples.mean(axis=1)
            samples = np.asarray(samples, dtype=np.float32)
        else:
            # Preserve the existing raw float32 test/client contract.
            samples = np.frombuffer(raw, dtype=np.float32)
            sample_rate = config.TARGET_SAMPLE_RATE
    except Exception as exc:
        raise HTTPException(status_code=400, detail={"status": "error", "error_code": "INVALID_AUDIO", "error_message": str(exc)}) from exc
    duration_ms = len(samples) / sample_rate * 1000.0
    if sample_rate <= 0 or duration_ms > config.MAX_ANALYZE_DURATION_SECONDS * 1000:
        raise HTTPException(status_code=413, detail={"status": "error", "error_code": "AUDIO_TOO_LONG"})
    if samples.size == 0 or not np.isfinite(samples).all():
        raise HTTPException(status_code=400, detail={"status": "error", "error_code": "INVALID_AUDIO"})

    result = detector.predict(samples)
    score = result["acoustic_score"]
    details = result.get("details") or {}
    fake_probability = details.get("fake_probability", score)
    real_probability = details.get("real_probability", 1.0 - score) if score is not None else None
    if (
        not result.get("success", True)
        or score is None
        or not np.isfinite(score)
        or not 0.0 <= score <= 1.0
        or fake_probability is None
        or real_probability is None
        or not np.isfinite(fake_probability)
        or not np.isfinite(real_probability)
        or not 0.0 <= fake_probability <= 1.0
        or not 0.0 <= real_probability <= 1.0
        or not np.isclose(fake_probability + real_probability, 1.0, atol=0.01)
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
    classification = "AI_GENERATED" if score >= config.SPOOF_THRESHOLD else "HUMAN"
    confidence = score if classification == "AI_GENERATED" else 1 - score

    # Reports are optional: a broker outage must not discard valid inference.
    report_note = "Background report generation disabled."
    if config.CELERY_ENABLED and not CELERY_AVAILABLE:
        logger.warning("Optional forensic report queue is not configured or Celery is unavailable")
        report_note = "Background report generation unavailable."
    elif config.CELERY_ENABLED:
        try:
            task = generate_forensic_report.delay(
                call_id="batch-analysis",
                payload={
                    "summary": (
                        f"Batch analysis completed for {audio_file.filename or 'uploaded sample'}"
                    ),
                    "generated_at": None,
                },
            )
            report_note = f"Background task queued: {task.id}."
        except Exception:
            logger.exception(
                "Failed to queue optional forensic report for batch-analysis; "
                "returning successful audio analysis"
            )
            report_note = "Background report generation unavailable."

    return AudioAnalyzeResponse(
        classification=classification,
        confidence=round(confidence, 4),
        status="ok",
        spoof_probability=score,
        fake_probability=float(fake_probability),
        real_probability=float(real_probability),
        model_version_antispoof=details.get("model_version_antispoof") or details.get("model"),
        inference_time_ms=details.get("inference_time_ms") or details.get("inference_latency_ms"),
        sample_rate=sample_rate,
        duration_ms=round(duration_ms, 2),
        explanation=(
            f"Acoustic synthesis likelihood {score:.0%} "
            f"based on the {result['details'].get('mode', 'mock')} detector "
            f"({details.get('model', 'deterministic demo')}). "
            f"{report_note}"
        ),
    )
