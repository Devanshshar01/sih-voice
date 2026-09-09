"""
Benchmark the current 2.0s window against a 4.0s alternative on a synthetic
voice-like stream.

This is intentionally lightweight and deterministic so it can run locally
without heavyweight dependencies. It reports:
- average latency per window (wall-clock)
- detector score stability across windows
- how many windows are generated over the same sample span

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\benchmark_audio_windows.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import HOP_SECONDS, SAMPLE_RATE_HZ, WINDOW_SECONDS
from app.services.audio_processor import RingBuffer, normalize_audio
from app.services.ml_detector import MockVoiceDetector


def synthetic_voice_like_stream(sample_rate: int = SAMPLE_RATE_HZ, duration_seconds: float = 8.0) -> np.ndarray:
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    carrier = np.sin(2 * np.pi * 150 * t)
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * t)
    voice = carrier * envelope
    noise = 0.03 * np.random.default_rng(42).normal(size=voice.shape)
    return (voice + noise).astype(np.float32)


def benchmark(window_seconds: float, hop_seconds: float) -> Dict[str, object]:
    detector = MockVoiceDetector()
    stream = synthetic_voice_like_stream()
    window_samples = int(SAMPLE_RATE_HZ * window_seconds)
    hop_samples = int(SAMPLE_RATE_HZ * hop_seconds)

    ring = RingBuffer(window_samples=window_samples, hop_samples=hop_samples)
    normalized = normalize_audio(stream)
    ring.push(normalized)

    start = time.perf_counter()
    windows = ring.pop_ready_windows()
    elapsed = time.perf_counter() - start

    scores: List[float] = []
    for window in windows:
        scores.append(detector.predict(window)["acoustic_score"])

    return {
        "window_seconds": window_seconds,
        "hop_seconds": hop_seconds,
        "windows_generated": len(windows),
        "avg_score": round(float(statistics.fmean(scores)), 4) if scores else 0.0,
        "score_std": round(float(statistics.pstdev(scores)), 4) if len(scores) > 1 else 0.0,
        "windowing_latency_seconds": round(elapsed, 6),
    }


if __name__ == "__main__":
    results = []
    for window_seconds in (2.0, 4.0):
        results.append(benchmark(window_seconds=window_seconds, hop_seconds=HOP_SECONDS))

    for result in results:
        print(result)

    current = benchmark(window_seconds=WINDOW_SECONDS, hop_seconds=HOP_SECONDS)
    print("\nCurrent config:", current)
