#!/usr/bin/env python3
"""Measured end-to-end latency benchmark for the SatyaVoice decision pipeline.

Streams synthetic speech-like audio over the real WebSocket endpoint and
reports per-stage percentiles (codec, vad, anti_spoof, asr, speaker, fusion,
total) plus the client-observed round-trip time, at p50/p95/p99.

Runs against the configured detector mode, so it measures whatever the
environment actually uses:
  * default (mock detector, development mode) -> measures the pipeline
    scaffolding, NOT a real-model decision. Report it as such.
  * VOICETRUST_VOICE_DETECTOR_MODE=real (models installed) -> measures the
    real decision path; those numbers are the SIH-relevant ones.

Usage:
    python3 scripts/benchmark_latency.py [--port 8000] [--windows 40] [--qps 2]

The server must be running (uvicorn app.main:app). Exit code 0 requires:
  * >= 80% of windows produced a decision snapshot, and
  * either the server-reported total p95 <= 500 ms, or --mode real was not
    requested (mock-mode runs are informational only).
"""
from __future__ import annotations

import argparse
import json
import math
import socket
import statistics
import sys
import time
import urllib.request

import numpy as np

try:
    import websockets  # the `websockets` client library
except ImportError:
    print("error: `pip install websockets` required", file=sys.stderr)
    sys.exit(2)

import os

API_PORT = int(os.environ.get("BENCH_PORT", "8000"))
BASE = f"http://127.0.0.1:{API_PORT}"


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_call() -> str:
    req = urllib.request.Request(
        f"{BASE}/api/v1/call/start",
        data=json.dumps({"caller_id": "bench", "recipient_id": "bench"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["call_id"]


def speech_like(samples_16k: int, seed: int) -> bytes:
    """Synthetic speech-like audio: formant-ish tones + envelope + pauses.

    NOT real speech — sufficient to keep VAD engaged so inference lanes fire.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(samples_16k) / 16000.0
    envelope = 0.6 + 0.4 * np.sin(2 * math.pi * 0.7 * t + seed)
    wave = (
        0.35 * np.sin(2 * math.pi * 180 * t)
        + 0.25 * np.sin(2 * math.pi * 620 * t + 1.1)
        + 0.15 * np.sin(2 * math.pi * 1400 * t + 2.3)
    )
    wave *= envelope
    wave += 0.02 * rng.standard_normal(samples_16k)
    return wave.astype(np.float32).tobytes()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--windows", type=int, default=40, help="decision snapshots to collect")
    parser.add_argument("--qps", type=float, default=2.0, help="frames per second to send")
    parser.add_argument("--port", type=int, default=API_PORT)
    args = parser.parse_args()

    if not _port_open(args.port):
        print(f"error: no server on 127.0.0.1:{args.port} (start uvicorn app.main:app)", file=sys.stderr)
        return 2

    call_id = start_call()
    hop = 0.5
    frame_floats = int(16000 * hop)
    ws_url = f"ws://127.0.0.1:{args.port}/api/v1/call/{call_id}/stream"

    totals, stages = [], {}
    rtts, missed = [], 0
    sent = 0

    async def run() -> None:
        nonlocal sent, missed
        import asyncio

        async with websockets.connect(ws_url, max_size=4 * 1024 * 1024) as ws:
            # Negotiate the browser contract: raw float32 PCM.
            await ws.send(json.dumps({"codec": "pcm", "sample_rate": 16000, "channels": 1}))
            seed = 0
            pending: dict[int, float] = {}
            deadline = time.time() + 60
            while len(totals) < args.windows and time.time() < deadline:
                # Send one hop frame.
                seed += 1
                await ws.send(speech_like(frame_floats, seed))
                sent += 1
                send_t = time.perf_counter()
                # Read every snapshot currently available (server may burst).
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    except (asyncio.TimeoutError, TimeoutError):
                        break
                    if isinstance(raw, bytes):
                        continue
                    msg = json.loads(raw)
                    if "error" in msg:
                        print("server error:", msg["error"], file=sys.stderr)
                        return
                    if "latency_ms" in msg:
                        lat = msg["latency_ms"]
                        totals.append(float(lat.get("total", 0.0)))
                        for stage, statsv in (msg.get("latency_stats") or {}).items():
                            # Keep the LAST snapshot per stage: LATENCY_STATS is
                            # cumulative across the call, so the final values
                            # reflect the full run (n = all decisions).
                            stages[stage] = (statsv.get("p50"), statsv.get("p95"), statsv.get("n"))
                        rtts.append((time.perf_counter() - send_t) * 1000.0)
                    if len(totals) >= args.windows:
                        break
                await asyncio.sleep(max(0.0, (1.0 / args.qps) - (time.perf_counter() - send_t)))

        if sent == 0:
            missed = args.windows

    import asyncio

    asyncio.run(run())

    if not totals:
        print(f"FAIL: no decision snapshots received (sent {sent} frames)")
        return 1

    def pct(xs, q):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(q * len(xs)))]

    print(f"windows sent            : {sent} (expected decisions ≈ {max(0, sent - 7)})")
    print(f"decision snapshots      : {len(totals)}")
    print(f"server total decision ms: p50={pct(totals,.5):.1f} p95={pct(totals,.95):.1f} p99={pct(totals,.99):.1f} max={max(totals):.1f}")
    print(f"client round-trip ms    : p50={pct(rtts,.5):.1f} p95={pct(rtts,.95):.1f} p99={pct(rtts,.99):.1f}")
    print("per-stage server p50/p95 (ms):")
    for stage in ("codec", "vad", "anti_spoof", "asr", "speaker", "fusion", "total"):
        if stage in stages:
            p50, p95, n = stages[stage]
            print(f"  {stage:<10} {p50:.1f} / {p95:.1f} (n={n})")

    real_mode = os.environ.get("VOICETRUST_VOICE_DETECTOR_MODE", "mock") == "real"
    # Each decision needs a full 4 s window = 8 hop frames; the first ~7 sent
    # frames only prime the ring buffer.
    expected = max(0, sent - 7)
    ok_coverage = len(totals) >= 0.8 * expected
    print()
    print(f"detector mode           : {'real (SIH-relevant numbers)' if real_mode else 'MOCK (scaffolding only, not a model claim)'}")
    if not ok_coverage:
        print("FAIL: snapshot coverage below 80%")
        return 1
    p95_total = pct(totals, 0.95)
    if real_mode:
        if p95_total <= 500:
            print(f"PASS: real-mode p95 total {p95_total:.1f} ms <= 500 ms target")
            return 0
        print(f"FAIL: real-mode p95 total {p95_total:.1f} ms > 500 ms target")
        return 1
    print("INFO: mock-mode run — rerun with VOICETRUST_VOICE_DETECTOR_MODE=real + installed models for the SIH claim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
