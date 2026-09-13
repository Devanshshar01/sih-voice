"""SatyaVoice development/benchmarking script for Kaggle GPU.

Runs the SAME shared inference pipeline as production
(``hf_zero_gpu/inference.py``) via ``app.services.local_provider`` and
produces:

  * a single-sample sanity inference  (``--mode sanity``)
  * a 100+ window latency benchmark   (``--mode benchmark``)
  * an optional labelled eval         (``--mode evaluate --data-dir DIR``)

Reports are written to ``kaggle/reports/`` as JSON + CSV. Kaggle is a
DEVELOPMENT/TESTING environment only -- HF ZeroGPU remains the production
provider, and benchmark numbers here are NOT automatic SIH compliance claims
(the <500 ms SIH target refers to the full end-to-end verdict path, not model
inference alone; p50/p95/p99 of the model critical path are reported
separately).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.local_provider import LocalInferenceProvider  # noqa: E402

SAMPLE_RATE = 16000
WINDOW_SAMPLES = SAMPLE_RATE * 4  # the canonical 4-second window
WARMUP_RUNS = 5
BENCH_RUNS = 100
REPORT_DIR = Path(__file__).resolve().parent / "reports"


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, timeout=10,
            capture_output=True, text=True,
        ).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def environment_report(provider: LocalInferenceProvider) -> dict:
    info = provider.describe()
    info["git_commit"] = _git_commit()
    return info


def single_inference(audio: np.ndarray) -> dict:
    """One timed inference split into XLS-R and ECAPA phases, CUDA-synced so
    measured latency is real kernel time (not async launch time). Scoring
    mirrors the production path: softmax over logits, spoof-class index from
    the model's own label map (NOT sigmoid)."""
    import torch

    from hf_zero_gpu import inference as pipeline

    pipeline._load_models()
    pipeline._ensure_models_on_device()
    device = pipeline.DEVICE
    if "cuda" in str(device):
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()

    prepared = pipeline._prepare_audio(audio)
    t0 = time.perf_counter()
    inputs = pipeline._antispoof_processor(
        prepared, sampling_rate=pipeline.SAMPLE_RATE,
        return_tensors="pt", padding=True,
    )
    inputs = {key: value.to(device) for key, value in inputs.items()}
    with torch.inference_mode():
        logits = pipeline._antispoof_model(**inputs).logits
        probabilities = torch.softmax(logits, dim=-1)[0]
    if "cuda" in str(device):
        torch.cuda.synchronize()
    xlsr_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    with torch.inference_mode():
        waveform = torch.from_numpy(prepared).float().unsqueeze(0).to(device)
        embedding_tensor = pipeline._speaker_model.encode_batch(waveform)
    if "cuda" in str(device):
        torch.cuda.synchronize()
    ecapa_ms = (time.perf_counter() - t1) * 1000.0

    peak_mem = (
        torch.cuda.max_memory_allocated() / (1024 ** 2) if "cuda" in str(device) else 0.0
    )
    return {
        "spoof_probability": float(
            probabilities[pipeline._spoof_label_index()].item()
        ),
        "speaker_embedding_dim": int(embedding_tensor.squeeze().shape[0]),
        "xlsr_ms": round(xlsr_ms, 2),
        "ecapa_ms": round(ecapa_ms, 2),
        "total_ms": round(xlsr_ms + ecapa_ms, 2),
        "peak_vram_mb": round(peak_mem, 1),
        "device": str(device),
    }


