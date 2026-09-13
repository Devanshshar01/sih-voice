"""
Local inference provider: runs the SHARED SatyaVoice ML pipeline directly in
the current process on the machine's GPU.

This is the provider the Kaggle development environment uses. Kaggle does NOT
have its own copy of the ML pipeline -- it executes this exact provider on its
GPU. The pipeline (audio contract, XLS-R inference, ECAPA-TDNN embedding,
result schema, error handling) is imported from the canonical implementation
in ``hf_zero_gpu/inference.py``, which is the same code the production Hugging
Face ZeroGPU Space runs. No model code is duplicated.

Device policy:
  * CUDA is selected automatically when available.
  * CPU is used ONLY when explicitly configured (DEVICE=cpu) or when CUDA is
    genuinely absent -- never silently degrade a benchmark.
Failure policy:
  * never fabricates a spoof_probability (no fake 0.5); returns an explicit
    ``InferenceResult.failure(error_code="INFERENCE_UNAVAILABLE", ...)``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np

from .inference_provider import InferenceProvider, InferenceResult

# Repo root, so ``hf_zero_gpu`` (the canonical pipeline) is importable from
# any working directory -- Render, Kaggle, or a developer laptop.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


class LocalInferenceProvider(InferenceProvider):
    """Same pipeline as HF ZeroGPU, executed in-process (Kaggle / local GPU)."""

    def __init__(self, env: Optional[dict] = None):
        self.env = env if env is not None else dict(os.environ)
        # Apply Kaggle/dev configuration to the shared pipeline's config module
        # BEFORE it is imported, so the checkpoint and device come from the
        # same env vars the notebook documents (ANTISPOOF_MODEL_ID,
        # SPEAKER_MODEL_ID, DEVICE).
        if self.env.get("ANTISPOOF_MODEL_ID"):
            os.environ["ANTISPOOF_MODEL_ID"] = self.env["ANTISPOOF_MODEL_ID"]
        if self.env.get("SPEAKER_MODEL_ID"):
            os.environ["SPEAKER_MODEL_ID"] = self.env["SPEAKER_MODEL_ID"]
        if self.env.get("DEVICE"):
            os.environ["DEVICE"] = self.env["DEVICE"]
        self._pipeline = None  # lazy import: torch must be installed

    # ------------------------------------------------------------------
    # Device selection
    # ------------------------------------------------------------------
    def _resolve_device(self) -> str:
        import torch

        configured = (self.env.get("DEVICE") or "").strip().lower()
        if configured == "cpu":
            return "cpu"  # explicit only
        if torch.cuda.is_available():
            return "cuda"
        if configured.startswith("cuda"):
            raise RuntimeError(
                "DEVICE is configured as CUDA but torch.cuda.is_available() "
                "is False -- refusing to silently fall back to CPU (this "
                "would produce meaningless latency benchmarks)."
            )
        return "cpu"

    def _ensure_pipeline(self):
        """Import and configure the canonical shared pipeline (once)."""
        if self._pipeline is not None:
            return self._pipeline
        from hf_zero_gpu import inference as pipeline

        self._pipeline = pipeline
        return pipeline

    # ------------------------------------------------------------------
    # InferenceProvider implementation
    # ------------------------------------------------------------------
    def infer_audio_window_sync(self, audio_window: np.ndarray) -> InferenceResult:
        try:
            pipeline = self._ensure_pipeline()
        except ImportError as exc:
            return InferenceResult.failure(
                "INFERENCE_UNAVAILABLE",
                f"Shared pipeline not importable (torch/transformers/"
                f"speechbrain required): {exc}",
                provider="local",
            )

        try:
            payload = pipeline.infer(audio_window)
        except ValueError as exc:
            # Invalid input contract -> explicit failure, no fake score.
            return InferenceResult.failure(
                "INVALID_AUDIO_INPUT", str(exc), provider="local"
            )
        except Exception as exc:  # noqa: BLE001
            return InferenceResult.failure(
                "INFERENCE_UNAVAILABLE",
                f"{type(exc).__name__}: {exc}",
                provider="local",
            )

        if payload.get("status") != "ok":
            error = payload.get("error") or {}
            return InferenceResult.failure(
                "INFERENCE_UNAVAILABLE",
                str(error.get("message", "unknown pipeline error")),
                provider="local",
                model_version_antispoof=str(
                    payload.get("model_version_antispoof", "unknown")
                ),
                model_version_speaker=str(
                    payload.get("model_version_speaker", "unknown")
                ),
            )

        return InferenceResult(
            spoof_probability=float(payload["spoof_probability"]),
            speaker_embedding=list(payload["speaker_embedding"]),
            inference_time_ms=float(payload["inference_time_ms"]),
            model_version_antispoof=str(payload["model_version_antispoof"]),
            model_version_speaker=str(payload["model_version_speaker"]),
            sample_rate=int(payload["sample_rate"]),
            duration_ms=float(payload["duration_ms"]),
            provider="local",
            success=True,
        )

    def is_available(self) -> bool:
        try:
            import torch  # noqa: F401

            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Environment report (used by the Kaggle notebook env check)
    # ------------------------------------------------------------------
    def describe(self) -> dict:
        info: dict = {"provider": "local", "device": None}
        try:
            import torch

            info["torch_version"] = torch.__version__
            info["cuda_available"] = torch.cuda.is_available()
            if torch.cuda.is_available():
                info["device"] = torch.cuda.get_device_name(0)
                info["cuda_version"] = torch.version.cuda
                info["vram_total_bytes"] = int(
                    torch.cuda.get_device_properties(0).total_memory
                )
        except ImportError:
            info["torch_version"] = None
            info["cuda_available"] = False
        try:
            self._ensure_pipeline()
            from hf_zero_gpu import config as pipeline_config

            info["antispoof_model_id"] = pipeline_config.ANTISPOOF_MODEL_ID
            info["speaker_model_id"] = pipeline_config.SPEAKER_MODEL_ID
            info["device"] = str(pipeline_config.DEVICE)
        except Exception as exc:  # noqa: BLE001
            info["pipeline_error"] = str(exc)
        return info
