"""
PCM audio decoding, normalization, VAD, and sliding-window buffering.

Pipeline order is fixed by the SIH spec:
    wire bytes -> codec normalization (app.services.codec_normalizer)
               -> Silero VAD gate (app.services.vad)
               -> rolling ring buffer -> 4.0s windows / 0.5s hop
               -> detector / speaker / ASR inference
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app import config
from app.services import codec_normalizer

_SILERO_VAD_MODEL = None
_SILERO_VAD_ERROR = None


def _load_silero_vad_model():
    """Deprecated alias: VAD now lives in app.services.vad. Kept for imports."""
    global _SILERO_VAD_MODEL, _SILERO_VAD_ERROR

    if _SILERO_VAD_MODEL is not None or _SILERO_VAD_ERROR is not None:
        return _SILERO_VAD_MODEL

    try:
        from app.services import vad as _vad

        _vad._load_silero()
        _SILERO_VAD_MODEL = _vad._SILERO_MODEL
        _SILERO_VAD_ERROR = _vad._SILERO_LOAD_ERROR
    except Exception as exc:  # pragma: no cover - runtime dependency guard
        _SILERO_VAD_ERROR = exc
        _SILERO_VAD_MODEL = None

    return _SILERO_VAD_MODEL


def decode_pcm_frame(raw_bytes: bytes) -> np.ndarray:
    """Decode one raw binary frame into canonical float32 samples.

    Thin retained alias over the codec normalizer so existing call sites and
    benchmarks keep working; the canonical path is `normalize_frame`.
    """
    return codec_normalizer.normalize_frame(raw_bytes, codec="pcm")


def normalize_audio(samples: np.ndarray, codec: Optional[str] = None) -> np.ndarray:
    """Normalize an in-memory sample array to amplitude-safe float32."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return samples
    if not np.all(np.isfinite(samples)):
        samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    peak = float(np.max(np.abs(samples)))
    if peak > 1.0:
        samples = samples / peak
    return np.clip(samples, -1.0, 1.0)


def apply_vad(samples: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """VAD stage: returns (samples, telemetry). Non-mutating by contract.

    Legacy callers that expected array-in/array-out must migrate to the
    telemetry tuple; see app/services/vad.py.
    """
    from app.services import vad

    return vad.assess(samples)


class RingBuffer:
    """Numpy ring buffer that yields overlapping 4-second windows every 0.5s.

    Efficiency contract: pushing N samples costs O(N); emitting windows costs
    O(window_samples) per emitted window — never a copy of the full audio
    history, which is also the privacy property (only the last `window` of
    audio is ever held in memory).
    """

    def __init__(
        self,
        window_samples: Optional[int] = None,
        hop_samples: Optional[int] = None,
    ) -> None:
        self.window_samples = int(window_samples or config.WINDOW_SAMPLES)
        self.hop_samples = int(hop_samples or config.HOP_SAMPLES)
        self._buffer = np.zeros(0, dtype=np.float32)
        self._total_pushed = 0

    @property
    def samples_buffered(self) -> int:
        return int(self._buffer.size)

    @property
    def total_pushed(self) -> int:
        return int(self._total_pushed)

    def push(self, samples: np.ndarray) -> None:
        """Append decoded samples (O(N) in chunk size)."""
        chunk = np.asarray(samples, dtype=np.float32).ravel()
        if chunk.size == 0:
            return
        self._buffer = np.concatenate((self._buffer, chunk))
        self._total_pushed += int(chunk.size)

    def pop_ready_windows(self) -> List[np.ndarray]:
        """Return every full window available, advancing exactly one hop each."""
        windows: List[np.ndarray] = []
        while self._buffer.size >= self.window_samples:
            windows.append(self._buffer[: self.window_samples].copy())
            # Advance by hop; keep only the overlap tail. Buffer never grows
            # unbounded: it holds at most window_samples + last_chunk - hop.
            self._buffer = self._buffer[self.hop_samples :]
        return windows

    def reset(self) -> None:
        """Clear buffered audio between calls."""
        self._buffer = np.zeros(0, dtype=np.float32)
        self._total_pushed = 0


def select_window_config(window_seconds: Optional[float] = None) -> dict:
    """Return the effective window/hop settings for the current pipeline."""
    if window_seconds is None:
        window_seconds = config.WINDOW_SECONDS

    return {
        "window_seconds": float(window_seconds),
        "hop_seconds": float(config.HOP_SECONDS),
        "window_samples": int(config.TARGET_SAMPLE_RATE * window_seconds),
        "hop_samples": int(config.SAMPLE_RATE_HZ * config.HOP_SECONDS),
    }
