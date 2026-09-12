"""WebSocket audio ingestion (SIH Phase 1 alignment).

Accepts binary audio frames, normalizes them through the codec layer
(`app.services.codec_normalizer`), feeds a rolling ring buffer that emits
4.0-second windows on a 0.5-second hop, gates inference with Silero VAD
(`app.services.vad`), and streams back JSON risk telemetry per window.

Frontend contract:
    - Binary frames: Float32 PCM, mono, 16 kHz by default.
    - Optional JSON control frames (any time, one or more keys):
        {"codec": "pcm" | "pcm_s16le" | "g711_ulaw" | "g711_alaw" | "opus" | "amr",
         "sample_rate": 8000, "channels": 1}   -> negotiate input format
        {"transcript": "..."}                   -> override ASR text
        {"language": "hi"}                      -> Whisper language hint
        {"force_acoustic_score": 0.0-1.0}       -> mock-mode demo hook only
    - Unknown/unsupported codecs get an JSON error frame and close 4402.

VAD policy: speech coverage is evaluated per 4s window. Windows with no
speech skip acoustic/speaker/ASR inference in real modes (telemetry reuses
the last risk snapshot and flags `vad_active: false`). In mock/demo mode the
gate is bypassed so the deterministic `force_acoustic_score` scenario keeps
working without a live microphone.
"""
import json
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from app import config
from app.core.latency import LatencyStats, LatencyTracker
from app.core.parallel_inference import run_window_inference
from app.core.risk_engine import compute_risk
from app.core.session_manager import session_manager
from app.db import models as db_models
from app.db.database import SessionLocal
from app.services import codec_normalizer, vad
from app.services.audio_processor import RingBuffer
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

# The deterministic mock detector is demo scaffolding, not ML inference, so
# the VAD gate is bypassed in mock mode to keep the forced-score demo working.
_VAD_GATES_INFERENCE = not isinstance(detector, MockVoiceDetector)

# Rolling p50/p95 latency statistics for the decision pipeline, exposed in
# every telemetry frame as `latency_stats` (SIH <500 ms measurability).
LATENCY_STATS = LatencyStats()


def _empty_speaker_match() -> Dict[str, Any]:
    """Identity evidence placeholder when the vault is disabled/unavailable.

    similarity is None (unknown), NOT 0.0: unknown identity is neutral in the
    fusion equation, not fraud.
    """
    return {
        "speaker_id": None,
        "speaker_match_score": None,
        "matched": False,
        "vault_size": 0,
        "method": speaker_vault._method,
        "checkpoint_status": speaker_vault._checkpoint_status,
    }


def _run_acoustic_detector(window, forced_score: Optional[float]):
    if isinstance(detector, MockVoiceDetector):
        return detector.predict(window, force_score=forced_score)
    return detector.predict(window)


def _run_asr_blocking(window) -> str:
    """Blocking faster-whisper transcription for the ASR lane.

    The lane contract returns plain text (None on failure = neutral in
    fusion). Whisper's detected language is stored on the function attribute
    and surfaced per-window in telemetry. Failures degrade to an empty
    transcript — never crash the WebSocket.
    """
    language = getattr(_run_asr_blocking, "language", None)
    try:
        text, detected = intent_analyzer.transcribe_detailed(window, language=language)
        _run_asr_blocking.detected_language = detected
        return text
    except Exception as exc:
        # Whisper failure: degrade, never crash the stream.
        _run_asr_blocking.detected_language = None
        _run_asr_blocking.last_error = f"{type(exc).__name__}: {exc}"
        return ""


def _run_speaker_blocking(window) -> Dict[str, Any]:
    """Blocking ECAPA/vault match for the speaker lane."""
    return speaker_vault.match(window)


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


