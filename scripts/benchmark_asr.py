"""Benchmark faster-whisper base and small models on a local PCM window.

Usage:
    python scripts/benchmark_asr.py
    python scripts/benchmark_asr.py --models base small --seconds 2
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np


def benchmark(model_size: str, samples: np.ndarray, language: str | None) -> None:
    from faster_whisper import WhisperModel

    started = time.perf_counter()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    load_seconds = time.perf_counter() - started

    started = time.perf_counter()
    segments, info = model.transcribe(
        samples,
        language=language,
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    inference_seconds = time.perf_counter() - started
    print(
        f"{model_size}: load={load_seconds:.2f}s "
        f"inference={inference_seconds:.2f}s "
        f"audio={len(samples) / 16000:.2f}s "
        f"language={getattr(info, 'language', None)} text={text!r}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", default=["base", "small"])
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--language", default=None)
    args = parser.parse_args()
    samples = np.zeros(round(args.seconds * 16000), dtype=np.float32)
    for model_size in args.models:
        benchmark(model_size, samples, args.language)


if __name__ == "__main__":
    main()
