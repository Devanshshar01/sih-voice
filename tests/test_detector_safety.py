"""Detector safety & production policy verification tests.

Covers all 7 mandatory test requirements:
  TEST 1: Production + real provider -> real provider selected
  TEST 2: Production + mock configuration -> startup/config rejected
  TEST 3: Development + mock configuration -> MockVoiceDetector allowed
  TEST 4: Production + HF provider unavailable -> explicit inference-unavailable result (NO mock score)
  TEST 5: Production + missing HF credentials/config -> explicit configuration/inference failure (NO mock score)
  TEST 6: Real provider success -> real inference result passes through unchanged
  TEST 7: No code path silently converts an inference exception into spoof_probability = 0.5 or fake score
"""
from __future__ import annotations

import asyncio
import os
from unittest import mock

import numpy as np
import pytest

from app import config
from app.core.parallel_inference import run_window_inference
from app.core.risk_engine import compute_risk
from app.services import ml_detector, provider_factory
from app.services.inference_provider import InferenceResult, MockInferenceProvider
from app.services.zerogpu_provider import ZeroGPUInferenceProvider

WINDOW = np.zeros(64000, dtype=np.float32)  # 4 s @ 16 kHz contract


# ---------------------------------------------------------------------------
# TEST 1: Production + real provider -> real provider is selected.
# ---------------------------------------------------------------------------
def test_production_real_provider_selected() -> None:
    env = {
        "ENVIRONMENT": "production",
        "VOICETRUST_DETECTOR_MODE": "zerogpu",
        "HF_ZERO_GPU_SPACE": "https://huggingface.co/spaces/test/space",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        mode = config.validate_detector_config(env)
        assert mode == "zerogpu"
        provider = provider_factory.get_inference_provider(env)
        assert isinstance(provider, ZeroGPUInferenceProvider)


# ---------------------------------------------------------------------------
# TEST 1b: Production + Render alias VOICETRUST_DETECTOR_MODE=remote_hf ->
# resolves to the same ZeroGPU remote provider (no separate code path).
# ---------------------------------------------------------------------------
def test_production_remote_hf_alias_selects_zerogpu() -> None:
    env = {
        "ENVIRONMENT": "production",
        "VOICETRUST_DETECTOR_MODE": "remote_hf",
        "HF_ZERO_GPU_SPACE": "https://huggingface.co/spaces/test/space",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        assert config.validate_detector_config(env) == "zerogpu"
        provider = provider_factory.get_inference_provider(env)
        assert isinstance(provider, ZeroGPUInferenceProvider)
        assert isinstance(
            ml_detector.get_detector("remote_hf"),
            ml_detector.ZeroGPUVoiceDetectorAdapter,
        )


# ---------------------------------------------------------------------------
# TEST 2: Production + mock configuration -> startup/config is rejected.
# ---------------------------------------------------------------------------
def test_production_mock_configuration_rejected() -> None:
    env = {
        "ENVIRONMENT": "production",
        "VOICETRUST_DETECTOR_MODE": "mock",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        # 1. Config validation fails
        with pytest.raises(RuntimeError, match="strictly prohibited in production"):
            config.validate_detector_config(env)

        # 2. Provider factory fails
        with pytest.raises(RuntimeError, match="strictly prohibited in production"):
            provider_factory.get_inference_provider(env)

        # 3. Detector factory fails
        with pytest.raises(RuntimeError, match="strictly prohibited in production"):
            ml_detector.get_detector("mock")


# ---------------------------------------------------------------------------
# TEST 3: Development + mock configuration -> MockVoiceDetector allowed.
# ---------------------------------------------------------------------------
def test_development_mock_configuration_allowed() -> None:
    env = {
        "ENVIRONMENT": "development",
        "VOICETRUST_DETECTOR_MODE": "mock",
    }
    with mock.patch.dict(os.environ, env, clear=True):
        mode = config.validate_detector_config(env)
        assert mode == "mock"
        provider = provider_factory.get_inference_provider(env)
        assert isinstance(provider, MockInferenceProvider)
        detector = ml_detector.get_detector("mock")
        assert isinstance(detector, ml_detector.MockVoiceDetector)


# ---------------------------------------------------------------------------
# TEST 4: Production + HF provider unavailable -> explicit inference-unavailable result (NO mock score).
# ---------------------------------------------------------------------------
def test_production_hf_provider_unavailable_returns_explicit_error() -> None:
    with mock.patch("app.services.zerogpu_provider.Client"):
        provider = ZeroGPUInferenceProvider("https://huggingface.co/spaces/test/space")

    # Mock HF client failure (e.g. timeout / HTTP error)
    provider._client = mock.MagicMock()
    provider._client.predict = mock.MagicMock(side_effect=RuntimeError("Space connection timeout"))

    result = provider.infer_audio_window_sync(WINDOW)

    assert result.success is False
    assert result.spoof_probability is None  # MUST be None, NEVER 0.5 or mock float
    assert result.error_code == "INFERENCE_UNAVAILABLE"
    assert "Space connection timeout" in (result.error_message or "")


# ---------------------------------------------------------------------------
# TEST 5: Production + missing HF credentials/config -> explicit failure.
# ---------------------------------------------------------------------------
def test_production_missing_hf_config_fails_explicitly() -> None:
    env = {
        "ENVIRONMENT": "production",
        "VOICETRUST_DETECTOR_MODE": "zerogpu",
        "HF_ZERO_GPU_SPACE": "",  # Missing endpoint
    }
    with mock.patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="HF_ZERO_GPU_SPACE is not configured"):
            config.validate_detector_config(env)

        with pytest.raises(RuntimeError, match="HF_ZERO_GPU_SPACE is required"):
            provider_factory.get_inference_provider(env)

    # Provider constructor directly rejects empty space_url
    with pytest.raises(ValueError, match="HF_ZERO_GPU_SPACE configuration is required"):
        ZeroGPUInferenceProvider("")


# ---------------------------------------------------------------------------
# TEST 6: Real provider success -> real inference result passes through unchanged.
# ---------------------------------------------------------------------------
def test_real_provider_success_passthrough() -> None:
    with mock.patch("app.services.zerogpu_provider.Client"):
        provider = ZeroGPUInferenceProvider("https://huggingface.co/spaces/test/space")

    payload = {
        "status": "ok",
        "spoof_probability": 0.88,
        "speaker_embedding": [0.1, 0.2, 0.3],
        "inference_time_ms": 42.0,
        "model_version_antispoof": "facebook/wav2vec2-xls-r-300m",
        "model_version_speaker": "speechbrain/spkrec-ecapa-voxceleb",
        "sample_rate": 16000,
        "duration_ms": 4000.0,
    }
    provider._client = mock.MagicMock()
    provider._client.predict = mock.MagicMock(return_value=payload)

    result = provider.infer_audio_window_sync(WINDOW)

    assert result.success is True
    assert result.spoof_probability == pytest.approx(0.88)
    assert result.model_version_antispoof == "facebook/wav2vec2-xls-r-300m"
    assert result.provider == "zerogpu"


# ---------------------------------------------------------------------------
# TEST 7: No code path silently converts an inference exception into spoof_probability = 0.5.
# ---------------------------------------------------------------------------
def test_no_silent_fallback_to_spoof_0_5_on_exception() -> None:
    # 1. Test parallel_inference.py under failure
    def failing_anti_spoof(w):
        raise RuntimeError("GPU OOM / Transport failure")

    acoustic_res, _, _, degraded = asyncio.run(
        run_window_inference(
            WINDOW,
            run_anti_spoof=failing_anti_spoof,
            run_asr=None,
            run_speaker=None,
        )
    )

    assert acoustic_res["acoustic_score"] is None  # NEVER 0.5
    assert acoustic_res["success"] is False
    assert acoustic_res["error_code"] == "INFERENCE_UNAVAILABLE"
    assert "anti_spoof" in degraded

    # 2. Test risk_engine.py fusion handling when acoustic_score is None
    fusion_result = compute_risk(
        acoustic_score=acoustic_res["acoustic_score"],  # None
        intent_score=0.1,
        speaker_similarity=0.9,
        degraded=degraded,
    )

    assert fusion_result["acoustic_score"] is None
    assert fusion_result["inference_available"] is False
    assert fusion_result["detector_status"] == "unavailable"
    assert fusion_result["error_code"] == "INFERENCE_UNAVAILABLE"