def _apply_codec_config(payload: Dict[str, Any], state: Dict[str, Any]) -> None:
    """Validate and store a client codec negotiation."""
    fixed = (config.AUDIO_CODEC or "auto").strip().lower()
    codec = str(payload.get("codec", state.get("codec", "pcm"))).strip().lower()
    if fixed and fixed != "auto":
        codec = fixed
    codec_normalizer.ensure_available(codec)
    state["codec"] = codec
    state["sample_rate"] = int(payload.get("sample_rate", state.get("sample_rate", config.TARGET_SAMPLE_RATE)))
    state["channels"] = max(1, int(payload.get("channels", state.get("channels", 1))))


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

    codec_state: Dict[str, Any] = {
        "codec": "pcm",
        "sample_rate": config.TARGET_SAMPLE_RATE,
        "channels": 1,
    }
    if (config.AUDIO_CODEC or "auto").strip().lower() not in {"", "auto"}:
        _apply_codec_config({}, codec_state)

    last_risk_result: Optional[Dict[str, Any]] = None
    malformed_frames = 0
    last_codec_ms = 0.0

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
                if "codec" in payload or "sample_rate" in payload or "channels" in payload:
                    try:
                        _apply_codec_config(payload, codec_state)
                    except codec_normalizer.UnsupportedCodecError as exc:
                        await websocket.send_json(
                            {
                                "error": str(exc),
                                "supported_codecs": sorted(codec_normalizer.CODEC_FAMILIES),
                                "capabilities": codec_normalizer.describe_capabilities(),
                            }
                        )
                        await websocket.close(code=4402)
                        break
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

            # ---- Stage 1: codec normalization -> canonical float32/mono/16k ----
            _codec_start = time.perf_counter()
            try:
                samples = codec_normalizer.normalize_frame(
                    raw_bytes,
                    codec=codec_state["codec"],
                    sample_rate=codec_state["sample_rate"],
                    channels=codec_state["channels"],
                )
            except codec_normalizer.UnsupportedCodecError as exc:
                last_codec_ms = (time.perf_counter() - _codec_start) * 1000.0
                await websocket.send_json(
                    {
                        "error": str(exc),
                        "supported_codecs": sorted(codec_normalizer.CODEC_FAMILIES),
                    }
                )
                await websocket.close(code=4402)
                break
            except Exception:
                last_codec_ms = (time.perf_counter() - _codec_start) * 1000.0
                # Malformed frame (wrong size, truncated payload): drop it,
                # keep the session alive, count it for diagnostics.
                malformed_frames += 1
                continue
            else:
                last_codec_ms = (time.perf_counter() - _codec_start) * 1000.0

            if samples.size == 0:
                continue

            # ---- Stage 2: rolling buffer. Every decoded sample is buffered,
            # including silence, so 4s window geometry is always exact. ----
            session.ring_buffer.push(samples)

            for window in session.ring_buffer.pop_ready_windows():
                tracker = LatencyTracker()
                tracker.start_total()
                tracker.record("codec", last_codec_ms)
                tracker.record("window_ready", 0.0)

                # ---- Stage 3: Silero VAD assessment (non-mutating) ----
                tracker.start("vad")
                _, vad_telemetry = vad.assess(window)
                tracker.stop("vad")
                speech_active = bool(vad_telemetry["vad_active"]) or not _VAD_GATES_INFERENCE

                if not speech_active and last_risk_result is not None:
                    # Skip ML inference on complete silence; re-emit the last
                    # snapshot with VAD flags so the console stays current.
                    snapshot = dict(last_risk_result)
                    snapshot.update(vad_telemetry)
                    snapshot["vad_skipped"] = True
                    snapshot["malformed_frames"] = malformed_frames
                    tracker.record("total", 0.0)
                    LATENCY_STATS.record(tracker)
                    snapshot["latency_ms"] = tracker.as_dict()
                    snapshot["latency_stats"] = LATENCY_STATS.snapshot()
                    await websocket.send_json(snapshot)
                    continue

                # ---- Stage 4: PARALLEL inference on speech-bearing windows
                # (anti-spoof ∥ ASR ∥ speaker; each lane serialized, bounded) ----
                _run_asr_blocking.language = stream_language  # language hint for the lane

                (acoustic_result, transcript, speaker_match, degraded) = await run_window_inference(
                    window,
                    run_anti_spoof=lambda w: _run_acoustic_detector(w, session.forced_acoustic_score),
                    run_asr=_run_asr_blocking if (config.ASR_MODE == "real" and not manual_transcript) else None,
                    run_speaker=_run_speaker_blocking if speaker_vault.enabled else None,
                )
                if transcript is not None:
                    latest_transcript = transcript

                # ---- Stage 5: intent + risk fusion (cheap, on the event loop) ----
                tracker.start("fusion")
                window_index = session.ring_buffer.total_pushed // config.HOP_SAMPLES
                intent_result = intent_analyzer.analyze_text(
                    latest_transcript,
                    language=stream_language,
                    window_index=window_index,
                    timestamp=time.time(),
                )

                risk_result = compute_risk(
                    acoustic_score=acoustic_result["acoustic_score"],
                    intent_score=intent_result["intent_score"],
                    flagged_phrases=intent_result["flagged_phrases"],
                    flagged_categories=intent_result.get("flagged_categories", []),
                    speaker_similarity=speaker_match["speaker_match_score"],
                    degraded=degraded,
                )
                tracker.stop("fusion")

                # Contextual ASR/intent evidence (additive; dashboard-ready).
                risk_result["transcript"] = latest_transcript
                asr_detected = getattr(_run_asr_blocking, "detected_language", None)
                risk_result["detected_language"] = (
                    intent_result.get("detected_language") or asr_detected
                )
                risk_result["intent_risks"] = intent_result.get("intent_risks", [])

                risk_result["detector"] = acoustic_result.get("details", {})
                risk_result["speaker"] = speaker_match
                risk_result["timestamp"] = time.time()
                risk_result.update(vad_telemetry)
                risk_result["vad_skipped"] = False
                risk_result["malformed_frames"] = malformed_frames

                tracker.finish_total()
                LATENCY_STATS.record(tracker)
                risk_result["latency_ms"] = tracker.as_dict()
                risk_result["latency_stats"] = LATENCY_STATS.snapshot()

                last_risk_result = dict(risk_result)
                session.record_risk_point(risk_result)
                session_manager.sync_session(session)
                _persist_risk_event(db, call_id, risk_result)

                await websocket.send_json(risk_result)

    except WebSocketDisconnect:
        pass
    finally:
        db.close()
        session.ring_buffer.reset()
