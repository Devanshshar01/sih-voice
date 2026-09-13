"""WebSocket streaming latency benchmark using FastAPI TestClient.

Measures the actual in-process round-trip (T2→T8 in the SIH model):
  Render receives WebSocket frame → codec → VAD → inference → fusion → JSON sent back

This is the server-service latency segment; network_to_render and browser
segments must be measured separately from a deployed environment.
"""
import os
import io
import statistics
import sys
import time

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.insert(0, ".")
os.environ["VOICETRUST_DETECTOR_MODE"] = "mock"
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")
os.environ["VOICETRUST_WS_JWT_SECRET"] = "bench-ws-secret-x1234"
os.environ["VOICETRUST_WS_AUTH_ENABLED"] = "true"
os.environ["VOICETRUST_ASR_MODE"] = "manual"

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app import config
from app.core.ws_auth import create_access_token

RUNS = 200
WARMUP = 20

# Pre-fill ring buffer by computing number of hops to fill one full window
FIRST_WINDOW_HOPS = config.WINDOW_SAMPLES // config.HOP_SAMPLES  # == 8

hop_audio = np.random.default_rng(42).standard_normal(
    config.HOP_SAMPLES
).astype(np.float32)
hop_bytes = hop_audio.tobytes()


def pct(vals, q):
    if not vals:
        return 0.0
    s = sorted(vals)
    idx = (len(s) - 1) * q
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (idx - lo)


round_trip_ms = []
latency_stage_totals = {}
errors = 0
timed_out = 0
successful = 0

with TestClient(app) as client:
    # Each call gets a fresh session for isolation
    def _measure_session(n_windows: int, warmup: bool = False):
        global errors, timed_out, successful

        caller_id = f"bench-user-{time.time_ns()}"
        resp = client.post(
            "/api/v1/call/start",
            json={"caller_id": caller_id, "recipient_id": "bench-desk"},
        )
        if resp.status_code != 200:
            errors += 1
            return []
        call_id = resp.json()["call_id"]
        token = create_access_token(caller_id)

        timings = []
        try:
            with client.websocket_connect(
                f"/api/v1/call/{call_id}/stream?token={token}"
            ) as ws:
                # Fill up to first full window (no telemetry before that)
                for _ in range(FIRST_WINDOW_HOPS - 1):
                    ws.send_bytes(hop_bytes)

                # Now each hop produces a telemetry frame
                for _ in range(n_windows):
                    t_send = time.perf_counter()
                    ws.send_bytes(hop_bytes)
                    msg = ws.receive_json()
                    t_recv = time.perf_counter()
                    rt = (t_recv - t_send) * 1000.0
                    if not warmup:
                        timings.append(rt)
                        successful += 1
                        # Collect server-side stage breakdown from latency_ms
                        lm = msg.get("latency_ms", {})
                        for stage, v in lm.items():
                            if v and v > 0:
                                latency_stage_totals.setdefault(stage, []).append(v)
        except Exception as exc:
            errors += 1
        return timings

    # Warm-up (not counted in stats)
    _measure_session(n_windows=WARMUP, warmup=True)

    # Measured runs: distribute across multiple sessions for realism
    # 10 sessions × 20 windows each = 200 total measurements
    for session_idx in range(10):
        session_timings = _measure_session(n_windows=20)
        round_trip_ms.extend(session_timings)

print()
print("SatyaVoice WebSocket Round-Trip Latency Benchmark (TestClient, mock mode)")
print(f"Sessions: 10 | Windows measured: {len(round_trip_ms)} | Errors: {errors}")
print("=" * 100)
print(
    f"{'Metric':<30} {'p50(ms)':>9} {'p95(ms)':>9} {'p99(ms)':>9}"
    f" {'mean(ms)':>9} {'min(ms)':>8} {'max(ms)':>9}"
)
print("-" * 100)

if round_trip_ms:
    print(
        f"{'WS send->recv (service)    ':<30} "

        f"{pct(round_trip_ms, 0.50):>9.2f} "
        f"{pct(round_trip_ms, 0.95):>9.2f} "
        f"{pct(round_trip_ms, 0.99):>9.2f} "
        f"{statistics.mean(round_trip_ms):>9.2f} "
        f"{min(round_trip_ms):>8.2f} "
        f"{max(round_trip_ms):>9.2f}"
    )

print("=" * 100)
print()
print("Server-reported stage breakdown (from latency_ms field in telemetry):")
print("-" * 100)
for stage, vals in latency_stage_totals.items():
    if vals:
        print(
            f"  {stage:<20} "
            f"p50={pct(vals, 0.50):>8.2f}ms  "
            f"p95={pct(vals, 0.95):>8.2f}ms  "
            f"mean={statistics.mean(vals):>8.2f}ms  "
            f"n={len(vals)}"
        )
print()
print("NOTE: This measures in-process TestClient service latency only.")
print("      Full E2E = service_ms + network_to_render_ms + render_to_hf_ms")
print("                + hf_model_ms + hf_to_render_ms + render_to_browser_ms")
