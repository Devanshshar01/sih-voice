"""
PCM audio decoding, normalization, silence suppression, and sliding-window buffering.

The frontend streams raw 32-bit float PCM (mono, 16kHz) binary frames over
the WebSocket. This module turns those byte frames into fixed-size numpy
windows for the acoustic/intent pipelines. The default window remains 2.0s
with a 0.5s hop because that is the better tradeoff for the current demo.
"""
from __future__ import annotations

from collections import deque
from typing import List, Optional

import numpy as np

from app import config


def decode_pcm_frame(raw_bytes: bytes) -> np.ndarray:
    """Decode a raw binary frame into a float32 numpy array in [-1, 1]."""
    samples = np.frombuffer(raw_bytes, dtype=np.float32)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 1.0:
        samples = samples / peak
    return samples


def normalize_audio(samples: np.ndarray, codec: Optional[str] = None) -> np.ndarray:
    """Normalize incoming audio to an amplitude-safe float32 array."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return samples

    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 1.0:
        samples = samples / peak

    if codec and codec.lower() in {"g711", "g.711", "g711ulaw", "g711alaw"}:
        # Telephony codecs often arrive with a mu-law or A-law signal that is
        # already amplitude-shaped; rescaling to [-1, 1] avoids spurious peaks.
        samples = np.clip(samples, -1.0, 1.0)

    if codec and codec.lower() in {"opus", "amr"}:
        # These codecs can have low-level background noise. Biasing the signal
        # toward a normalized range keeps downstream scoring stable.
        rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
        if rms > 0:
            samples = samples / max(rms, 1e-6)

    return samples


def apply_vad(samples: np.ndarray) -> np.ndarray:
    """Drop frames that are effectively silent before detector scoring."""
    if not config.VAD_ENABLED or samples.size == 0:
        return samples

    rms = float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0
    if rms < config.VAD_ENERGY_THRESHOLD:
        return np.zeros_like(samples, dtype=np.float32)

    min_active_frames = max(1, config.VAD_MIN_ACTIVE_FRAMES)
    step = max(1, samples.size // min_active_frames)
    frame_means = np.abs(samples[: step * (samples.size // step)]).reshape(-1, step).mean(axis=1)
    active_frames = frame_means > config.VAD_ENERGY_THRESHOLD

    if active_frames.size == 0 or active_frames.sum() == 0:
        return np.zeros_like(samples, dtype=np.float32)

    first_active = int(np.argmax(active_frames)) * step
    last_active = int(np.nonzero(active_frames)[0][-1]) * step + step
    return samples[first_active:last_active].astype(np.float32, copy=False)


class RingBuffer:
    """Accumulates decoded samples and yields overlapping analysis windows."""

    def __init__(
        self,
        window_samples: int = config.WINDOW_SAMPLES,
        hop_samples: int = config.HOP_SAMPLES,
    ):
        self.window_samples = window_samples
        self.hop_samples = hop_samples
        self._buffer: deque = deque()

    def push(self, samples: np.ndarray) -> None:
        self._buffer.extend(samples.tolist())

    def pop_ready_windows(self) -> List[np.ndarray]:
        """Return every full window currently available, advancing by hop size."""
        windows: List[np.ndarray] = []
        while len(self._buffer) >= self.window_samples:
            window = np.array(list(self._buffer)[: self.window_samples], dtype=np.float32)
            windows.append(window)
            for _ in range(min(self.hop_samples, len(self._buffer))):
                self._buffer.popleft()
        return windows


def select_window_config(window_seconds: Optional[float] = None) -> dict:
    """Return the effective window/hop settings for the current pipeline."""
    if window_seconds is None:
        window_seconds = config.WINDOW_SECONDS

    return {
        "window_seconds": float(window_seconds),
        "hop_seconds": float(config.HOP_SECONDS),
        "window_samples": int(config.SAMPLE_RATE_HZ * window_seconds),
        "hop_samples": int(config.SAMPLE_RATE_HZ * config.HOP_SECONDS),
    }
