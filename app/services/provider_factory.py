"""
Provider factory: selects the inference provider via configuration.

    INFERENCE_PROVIDER=detector   (default) preserves the current production
                                  behaviour exactly: Render runs its own
                                  in-process detectors (ml_detector.py +
                                  speaker_vault.py). Nothing changes.
    INFERENCE_PROVIDER=zerogpu    route windows to the Hugging Face ZeroGPU
                                  Space (production HF path). The Render
                                  deployment spelling
                                  VOICETRUST_DETECTOR_MODE=remote_hf is a
                                  pure alias of this provider.
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

PROVIDER_ZEROGPU = "zerogpu"
PROVIDER_REMOTE_HF = "remote_hf"
PROVIDER_LOCAL = "local"
PROVIDER_REAL = "real"
PROVIDER_DETECTOR = "detector"
PROVIDER_MOCK = "mock"

# "local" is what Kaggle sets; documented alias "kaggle" maps onto it because
# Kaggle does not need a redundant provider of its own (it IS local GPU).
# "remote_hf" is the Render deployment spelling of the same Hugging Face
# ZeroGPU remote provider -- a pure alias, not a separate implementation.
_PROVIDER_ALIASES = {
    "kaggle": PROVIDER_LOCAL,
    "real": PROVIDER_REAL,
    "mock": PROVIDER_MOCK,
    "detector": PROVIDER_MOCK,  # legacy detector mode maps to mock unless explicitly real
    PROVIDER_REMOTE_HF: PROVIDER_ZEROGPU,
}


def _resolve_env(env: Optional[dict] = None) -> dict:
    source = dict(os.environ)
    if env is not None:
        source.update(env)
    return source


def get_configured_provider_name(env: Optional[dict] = None) -> str:
    """Normalized INFERENCE_PROVIDER / VOICETRUST_DETECTOR_MODE value (default: zerogpu)."""
    source = _resolve_env(env)
    raw = (
        source.get("VOICETRUST_DETECTOR_MODE")
        or source.get("INFERENCE_PROVIDER")
        or PROVIDER_ZEROGPU
    ).strip().lower()
    return _PROVIDER_ALIASES.get(raw, raw)


def get_inference_provider(
    env: Optional[dict] = None,
) -> InferenceProvider:
    """Instantiate the configured provider.

    Enforces production safety policy: mock mode is strictly rejected when
    ENVIRONMENT=production. Real production deployments default to ZeroGPU.
    """
    source = _resolve_env(env)
    env_name = (
        source.get("ENVIRONMENT")
        or source.get("VOICETRUST_ENVIRONMENT")
        or "development"
    ).strip().lower()
    is_production = env_name in {"production", "prod"}

    name = get_configured_provider_name(source)


    if is_production and name in {PROVIDER_MOCK, PROVIDER_DETECTOR}:
        raise RuntimeError(
            "PRODUCTION ENVIRONMENT SAFETY VIOLATION: "
            "Mock inference provider is strictly prohibited in production. "
            "Production must use a real inference provider (e.g. zerogpu)."
        )

    if name == PROVIDER_ZEROGPU:
        from .zerogpu_provider import ZeroGPUInferenceProvider

        space_url = (source.get("HF_ZERO_GPU_SPACE") or "").strip()
        if not space_url:
            raise RuntimeError(
                "ZeroGPU configuration missing: HF_ZERO_GPU_SPACE is required for ZeroGPUInferenceProvider"
            )
        return ZeroGPUInferenceProvider(
            space_url=space_url,
            hf_token=source.get("HF_TOKEN") or None,
        )

    if name in {PROVIDER_MOCK, PROVIDER_DETECTOR}:
        from .inference_provider import MockInferenceProvider

        return MockInferenceProvider()

    if name == PROVIDER_LOCAL:
        from .local_provider import LocalInferenceProvider

        return LocalInferenceProvider(env=env)

    raise ValueError(
        f"Unknown INFERENCE_PROVIDER / VOICETRUST_DETECTOR_MODE '{name}'. "
        f"Expected one of: {PROVIDER_ZEROGPU}, {PROVIDER_LOCAL}, {PROVIDER_REAL}, {PROVIDER_MOCK}."
    )