def mode_sanity(provider: LocalInferenceProvider, audio: np.ndarray) -> dict:
    """Single-sample sanity test -- prints the structured result. No fakes."""
    import torch

    result = provider.infer_audio_window_sync(audio)
    phases = single_inference(audio)
    info = environment_report(provider)
    from hf_zero_gpu import config as pipeline_config
    from hf_zero_gpu import inference as pipeline

    print("\n" + "=" * 60)
    print("SatyaVoice inference")
    print("=" * 60)
    print("provider:                local (kaggle)")
    print(f"sample_rate:            {result.sample_rate}")
    print(f"duration_ms:            {result.duration_ms}")
    print(f"success:                {result.success}")
    if result.success:
        print(f"spoof_probability:      {result.spoof_probability:.4f}")
        print(f"speaker_embedding_dim:  {len(result.speaker_embedding)}")
        print(f"xlsr_ms:                {phases['xlsr_ms']}")
        print(f"ecapa_ms:               {phases['ecapa_ms']}")
        print(f"total_ms:               {phases['total_ms']}")
    else:
        print(f"error_code:             {result.error_code}")
        print(f"error_message:          {result.error_message}")
    print(f"model_version_antispoof: {result.model_version_antispoof}")
    print(f"model_version_speaker:   {result.model_version_speaker}")
    try:
        state = pipeline._antispoof_model.state_dict()
        total = sum(float(p.detach().float().sum()) for p in state.values())
        print(f"antispoof_weight_sumhash: {total:.6e}")
    except Exception:  # noqa: BLE001
        pass
    if pipeline_config.ANTISPOOF_MODEL_ID == "facebook/wav2vec2-xls-r-300m":
        print(
            "\n*** WARNING: BASE XLS-R -- NOT THE FINAL SATYAVOICE ANTI-SPOOF "
            "MODEL. Set ANTISPOOF_MODEL_ID to the fine-tuned checkpoint "
            "before reporting production results. ***"
        )
    print("=" * 60)
    return {"phases": phases, "result_ok": bool(result.success)}


def _stats(series) -> dict:
    s = sorted(series)
    return {
        "p50": round(s[int(len(s) * 0.50)], 2),
        "p95": round(s[min(int(len(s) * 0.95), len(s) - 1)], 2),
        "p99": round(s[min(int(len(s) * 0.99), len(s) - 1)], 2),
        "mean": round(statistics.fmean(s), 2),
    }


def mode_benchmark(provider: LocalInferenceProvider, audio: np.ndarray,
                   runs: int = BENCH_RUNS) -> dict:
    """Latency benchmark: warm-up excluded, CUDA-synced, p50/p95/p99."""
    print(f"benchmark: {WARMUP_RUNS} warm-up + {runs} measured runs ...")
    for _ in range(WARMUP_RUNS):
        provider.infer_audio_window_sync(audio)

    xlsr, ecapa, total, mem = [], [], [], []
    for i in range(runs):
        phases = single_inference(audio)
        xlsr.append(phases["xlsr_ms"])
        ecapa.append(phases["ecapa_ms"])
        total.append(phases["total_ms"])
        mem.append(phases["peak_vram_mb"])
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{runs}")

    report = {
        "runs": runs,
        "warmup_excluded": WARMUP_RUNS,
        "xlsr_ms": _stats(xlsr),
        "ecapa_ms": _stats(ecapa),
        "combined_critical_path_ms": _stats(total),
        "avg_peak_vram_mb": round(statistics.fmean(mem), 1),
        "max_peak_vram_mb": round(max(mem), 1),
        "device": phases["device"],
        "note": (
            "model critical-path latency only; the SIH <500 ms target is the "
            "full end-to-end verdict path (frontend -> Render -> inference -> "
            "risk engine -> UI) and is measured separately."
        ),
    }
    print(json.dumps(report, indent=2))
    return report


