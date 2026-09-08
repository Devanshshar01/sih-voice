"""
Batch analysis endpoint for a single uploaded audio sample -- lets judges
or teammates sanity-check the detector without spinning up a full call.
"""
import numpy as np
from fastapi import APIRouter, File, Form, UploadFile

from app import config
from app.models.schemas import AudioAnalyzeResponse
from app.services.ml_detector import get_detector

router = APIRouter(prefix="/audio", tags=["audio"])

detector = get_detector(config.VOICE_DETECTOR_MODE)


@router.post("/analyze", response_model=AudioAnalyzeResponse)
async def analyze_audio(audio_file: UploadFile = File(...), language: str = Form("en-IN")):
    raw = await audio_file.read()
    # Phase 1 assumes raw PCM float32 bytes for simplicity. Swap in a proper
    # WAV/MP3 decoder (soundfile/pydub) before wiring this up to arbitrary
    # judge-supplied files.
    samples = np.frombuffer(raw, dtype=np.float32) if raw else np.array([], dtype=np.float32)

    result = detector.predict(samples)
    score = result["acoustic_score"]
    classification = "AI_GENERATED" if score >= 0.5 else "HUMAN"
    confidence = score if classification == "AI_GENERATED" else 1 - score

    return AudioAnalyzeResponse(
        classification=classification,
        confidence=round(confidence, 4),
        explanation=(
            f"Acoustic synthesis likelihood {score:.0%} "
            f"based on the {result['details'].get('mode', 'mock')} detector."
        ),
    )
