"""Cross-provider consistency test: Local/Kaggle provider vs HF ZeroGPU Space.

Runs the SAME deterministic audio samples through
  A) the shared local pipeline (hf_zero_gpu.inference, executed on Kaggle GPU)
  B) the production HF ZeroGPU Space over its Gradio API
and reports per-sample absolute score differences, verdict agreement and
model-version agreement against configurable tolerances.

This is the drift detector between the Kaggle implementation and the HF
production implementation. Usage (from repo root on Kaggle):

    python kaggle/consistency.py \
        --space https://devanshshar01-satyavoice-gpu.hf.space \
        --samples 5 [--tolerance 0.02] [--audio-dir path/to/wavs]

With --audio-dir omitted, deterministic synthetic windows are generated so the
comparison is reproducible. Score differences are NOT expected to be
bit-for-bit zero (different GPUs / kernels); tolerance thresholds decide.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
import wave
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

SAMPLE_RATE = 16000
DURATION_S = 4
N_SAMPLES = SAMPLE_RATE * DURATION_S


def make_deterministic_window(seed: int, kind: str = "tone") -> np.ndarray:
    """Deterministic pseudo-audio so both providers see identical input."""
    rng = np.random.RandomState(seed)
    t = np.arange(N_SAMPLES, dtype=np.float64) / SAMPLE_RATE
    if kind == "tone":
        f0 = 120 + seed % 200
        x = 0.5 * np.sin(2 * np.pi * f0 * t)
        x += 0.2 * np.sin(2 * np.pi * (2 * f0) * t)
    else:  # noise
        x = 0.4 * rng.randn(N_SAMPLES)
    x += 0.01 * rng.randn(N_SAMPLES)
    return x.astype(np.float32)


def list_wavs(audio_dir: str, limit: int) -> list:
    files = sorted(Path(audio_dir).glob("*.wav"))[:limit]
    out = []
    for f in files:
        import soundfile as sf  # deferred dependency

        data, sr = sf.read(str(f), dtype="float32", always_2d=True)
        mono = data.mean(axis=1)
        out.append((f.name, mono, sr))
    return out


def run_local(x: np.ndarray) -> dict:
    from hf_zero_gpu import inference as pipeline

    return pipeline.infer(x)


def run_hf(x: np.ndarray, space: str, hf_token: str | None) -> dict:
    """Upload -> queue -> stream via the Gradio 6 queue API (/gradio_api)."""
    import io

    import requests  # Kaggle ships requests

    api = f"{space.rstrip('/')}/gradio_api"
    headers = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}

    # Encode the float window to a 16-bit WAV in memory
    buf = io.BytesIO()
    with wave.open(buf, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    wav_bytes = buf.getvalue()

    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="sample.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode() + wav_bytes + f"\r\n--{boundary}--\r\n".encode()
    r = requests.post(
        f"{api}/upload", data=body,
        headers={**headers,
                 "Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=60,
    )
    r.raise_for_status()
    server_path = r.json()[0]

    payload = {"data": [{"path": server_path,
                         "meta": {"_type": "gradio.FileData"}}]}
    r = requests.post(
        f"{api}/call/infer", data=json.dumps(payload),
        headers={**headers, "Content-Type": "application/json"}, timeout=60,
    )
    r.raise_for_status()
    event_id = r.json()["event_id"]

    with requests.get(f"{api}/call/infer/{event_id}", headers=headers,
                      stream=True, timeout=600) as resp:
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data:"):
                data = json.loads(line[5:].strip())
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    return data[0]
                if isinstance(data, dict):
                    return data
    raise RuntimeError("SSE stream ended without a result")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--space",
                    default="https://devanshshar01-satyavoice-gpu.hf.space")
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--audio-dir", default=None)
    ap.add_argument("--tolerance", type=float, default=0.02,
                    help="max |score difference| for consistency PASS")
    ap.add_argument("--hf-token", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from hf_zero_gpu import config as cfg

    print("=" * 60)
    print("SatyaVoice cross-provider consistency")
    print("=" * 60)
    print(f"antispoof checkpoint : {cfg.ANTISPOOF_MODEL_ID}")
    print(f"speaker checkpoint   : {cfg.SPEAKER_MODEL_ID}")
    print(f"tolerance            : {args.tolerance}")
    if cfg.ANTISPOOF_MODEL_ID == "facebook/wav2vec2-xls-r-300m":
        print("WARNING: BASE XLS-R loaded -- NOT the final SatyaVoice "
              "anti-spoof model. Consistency still validates the pipeline, "
              "but label results accordingly.")

    # Build sample set
    samples = []
    if args.audio_dir:
        for name, mono, sr in list_wavs(args.audio_dir, args.samples):
            samples.append((name, mono, sr))
    else:
        for i in range(args.samples):
            samples.append(
                (f"synthetic_{i}", make_deterministic_window(i), SAMPLE_RATE))

    rows = []
    for name, x, sr in samples:
        t0 = time.perf_counter()
        a = run_local(x)
        local_ms = (time.perf_counter() - t0) * 1000
        t0 = time.perf_counter()
        b = run_hf(x, args.space, args.hf_token)
        hf_ms = (time.perf_counter() - t0) * 1000

        if a.get("status") != "ok" or b.get("status") != "ok":
            print(f"[{name}] SKIP -- provider error "
                  f"(local={a.get('status')}, hf={b.get('status')})")
            rows.append({"sample": name, "status": "error"})
            continue

        d_spoof = abs(a["spoof_probability"] - b["spoof_probability"])
        emb_a = np.asarray(a["speaker_embedding"], dtype=np.float64)
        emb_b = np.asarray(b["speaker_embedding"], dtype=np.float64)
        d_emb = float(np.linalg.norm(emb_a - emb_b))
        versions_match = (
            a["model_version_antispoof"] == b["model_version_antispoof"]
            and a["model_version_speaker"] == b["model_version_speaker"]
        )
        ok = d_spoof <= args.tolerance and versions_match
        rows.append({
            "sample": name,
            "kaggle_spoof": a["spoof_probability"],
            "hf_spoof": b["spoof_probability"],
            "abs_diff_spoof": d_spoof,
            "kaggle_emb_l2_vs_hf": d_emb,
            "versions_match": versions_match,
            "local_ms": round(local_ms, 1),
            "hf_ms": round(hf_ms, 1),
            "verdict": "PASS" if ok else "FAIL",
        })
        print(f"[{name}] dSpoof={d_spoof:.5f} dEmbL2={d_emb:.4f} "
              f"versions={'OK' if versions_match else 'MISMATCH'} "
              f"local={local_ms:.0f}ms hf={hf_ms:.0f}ms -> "
              f"{'PASS' if ok else 'FAIL'}")

    passed = sum(1 for r in rows if r.get("verdict") == "PASS")
    print("-" * 60)
    print(f"consistency: {passed}/{len(rows)} samples within tolerance "
          f"({args.tolerance})")
    report = {
        "space": args.space,
        "tolerance": args.tolerance,
        "antispoof_model": cfg.ANTISPOOF_MODEL_ID,
        "speaker_model": cfg.SPEAKER_MODEL_ID,
        "rows": rows,
    }
    out = (Path(args.out) if args.out else
           _REPO_ROOT / "reports" /
           f"satyavoice_consistency_{time.strftime('%Y%m%d_%H%M%S')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"report written: {out}")
    return 0 if passed == len(rows) and rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