def _classification_metrics(scores, labels) -> dict:
    """ROC-AUC / PR-AUC / EER / F1 / precision / recall / balanced accuracy,
    numpy-only (no extra deps). Scores = spoof probability, label 1 = fake."""
    scores_a = np.asarray(scores, dtype=np.float64)
    labels_a = np.asarray(labels)
    order = np.argsort(-scores_a)
    ranked = labels_a[order]
    pos = float(ranked.sum())
    neg = float(len(ranked) - pos)
    tps = np.cumsum(ranked)
    fps = np.cumsum(1.0 - ranked)
    tpr = np.concatenate([[0.0], tps / max(pos, 1), [1.0]])
    fpr = np.concatenate([[0.0], fps / max(neg, 1), [1.0]])
    roc_auc = float(np.trapz(tpr, fpr))
    precision_curve = np.concatenate([[1.0], tps / np.maximum(tps + fps, 1e-12)])
    pr_recall = np.concatenate([[0.0], tps / max(pos, 1)])
    pr_auc = float(-np.trapz(precision_curve, pr_recall))
    eer = float(np.interp(0.5, tpr, fpr))
    best_f1 = best_p = best_r = 0.0
    for p_, r_ in zip(precision_curve[1:], tpr[1:-1]):
        f1 = 2 * p_ * r_ / max(p_ + r_, 1e-12)
        if f1 > best_f1:
            best_f1, best_p, best_r = f1, float(p_), float(r_)
    return {
        "roc_auc": round(roc_auc, 4),
        "pr_auc": round(pr_auc, 4),
        "eer": round(eer, 4),
        "f1": round(best_f1, 4),
        "precision": round(best_p, 4),
        "recall": round(best_r, 4),
        "balanced_accuracy": round((best_r + (1 - eer)) / 2, 4),
    }


def _per_language(rows: list, min_samples: int = 5) -> dict:
    """Per-language metrics ONLY when both classes have enough labelled
    samples (Hindi/Tamil/Telugu/Bengali/Marathi/English expected as filename
    prefixes hi_/ta_/te_/bn_/mr_/en_). Sample counts always shown; metrics
    are NEVER fabricated for insufficient data."""
    by_lang: dict = {}
    for row in rows:
        if row.get("label") is None:
            continue
        prefix = (row["file"].split("_")[0] or "unknown").lower()
        by_lang.setdefault(prefix, []).append(row)
    out = {}
    for lang, lrows in by_lang.items():
        n_pos = sum(1 for r in lrows if r["label"])
        n_neg = len(lrows) - n_pos
        entry = {"n_total": len(lrows), "n_genuine": n_neg, "n_deepfake": n_pos}
        if min(n_pos, n_neg) >= min_samples:
            entry["metrics"] = _classification_metrics(
                [r["spoof_probability"] for r in lrows],
                [r["label"] for r in lrows],
            )
        else:
            entry["metrics"] = "insufficient labelled samples -- not reported"
        out[lang] = entry
    return out


def _read_wav_float32(path: Path):
    import wave as wavemod

    with wavemod.open(str(path)) as w:
        raw = w.readframes(w.getnframes())
        sr = w.getframerate()
        sw = w.getsampwidth()
    if sw == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        x = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:  # 8-bit unsigned
        x = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    return x, sr


def _label_for(stem: str):
    """Ground truth from filename prefix; None when unknown (never guessed).
    Optional language prefix (hi_/ta_/te_/bn_/mr_/en_) enables per-language
    reporting."""
    low = stem.lower()
    if low.startswith(("fake_", "spoof_")):
        return 1
    if low.startswith(("real_", "genuine_", "bonafide_")):
        return 0
    return None


def mode_evaluate(provider: LocalInferenceProvider, data_dir: str) -> dict:
    """Labelled evaluation (ROC-AUC / PR-AUC / EER / F1 / precision / recall /
    balanced accuracy). Ground truth comes from filename prefixes via
    _label_for(); unlabelled rows are scored but excluded from metrics. NO
    METRIC IS EVER INVENTED: without labels this mode reports scores only and
    marks the run qualitative."""
    files = sorted(Path(data_dir).glob("*.wav"))
    if not files:
        raise SystemExit(f"no .wav files found in {data_dir}")
    rows = []
    for i, f in enumerate(files):
        x, sr = _read_wav_float32(f)
        t0 = time.perf_counter()
        result = provider.infer_audio_window_sync(x)
        wall_ms = (time.perf_counter() - t0) * 1000.0
        rows.append({
            "file": f.name,
            "label": _label_for(f.stem),
            "source_sr": sr,
            "spoof_probability": (
                result.spoof_probability if result.success else None
            ),
            "inference_time_ms": result.inference_time_ms,
            "wall_ms": round(wall_ms, 2),
            "success": result.success,
            "error_code": result.error_code,
        })
        if (i + 1) % 20 == 0:
            print(f"  {i + 1}/{len(files)} scored")
    ok = [r for r in rows if r["success"] and r["spoof_probability"] is not None]
    labelled = [r for r in ok if r["label"] is not None]
    report: dict = {
        "mode": "evaluate",
        "data_dir": str(data_dir),
        "n_files": len(rows),
        "n_scored": len(ok),
        "n_labelled": len(labelled),
        "language_counts": _per_language(ok),
    }
    if labelled:
        report["metrics"] = _classification_metrics(
            [r["spoof_probability"] for r in labelled],
            [r["label"] for r in labelled],
        )
        report["per_language"] = _per_language(labelled)
    else:
        report["metrics"] = (
            "QUALITATIVE ONLY -- no usable ground-truth labels in filenames; "
            "no metrics invented."
        )
    report["rows"] = rows
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=2))
    return report


