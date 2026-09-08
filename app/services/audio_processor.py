"""
PCM audio decoding and sliding-window buffering.

The frontend streams raw 32-bit float PCM (mono, 16kHz) binary frames over
the WebSocket. This module turns those byte frames into fixed-size numpy
windows for the acoustic/intent pipelines: a 2.0s window with a 0.5s hop
(75% overlap), exactly as specified in the prototype blueprint.
"""
from __future__ import annotations

from collections import deque
from typing import List

import numpy as np

from app import config


def decode_pcm_frame(raw_bytes: bytes) -> np.ndarray:
    """Decode a raw binary frame into a float32 numpy array in [-1, 1]."""
    samples = np.frombuffer(raw_bytes, dtype=np.float32)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 1.0:
        samples = samples / peak
    return samples


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
