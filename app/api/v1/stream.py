"""WebSocket audio ingestion (SIH Phase 1 alignment).

SECURITY / RESILIENCE:
  - Maximum binary frame size: MAX_FRAME_BYTES (8 MB). Oversized frames are
    dropped with a counter increment; the stream stays alive (B4).
  - _persist_risk_event() is DB-failure-tolerant: a commit error logs and
    continues without crashing the WebSocket (B6).
  - WebSocket auth (IDOR/BOLA) is handled by authenticate_websocket (B2/B10).

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
import logging
import math
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from app import config
from app.core.latency import LatencyStats, LatencyTracker
from app.core.parallel_inference import run_window_inference
from app.core.risk_engine import compute_risk
from app.core.session_manager import session_manager
from app.core.ws_auth import authenticate_websocket
from app.db import models as db_models
from app.db.database import SessionLocal, commit_with_retry
from app.services import codec_normalizer, vad
from app.services.audio_processor import RingBuffer
from app.services.intent_analyzer import IntentAnalyzer
from app.services.ml_detector import MockVoiceDetector, get_detector
from app.services.speaker_vault import get_speaker_vault

router = APIRouter(prefix="/call", tags=["stream"])

_logger = logging.getLogger("satyavoice.stream")

# Maximum binary frame size accepted per WebSocket message.
# Frames exceeding this are silently dropped (malformed_frames counter incremented).
# 4 seconds at 16kHz float32 = 256 KB. 8 MB is extremely generous.
MAX_FRAME_BYTES = 8 * 1024 * 1024  # 8 MB

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


# Model id reported when the detector cannot report its own provenance (e.g. the
# provider failed before it could identify the checkpoint it was using).
_ACOUSTIC_MODEL_ID = config.VOICE_MODEL_ID


class _AcousticTrace:
    """Structured, low-noise tracing of the live anti-spoof provider lane.

    Answers "where did anti_spoof become degraded?" from production logs by
    recording, per window: window duration, sample rate, provider start/finish
    timing, model id, detector mode, the provider's error type/message, and
    whether the returned score normalized into the expected 0-1 range.

    Steady-state success is logged once rather than every window; failures and
    ok<->degraded transitions are always logged. Raw audio, JWTs, tokens and
    credentials are never logged -- only derived metrics.
    """

    def __init__(self, call_id: str) -> None:
        self.call_id = call_id
        self.windows = 0
        self.last_status: Optional[str] = None

    def record(
        self,
        *,
        acoustic_result: Dict[str, Any],
        degraded: Dict[str, str],
        window,
        elapsed_ms: float,
    ) -> None:
        self.windows += 1
        details = acoustic_result.get("details") or {}
        reason = degraded.get("anti_spoof")
        status = "degraded" if reason else "ok"

        # Quiet in steady state: one INFO per call while healthy.
        if status == "ok" and self.last_status is not None:
            return
        self.last_status = status

        try:
            window_samples = int(window.size)
        except AttributeError:
            window_samples = len(window)

        score = acoustic_result.get("acoustic_score")
        try:
            score_normalized = (
                score is not None
                and math.isfinite(float(score))
                and 0.0 <= float(score) <= 1.0
            )
        except (TypeError, ValueError):
            score_normalized = False

        error_type, _, error_message = (reason or "").partition(":")
        payload = {
            "call_id": self.call_id,
            "window_index": self.windows,
            "window_samples": window_samples,
            "window_ms": round(window_samples / config.TARGET_SAMPLE_RATE * 1000.0, 1),
            "sample_rate": config.TARGET_SAMPLE_RATE,
            "provider_invoked": True,
            "provider_finished": True,
            "provider_ms": round(elapsed_ms, 1),
            "model_id": (
                details.get("model_version_antispoof")
                or details.get("model")
                or _ACOUSTIC_MODEL_ID
            ),
            "detector_mode": details.get("mode"),
            "detector_status": acoustic_result.get("detector_status"),
            "status": status,
            "error_type": error_type.strip() or None,
            "error_message": error_message.strip() or None,
            "score_normalized": bool(score_normalized),
        }
        rendered = json.dumps(payload, sort_keys=True)
        if status == "degraded":
            _logger.error("anti_spoof_provider %s", rendered)
        else:
            _logger.info("anti_spoof_provider %s", rendered)

    def summary(self) -> Optional[str]:
        """One-line outcome for the end of the call (None when never degraded)."""
        if self.last_status != "degraded":
            return None
        return json.dumps(
            {
                "call_id": self.call_id,
                "windows_inferred": self.windows,
                "final_status": self.last_status,
                "degraded_stage": "anti_spoof",
            },
            sort_keys=True,
        )


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


class _PersistState:
    """Per-call database write state.

    Two guarantees:
      1. A SQLAlchemy session whose commit failed is never reused — every failure
         is rolled back and the connection pool is disposed so the next write
         runs on a fresh connection.
      2. The same failure is never logged once per audio event: after the first
         unrecoverable failure, persistence is disabled for the remainder of the
         call (the stream itself keeps running).
    """

    def __init__(self, call_id: str, *, enabled: bool = True) -> None:
        self.call_id = call_id
        self.enabled = enabled
        self.failures = 0

    def disable(self) -> None:
        self.enabled = False
        self.failures += 1
        _logger.warning(
            "DB persistence disabled for call_id=%s after %d failed write(s); "
            "no further RiskEvent writes for this call — stream continues",
            self.call_id,
            self.failures,
        )


def _persist_risk_event(
    db: DBSession,
    call_id: str,
    result: dict,
    state: Optional[_PersistState] = None,
) -> None:
    """Persist a risk event, recovering from a transiently closed connection.

    A failed commit is rolled back and the pooled connections disposed, then the
    write is re-staged once so a transiently closed managed-PostgreSQL
    connection (Render closes idle sockets) recovers transparently. If the retry
    also fails, persistence is switched off for the rest of the call so a
    permanent failure cannot emit one identical error per incoming audio event.

    The WebSocket is never crashed by a DB error (B6 resilience requirement).
    """
    if state is not None and not state.enabled:
        return

    def _stage() -> None:
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

    _stage()
    if commit_with_retry(db, _stage, context=f"risk_event_persist call_id={call_id}"):
        if state is not None:
            # A recovered transient failure re-arms the "logged once" latch.
            state.failures = 0
        return

    if state is not None:
        state.disable()


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
    # ---- Authentication & Authorization (must occur BEFORE accept()) ----
    # authenticate_websocket validates the JWT token from the ?token= query
    # param, verifies the token's subject matches the session's caller_id
    # (preventing IDOR/BOLA), and closes the socket on any failure.
    # The session existence check is performed inside authenticate_websocket.
    allowed = await authenticate_websocket(websocket, call_id)
    if not allowed:
        return

    # Re-fetch the session (authenticate_websocket already verified it exists).
    session = session_manager.get(call_id)
    if not session:
        # Extremely unlikely race: session expired between auth check and here.
        await websocket.close(code=4404)
        return

    await websocket.accept()
    latest_transcript = ""
    manual_transcript = False
    stream_language: Optional[str] = config.ASR_LANGUAGE or None
    db = SessionLocal()
    # Persistence is skipped entirely when /call/start already established that
    # the durable audit row could not be written (explicit best-effort mode).
    persist_state = _PersistState(call_id, enabled=not session.persistence_degraded)
    acoustic_trace = _AcousticTrace(call_id)

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

            # Frame size guard: drop oversized frames (B4 — resource exhaustion)
            if len(raw_bytes) > MAX_FRAME_BYTES:
                malformed_frames += 1
                _logger.warning(
                    "Oversized frame dropped for call_id=%s: %d bytes > %d max",
                    call_id,
                    len(raw_bytes),
                    MAX_FRAME_BYTES,
                )
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

                # Anti-spoof provider lane. Timing wraps the actual provider
                # invocation so logs separate provider latency from lane queueing.
                acoustic_timing: Dict[str, float] = {}

                def _timed_acoustic(window_data):
                    _provider_start = time.perf_counter()
                    try:
                        return _run_acoustic_detector(
                            window_data, session.forced_acoustic_score
                        )
                    finally:
                        acoustic_timing["ms"] = (
                            time.perf_counter() - _provider_start
                        ) * 1000.0

                (acoustic_result, transcript, speaker_match, degraded) = await run_window_inference(
                    window,
                    run_anti_spoof=_timed_acoustic,
                    run_asr=_run_asr_blocking if (config.ASR_MODE == "real" and not manual_transcript) else None,
                    run_speaker=_run_speaker_blocking if speaker_vault.enabled else None,
                )
                acoustic_trace.record(
                    acoustic_result=acoustic_result,
                    degraded=degraded,
                    window=window,
                    elapsed_ms=acoustic_timing.get("ms", 0.0),
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
                _persist_risk_event(db, call_id, risk_result, persist_state)

                await websocket.send_json(risk_result)

    except WebSocketDisconnect:
        pass
    finally:
        summary = acoustic_trace.summary()
        if summary:
            _logger.error("anti_spoof_provider_summary %s", summary)
        db.close()
        session.ring_buffer.reset()
