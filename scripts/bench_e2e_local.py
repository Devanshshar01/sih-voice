"""Local server-side pipeline latency benchmark (steady-state, mock mode).

Measures the same code path as stream.py window processing:
codec → VAD → anti_spoof → fusion → total

Reports p50/p95/p99/mean/min/max for each stage.
"""
import os
import statistics
import sys
import time

sys.path.insert(0, ".")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")
os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "bench-secret-x1234")
os.environ.setdefault("VOICETRUST_ASR_MODE", "manual")

import numpy as np

from app import config
from app.core.latency import LatencyStats, LatencyTracker
from app.core.risk_engine import compute_risk
from app.services import vad
from app.services.audio_processor import RingBuffer
from app.services.codec_normalizer import normalize_frame
from app.services.intent_analyzer import IntentAnalyzer
from app.services.ml_detector import get_detector

RUNS = 200
WARMUP = 20

detector = get_detector("mock")
intent = IntentAnalyzer(model_size="small", device="cpu", compute_type="int8")
ring = RingBuffer(
    window_samples=config.WINDOW_SAMPLES, hop_samples=config.HOP_SAMPLES
)
stats = LatencyStats()

# Pre-seed the ring buffer so the first hop produces a complete window.
seed = np.zeros(config.WINDOW_SAMPLES - config.HOP_SAMPLES, dtype=np.float32)
ring.push(seed)
_ = ring.pop_ready_windows()

hop_audio = (
    np.random.default_rng(42).standard_normal(config.HOP_SAMPLES).astype(np.float32)
)
hop_bytes = hop_audio.tobytes()

SAMPLE_TEXT = "Just checking on the quarterly budget report."


def run_one(warmup: bool = False):
    tracker = LatencyTracker()
    tracker.start_total()

    # Stage: codec normalisation
    tracker.start("codec")
    samples = normalize_frame(hop_bytes, codec="pcm", sample_rate=16000, channels=1)
    tracker.stop("codec")

    ring.push(samples)
    windows = ring.pop_ready_windows()
    if not windows:
        return None

    for w in windows:
        # Stage: VAD
        tracker.start("vad")
        _, _vad_tel = vad.assess(w)
        tracker.stop("vad")

        # Stage: anti-spoof
        tracker.start("anti_spoof")
        acoustic = detector.predict(w)
        tracker.stop("anti_spoof")

        # Stage: intent + risk fusion
        tracker.start("fusion")
        intent_result = intent.analyze_text(SAMPLE_TEXT)
        compute_risk(
            acoustic_score=acoustic["acoustic_score"],
            intent_score=intent_result["intent_score"],
            flagged_phrases=intent_result["flagged_phrases"],
        )
        tracker.stop("fusion")

    tracker.finish_total()
    if not warmup:
        stats.record(tracker)
    return tracker.as_dict()


def pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = (len(s) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


# Warm-up
for _ in range(WARMUP):
    run_one(warmup=True)

# Reset ring for measured runs
ring.reset()
seed = np.zeros(config.WINDOW_SAMPLES - config.HOP_SAMPLES, dtype=np.float32)
ring.push(seed)
_ = ring.pop_ready_windows()

stage_samples = {
    "codec": [],
    "vad": [],
    "anti_spoof": [],
    "fusion": [],
    "total": [],
}
errors = 0

for _ in range(RUNS):
    try:
        d = run_one()
        if d is None:
            continue
        for stage in stage_samples:
            v = d.get(stage, 0.0)
            if v > 0:
                stage_samples[stage].append(v)
    except Exception as exc:
        errors += 1
        print(f"  ERROR: {exc}")

print()
print(f"SatyaVoice Server-Side Pipeline Latency Benchmark")
print(f"Mode: mock | Runs: {RUNS} | Warmup: {WARMUP} | Errors: {errors}")
print(f"Window: {config.WINDOW_SECONDS}s @ {config.TARGET_SAMPLE_RATE}Hz")
print("=" * 100)
print(
    f"{'Stage':<16} {'p50(ms)':>9} {'p95(ms)':>9} {'p99(ms)':>9}"
    f" {'mean(ms)':>9} {'min(ms)':>8} {'max(ms)':>9} {'n':>5}"
)
print("-" * 100)
for stage, vals in stage_samples.items():
    if vals:
        print(
            f"{stage:<16} "
            f"{pct(vals, 0.50):>9.2f} "
            f"{pct(vals, 0.95):>9.2f} "
            f"{pct(vals, 0.99):>9.2f} "
            f"{statistics.mean(vals):>9.2f} "
            f"{min(vals):>8.2f} "
            f"{max(vals):>9.2f} "
            f"{len(vals):>5}"
        )
print("=" * 100)
