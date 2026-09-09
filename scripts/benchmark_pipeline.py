"""Benchmark the real SatyaVoice pipeline with percentile reporting.

Measures end-to-end latency for the actual backend stages used by the live
stream path, broken down as:
    capture -> transport -> preprocessing -> inference -> fusion -> response

The script intentionally benchmarks the real code path (audio decode, VAD,
ring-buffer windowing, detector inference, intent analysis, and risk fusion)
so the reported p50 / p95 values reflect actual pipeline behavior rather than
mocked call-start timing.

Usage examples:
    .\\.venv\\Scripts\\python.exe scripts\\benchmark_pipeline.py
    .\\.venv\\Scripts\\python.exe scripts\\benchmark_pipeline.py --runs 500 --mode mock
    .\\.venv\\Scripts\\python.exe scripts\\benchmark_pipeline.py --runs 250 --mode real
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from app.core.risk_engine import compute_risk
from app.services.audio_processor import RingBuffer, apply_vad, decode_pcm_frame, normalize_audio
from app.services.intent_analyzer import IntentAnalyzer
from app.services.ml_detector import get_detector


def synthetic_voice_like_window(
    duration_seconds: float = 2.0,
    sample_rate: int = config.SAMPLE_RATE_HZ,
    seed: int = 42,
) -> np.ndarray:
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds), endpoint=False)
    carrier = np.sin(2 * np.pi * 150 * t)
    envelope = 0.5 + 0.5 * np.sin(2 * np.pi * 1.5 * t)
    voice = carrier * envelope
    noise = 0.03 * np.random.default_rng(seed).normal(size=voice.shape)
    return (voice + noise).astype(np.float32)


def percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def benchmark_once(
    detector,
    intent_analyzer: IntentAnalyzer,
    ring_buffer: RingBuffer,
    transcript: str,
) -> Dict[str, float]:
    window = synthetic_voice_like_window(duration_seconds=config.WINDOW_SECONDS)
    frame_bytes = window.astype(np.float32).tobytes()

    capture_start = time.perf_counter()
    raw_bytes = frame_bytes
    capture_ms = (time.perf_counter() - capture_start) * 1000.0

    transport_start = time.perf_counter()
    samples = decode_pcm_frame(raw_bytes)
    samples = normalize_audio(samples, codec=config.AUDIO_CODEC)
    transport_ms = (time.perf_counter() - transport_start) * 1000.0

    preprocessing_start = time.perf_counter()
    samples = apply_vad(samples)
    ring_buffer.push(samples)
    windows = ring_buffer.pop_ready_windows()
    if not windows:
        return {
            "capture_ms": capture_ms,
            "transport_ms": transport_ms,
            "preprocessing_ms": (time.perf_counter() - preprocessing_start) * 1000.0,
            "inference_ms": 0.0,
            "fusion_ms": 0.0,
            "response_ms": 0.0,
            "total_ms": capture_ms + transport_ms + (time.perf_counter() - preprocessing_start) * 1000.0,
        }
    processing_window = windows[0]
    preprocessing_ms = (time.perf_counter() - preprocessing_start) * 1000.0

    inference_start = time.perf_counter()
    acoustic_result = detector.predict(processing_window)
    inference_ms = (time.perf_counter() - inference_start) * 1000.0

    fusion_start = time.perf_counter()
    intent_result = intent_analyzer.analyze_text(transcript)
    risk_result = compute_risk(
        acoustic_score=acoustic_result["acoustic_score"],
        intent_score=intent_result["intent_score"],
        flagged_phrases=intent_result["flagged_phrases"],
        speaker_score=0.0,
    )
    fusion_ms = (time.perf_counter() - fusion_start) * 1000.0

    response_start = time.perf_counter()
    response_payload = {
        "risk_score": risk_result["risk_score"],
        "status": risk_result["status"],
        "acoustic_score": acoustic_result["acoustic_score"],
        "intent_score": intent_result["intent_score"],
        "flagged_phrases": intent_result["flagged_phrases"],
    }
    json.dumps(response_payload)
    response_ms = (time.perf_counter() - response_start) * 1000.0

    total_ms = (
        capture_ms
        + transport_ms
        + preprocessing_ms
        + inference_ms
        + fusion_ms
        + response_ms
    )
    return {
        "capture_ms": capture_ms,
        "transport_ms": transport_ms,
        "preprocessing_ms": preprocessing_ms,
        "inference_ms": inference_ms,
        "fusion_ms": fusion_ms,
        "response_ms": response_ms,
        "total_ms": total_ms,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the SatyaVoice pipeline latency.")
    parser.add_argument("--runs", type=int, default=100, help="Number of benchmark iterations to run.")
    parser.add_argument(
        "--mode",
        default=config.VOICE_DETECTOR_MODE,
        choices=["mock", "ml", "real"],
        help="Detector mode to benchmark. Defaults to current VOICETRUST_DETECTOR_MODE.",
    )
    parser.add_argument(
        "--transcript",
        default="This is urgent, please approve the wire transfer immediately.",
        help="Transcript content to feed into the intent analyzer.",
    )
    args = parser.parse_args()

    detector = get_detector(
        args.mode,
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

    ring_buffer = RingBuffer(window_samples=config.WINDOW_SAMPLES, hop_samples=config.HOP_SAMPLES)

    measurements: List[Dict[str, float]] = []
    for _ in range(args.runs):
        measurements.append(benchmark_once(detector, intent_analyzer, ring_buffer, args.transcript))

    stage_names = [
        "capture_ms",
        "transport_ms",
        "preprocessing_ms",
        "inference_ms",
        "fusion_ms",
        "response_ms",
        "total_ms",
    ]

    print(f"SatyaVoice pipeline latency benchmark ({args.runs} runs, mode={args.mode})")
    print("=" * 88)
    print(f"{'stage':<18} {'p50(ms)':>12} {'p95(ms)':>12} {'avg(ms)':>12} {'min(ms)':>12} {'max(ms)':>12}")

    for stage in stage_names:
        values = [entry[stage] for entry in measurements]
        print(
            f"{stage:<18} "
            f"{percentile(values, 0.50):>10.3f} "
            f"{percentile(values, 0.95):>10.3f} "
            f"{statistics.fmean(values):>10.3f} "
            f"{min(values):>10.3f} "
            f"{max(values):>10.3f}"
        )

    print("\nSample result row:")
    sample = measurements[0]
    print(json.dumps(sample, indent=2))


if __name__ == "__main__":
    import math

    main()
