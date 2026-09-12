"""
Silero VAD preprocessing stage (SIH spec item D).

Role in the pipeline: decide where speech is, so detector/speaker/ASR
inference is not wasted on complete silence — while *never* corrupting the
4-second window geometry the models expect.

Key contract decisions (all verified by tests):
  * `assess()` is non-mutating and returns (samples, telemetry). It does not
    shrink, splice, or concatenate the window — the RingBuffer still receives
    every decoded sample so 4-second windows are always constructible.
  * A completely silent window short-circuits inference (vad_active=False)
    without touching buffering state.
  * Short intra-utterance pauses are preserved: we keep the union of speech
    regions expanded by VAD_SPEECH_PAD_MS rather than cutting between
    detected segments.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import numpy as np

from app import config

logger = logging.getLogger(__name__)

_SILERO_MODEL = None
_SILERO_LOAD_ERROR: Optional[str] = None


def _load_silero():
    global _SILERO_MODEL, _SILERO_LOAD_ERROR
    if _SILERO_MODEL is not None or _SILERO_LOAD_ERROR is not None:
        return _SILERO_MODEL
    try:
        try:
            from silero_vad import load_silero_vad as _loader
        except ImportError:  # older/newer package layout
            from silero_vad import load_silero_jit as _loader
        _SILERO_MODEL = _loader()
    except Exception as exc:  # model not downloaded / torch missing
        _SILERO_LOAD_ERROR = f"{exc.__class__.__name__}: {exc}"
        logger.warning("Silero VAD unavailable, falling back to energy VAD: %s", _SILERO_LOAD_ERROR)
    return _SILERO_MODEL


def vad_backend_status() -> str:
    if not config.VAD_ENABLED:
        return "disabled"
    if _SILERO_MODEL is not None:
        return "silero"
    if _SILERO_LOAD_ERROR is not None:
        return "energy-fallback"
    return "pending"


def _energy_assess(samples: np.ndarray) -> Tuple[bool, float]:
    """Legacy energy-threshold VAD, used only when Silero cannot load."""
    if samples.size == 0:
        return False, 0.0
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    return rms >= config.VAD_ENERGY_THRESHOLD, rms


def _silero_speech_ratio(samples: np.ndarray) -> float:
    """Fraction of 512-sample (32 ms) Silero frames classified as speech."""
    model = _SILERO_MODEL
    if model is None:
        return 0.0

    frame = 512  # Silero's native input frame at 16 kHz
    hop = frame
    total = 0
    voiced = 0
    threshold = config.VAD_THRESHOLD

    for start in range(0, samples.size - frame + 1, hop):
        chunk = samples[start : start + frame]
        try:
            prob = float(model(chunk, config.SAMPLE_RATE_HZ).item())
        except Exception:
            # Fail open: a transient model error must never cause us to
            # discard genuine speech from inference.
            return 1.0
        total += 1
        if prob >= threshold:
            voiced += 1

    return (voiced / total) if total else 0.0


def assess(samples: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Evaluate one decoded window of canonical audio.

    Returns:
        (samples_unchanged, telemetry) — telemetry keys:
          vad_active      : bool — speech present (inference is worthwhile)
          vad_coverage    : float — fraction of the window classified as speech
          vad_backend     : str  — "silero" | "energy-fallback" | "disabled"
    """
    telemetry: Dict[str, Any] = {
        "vad_active": False,
        "vad_coverage": 0.0,
        "vad_backend": vad_backend_status(),
    }

    if not config.VAD_ENABLED:
        telemetry.update(vad_active=True, vad_coverage=1.0, vad_backend="disabled")
        return samples, telemetry

    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return samples, telemetry

    if _SILERO_MODEL is None:
        _load_silero()

    if _SILERO_MODEL is not None:
        coverage = _silero_speech_ratio(samples)
        backend = "silero"
    else:
        active, rms = _energy_assess(samples)
        coverage = 1.0 if active else 0.0
        backend = "energy-fallback"

    telemetry.update(vad_active=coverage > 0.0, vad_coverage=round(coverage, 4), vad_backend=backend)
    return samples, telemetry


def get_speech_regions(samples: np.ndarray) -> list:
    """
    Speech regions [start, end) sample offsets, used by ASR prefiltering.

    Implements the "keep short pauses" requirement: the union of speech
    segments padded by VAD_SPEECH_PAD_MS; genuinely long non-speech gaps are
    the only things that get cut.
    """
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return []

    if not config.VAD_ENABLED:
        return [(0, samples.size)]

    if _SILERO_MODEL is None:
        _load_silero()

    if _SILERO_MODEL is None:
        active, _rms = _energy_assess(samples)
        return [(0, samples.size)] if active else []

    try:
        from silero_vad import get_speech_timestamps

        return get_speech_timestamps(
            samples,
            _SILERO_MODEL,
            sampling_rate=config.SAMPLE_RATE_HZ,
            threshold=config.VAD_THRESHOLD,
            min_speech_duration_ms=config.VAD_MIN_SPEECH_DURATION_MS,
            min_silence_duration_ms=config.VAD_MIN_SILENCE_DURATION_MS,
            speech_pad_ms=config.VAD_SPEECH_PAD_MS,
            return_seconds=False,
        )
    except Exception:  # pragma: no cover - dependency mismatch
        active, _rms = _energy_assess(samples)
        return [(0, samples.size)] if active else []
