"""
Provider factory: selects the inference provider via configuration.

    INFERENCE_PROVIDER=detector   (default) preserves the current production
                                  behaviour exactly: Render runs its own
                                  in-process detectors (ml_detector.py +
                                  speaker_vault.py). Nothing changes.
    INFERENCE_PROVIDER=zerogpu    route windows to the Hugging Face ZeroGPU
                                  Space (production HF path).
    INFERENCE_PROVIDER=local      run the SAME shared ML pipeline
                                  (hf_zero_gpu/inference.py) directly in the
                                  current process on CUDA -- this is what the
                                  Kaggle development environment uses. Kaggle
                                  never becomes a separate pipeline: it simply
                                  executes the canonical provider on its GPU.

Kaggle is a DEVELOPMENT/TESTING/BENCHMARKING environment only; production
defaults must remain unchanged.
"""
from __future__ import annotations

import os
from typing import Optional

from .inference_provider import InferenceProvider, InferenceResult

PROVIDER_DETECTOR = "detector"
PROVIDER_ZEROGPU = "zerogpu"
PROVIDER_LOCAL = "local"

# "local" is what Kaggle sets; documented alias "kaggle" maps onto it because
# Kaggle does not need a redundant provider of its own (it IS local GPU).
_PROVIDER_ALIASES = {"kaggle": PROVIDER_LOCAL}


def get_configured_provider_name(env: Optional[dict] = None) -> str:
    """Normalized INFERENCE_PROVIDER value (default: current behaviour)."""
    source = os.environ if env is None else env
    raw = (source.get("INFERENCE_PROVIDER") or PROVIDER_DETECTOR).strip().lower()
    return _PROVIDER_ALIASES.get(raw, raw)


def get_inference_provider(
    env: Optional[dict] = None,
) -> InferenceProvider:
    """Instantiate the configured provider.

    Raises ValueError for an unknown provider name; falls back to the
    always-available MockInferenceProvider only where the existing production
    fallback already used one.
    """
    name = get_configured_provider_name(env)
    if name == PROVIDER_DETECTOR:
        # Preserve today's production path untouched.
        from .inference_provider import MockInferenceProvider

        return MockInferenceProvider()
    if name == PROVIDER_ZEROGPU:
        from .zerogpu_provider import ZeroGPUInferenceProvider

        source = os.environ if env is None else env
        return ZeroGPUInferenceProvider(
            space_url=source.get("HF_ZERO_GPU_SPACE", ""),
            hf_token=source.get("HF_TOKEN") or None,
        )
    if name == PROVIDER_LOCAL:
        from .local_provider import LocalInferenceProvider

        return LocalInferenceProvider(env=env)
    raise ValueError(
        f"Unknown INFERENCE_PROVIDER '{name}'. "
        f"Expected one of: {PROVIDER_DETECTOR}, {PROVIDER_ZEROGPU}, {PROVIDER_LOCAL}."
    )