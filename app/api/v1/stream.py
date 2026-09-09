"""WebSocket audio ingestion.

Accepts raw PCM binary frames, buffers them into sliding 2.0s/0.5s-hop
windows, runs the dual acoustic + intent pipeline, and streams back JSON
risk telemetry as each window completes.

Frontend contract:
    - Binary frames: Float32 PCM, mono, 16kHz.
    - Optional JSON text frame: {"transcript": "..."} to override ASR text,
        {"language": "hi"} to select a Whisper language, and/or
        {"force_acoustic_score": 0.0-1.0} for deterministic mock demos.
"""
import json
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from app import config
from app.core.risk_engine import compute_risk
from app.core.session_manager import session_manager
from app.db import models as db_models
from app.db.database import SessionLocal
from app.services.audio_processor import apply_vad, decode_pcm_frame, normalize_audio
from app.services.intent_analyzer import IntentAnalyzer
from app.services.ml_detector import MockVoiceDetector, get_detector
from app.services.speaker_vault import get_speaker_vault

router = APIRouter(prefix="/call", tags=["stream"])

detector = get_detector(
    config.VOICE_DETECTOR_MODE,
    model_path=config.VOICE_MODEL_PATH or None,
    model_id=config.VOICE_MODEL_ID,
    device=config.VOICE_MODEL_DEVICE,
    revision=config.VOICE_MODEL_REVISION,
)
intent_analyzer = IntentAnalyzer(
    model_size=config.ASR_MODEL_SIZE,
    device=config.ASR_DEVICE,
    compute_type=config.ASR_COMPUTE_TYPE,
)
speaker_vault = get_speaker_vault()


def _run_acoustic_detector(window, forced_score: Optional[float]):
    if isinstance(detector, MockVoiceDetector):
        return detector.predict(window, force_score=forced_score)
    return detector.predict(window)


def _persist_risk_event(db: DBSession, call_id: str, result: dict) -> None:
    db.add(
        db_models.RiskEvent(
            call_id=call_id,
            acoustic_score=result["acoustic_score"],
            intent_score=result["intent_score"],
            combined_risk_score=result["risk_score"],
            triggered_rule=result["status"],
        )
    )
    session_row = db.query(db_models.Session).filter_by(call_id=call_id).first()
    if session_row and result["risk_score"] > session_row.max_risk_score:
        session_row.max_risk_score = result["risk_score"]
    db.commit()


@router.websocket("/{call_id}/stream")
async def stream_audio(websocket: WebSocket, call_id: str):
    session = session_manager.get(call_id)
    if not session:
        await websocket.close(code=4404)
        return

    await websocket.accept()
    latest_transcript = ""
    manual_transcript = False
    stream_language: Optional[str] = config.ASR_LANGUAGE or None
    db = SessionLocal()

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break

            if message.get("text") is not None:
                try:
                    payload = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue
                if "transcript" in payload:
                    latest_transcript = payload.get("transcript", "")
                    manual_transcript = True
                if payload.get("language"):
                    stream_language = payload["language"]
                if config.VOICE_DETECTOR_MODE == "mock" and "force_acoustic_score" in payload:
                    session.forced_acoustic_score = payload["force_acoustic_score"]
                continue

            raw_bytes = message.get("bytes")
            if raw_bytes is None:
                continue

            session.touch()
            samples = decode_pcm_frame(raw_bytes)
            samples = normalize_audio(samples, codec=config.AUDIO_CODEC)
            samples = apply_vad(samples)
            if samples.size == 0:
                continue
            session.ring_buffer.push(samples)

            for window in session.ring_buffer.pop_ready_windows():
                acoustic_result = _run_acoustic_detector(window, session.forced_acoustic_score)
                speaker_match = speaker_vault.match(window) if speaker_vault.enabled else {
                    "speaker_id": None,
                    "speaker_match_score": 0.0,
                    "matched": False,
                    "vault_size": 0,
                    "method": speaker_vault._method,
                    "checkpoint_status": speaker_vault._checkpoint_status,
                }
                if config.ASR_MODE == "real" and not manual_transcript:
                    latest_transcript = intent_analyzer.transcribe(window, stream_language)
                intent_result = intent_analyzer.analyze_text(latest_transcript)

                risk_result = compute_risk(
                    acoustic_score=acoustic_result["acoustic_score"],
                    intent_score=intent_result["intent_score"],
                    flagged_phrases=intent_result["flagged_phrases"],
                    speaker_score=speaker_match["speaker_match_score"],
                )
                risk_result["detector"] = acoustic_result.get("details", {})
                risk_result["speaker"] = speaker_match
                risk_result["timestamp"] = time.time()

                session.record_risk_point(risk_result)
                session_manager.sync_session(session)
                _persist_risk_event(db, call_id, risk_result)

                await websocket.send_json(risk_result)

    except WebSocketDisconnect:
        pass
    finally:
        db.close()