def write_report(report: dict, prefix: str = "satyavoice_kaggle_benchmark") -> Path:
    """Persist a report as JSON + CSV under kaggle/reports/ (Step 23)."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = REPORT_DIR / f"{prefix}_{ts}.json"
    env = report.pop("environment", None) or {}
    full = {
        "timestamp": ts,
        "git_commit": env.get("git_commit"),
        "gpu": env.get("device"),
        "cuda_version": env.get("cuda_version"),
        "torch_version": env.get("torch_version"),
        "model_version_antispoof": report.get("model_version_antispoof"),
        "model_version_speaker": report.get("model_version_speaker"),
        **report,
    }
    json_path.write_text(json.dumps(full, indent=2))
    csv_path = REPORT_DIR / f"{prefix}_{ts}.csv"
    flat = {k: v for k, v in full.items() if isinstance(v, (int, float, str, bool))}
    with open(csv_path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerows(flat.items())
    print(f"report written: {json_path.name} / {csv_path.name}")
    return json_path


def make_tone_window() -> np.ndarray:
    t = np.arange(WINDOW_SAMPLES, dtype=np.float64) / SAMPLE_RATE
    return (0.4 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _load_audio(path: str) -> np.ndarray:
    return _read_wav_float32(Path(path))[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["sanity", "benchmark", "evaluate"], default="sanity"
    )
    parser.add_argument("--data-dir", default=None, help="labelled .wav folder")
    parser.add_argument("--runs", type=int, default=BENCH_RUNS)
    parser.add_argument("--audio", default=None, help="one .wav for sanity mode")
    args = parser.parse_args()

    provider = LocalInferenceProvider(env=dict(os.environ))
    env = environment_report(provider)
    print(json.dumps(env, indent=2))
    from hf_zero_gpu import config as pipeline_config

    if pipeline_config.ANTISPOOF_MODEL_ID == "facebook/wav2vec2-xls-r-300m":
        print(
            "*** CHECKPOINT WARNING: BASE XLS-R (facebook/wav2vec2-xls-r-300m) "
            "-- NOT THE FINAL SATYAVOICE ANTI-SPOOF MODEL. Any result produced "
            "with this checkpoint must be labelled as base-model only. ***"
        )

    if args.mode == "sanity":
        audio = _load_audio(args.audio) if args.audio else make_tone_window()
        mode_sanity(provider, audio)
    elif args.mode == "benchmark":
        audio = _load_audio(args.audio) if args.audio else make_tone_window()
        first = provider.infer_audio_window_sync(audio)
        report = mode_benchmark(provider, audio, runs=args.runs)
        report["environment"] = env
        report["model_version_antispoof"] = first.model_version_antispoof
        report["model_version_speaker"] = first.model_version_speaker
        write_report(report)
    else:
        if not args.data_dir:
            raise SystemExit("--mode evaluate requires --data-dir DIR")
        report = mode_evaluate(provider, args.data_dir)
        report["environment"] = env
        report["model_version_antispoof"] = pipeline_config.ANTISPOOF_MODEL_ID
        report["model_version_speaker"] = pipeline_config.SPEAKER_MODEL_ID
        write_report(report)


if __name__ == "__main__":
    main()
