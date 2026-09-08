"""
WebSocket audio ingestion.

Accepts raw PCM binary frames, buffers them into sliding 2.0s/0.5s-hop
windows, runs the dual acoustic + intent pipeline, and streams back JSON
risk telemetry as each window completes.

Frontend contract:
  - Binary frames: Float32 PCM, mono, 16kHz.
  - Optional JSON text frame: {"transcript": "..."} to feed the intent
    analyzer (Phase 1 has no on-server ASR model), and/or
    {"force_acoustic_score": 0.0-1.0} -- the judge-demo backup audio
    injection hook for deterministically triggering the cloned-voice
    scenario if the live microphone isn't reliable.
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
from app.services.audio_processor import decode_pcm_frame
from app.services.intent_analyzer import IntentAnalyzer
from app.services.ml_detector import MockVoiceDetector, get_detector

router = APIRouter(prefix="/call", tags=["stream"])

detector = get_detector(config.VOICE_DETECTOR_MODE)
intent_analyzer = IntentAnalyzer()


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
                latest_transcript = payload.get("transcript", latest_transcript)
                if "force_acoustic_score" in payload:
                    session.forced_acoustic_score = payload["force_acoustic_score"]
                continue

            raw_bytes = message.get("bytes")
            if raw_bytes is None:
                continue

            session.touch()
            samples = decode_pcm_frame(raw_bytes)
            session.ring_buffer.push(samples)

            for window in session.ring_buffer.pop_ready_windows():
                acoustic_result = _run_acoustic_detector(window, session.forced_acoustic_score)
                intent_result = intent_analyzer.analyze_text(latest_transcript)

                risk_result = compute_risk(
                    acoustic_score=acoustic_result["acoustic_score"],
                    intent_score=intent_result["intent_score"],
                    flagged_phrases=intent_result["flagged_phrases"],
                )
                risk_result["timestamp"] = time.time()

                session.record_risk_point(risk_result)
                _persist_risk_event(db, call_id, risk_result)

                await websocket.send_json(risk_result)

    except WebSocketDisconnect:
        pass
    finally:
        db.close()
