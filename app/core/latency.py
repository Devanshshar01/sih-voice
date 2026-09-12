"""
Latency instrumentation for the multimodal decision pipeline (SIH Phase 2).

Tracks per-stage wall-clock timings for each 4-second decision window:

    window_ready -> codec -> vad -> anti_spoof -> asr -> speaker -> fusion -> total

`LatencyTracker` is per-window (records one decision); `LatencyStats` keeps a
bounded rolling history per stage and reports p50/p95, so the sub-500 ms
target can be *measured*, not claimed. Stage timings are recorded in
milliseconds and exported inside risk telemetry as `latency_ms`.
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Deque, Dict, Optional

import numpy as np

STAGES = (
    "window_ready",   # time the completed window waited before processing started
    "codec",          # codec normalization (decode + resample + normalize)
    "vad",            # Silero/energy VAD assessment
    "anti_spoof",     # Wav2Vec2 (or mock) anti-spoof inference
    "asr",            # faster-whisper transcription
    "speaker",        # ECAPA speaker embedding + vault match
    "fusion",         # risk fusion (compute_risk)
    "total",          # window-ready -> decision serialized
)

_HISTORY_LIMIT = 200


class LatencyTracker:
    """Collects stage timings for one decision window."""

    def __init__(self) -> None:
        self._marks: Dict[str, float] = {}
        self._durations_ms: Dict[str, float] = {}
        self._total_start: Optional[float] = None

    def start_total(self) -> None:
        self._total_start = time.perf_counter()

    def start(self, stage: str) -> None:
        self._marks[stage] = time.perf_counter()

    def stop(self, stage: str) -> None:
        if stage in self._marks:
            elapsed = (time.perf_counter() - self._marks.pop(stage)) * 1000.0
            self._durations_ms[stage] = self._durations_ms.get(stage, 0.0) + elapsed

    def record(self, stage: str, duration_ms: float) -> None:
        self._durations_ms[stage] = self._durations_ms.get(stage, 0.0) + float(duration_ms)

    def finish_total(self) -> float:
        if self._total_start is not None:
            self._durations_ms["total"] = (time.perf_counter() - self._total_start) * 1000.0
        return self._durations_ms.get("total", 0.0)

    def as_dict(self) -> Dict[str, float]:
        return {stage: round(self._durations_ms.get(stage, 0.0), 2) for stage in STAGES}


def percentile(values, q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * q
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


class LatencyStats:
    """Bounded rolling percentile statistics per pipeline stage."""

    def __init__(self, history_limit: int = _HISTORY_LIMIT) -> None:
        self._history: Dict[str, Deque[float]] = {stage: deque(maxlen=history_limit) for stage in STAGES}

    def record(self, tracker: LatencyTracker) -> None:
        for stage, ms in tracker.as_dict().items():
            if stage in self._history:
                self._history[stage].append(float(ms))

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        return {
            stage: {
                "p50": round(percentile(hist, 0.50), 2),
                "p95": round(percentile(hist, 0.95), 2),
                "n": len(hist),
            }
            for stage, hist in self._history.items()
            if len(hist) > 0
        }

    def summary_line(self) -> str:
        snap = self.snapshot()
        if not snap:
            return "no latency samples yet"
        parts = []
        for stage, stats in snap.items():
            if stage in ("window_ready",):
                continue
            parts.append(f"{stage}: p50={stats['p50']:.1f}ms p95={stats['p95']:.1f}ms (n={stats['n']})")
        return " | ".join(parts)
