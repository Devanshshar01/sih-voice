"""Unit tests for the inference provider layer (no GPU required).

Covers: provider interface/contract, factory selection, local provider result
and failure mapping (never a fake spoof_probability), ZeroGPU provider result
and structured-error mapping, and provider switching -- all with mocked
backends so ordinary CI never touches a real GPU or the HF Space.
"""
from __future__ import annotations

import asyncio
import os
from unittest import mock

import numpy as np
import pytest

from app.services import provider_factory
from app.services.inference_provider import (
    InferenceProvider,
    InferenceResult,
    MockInferenceProvider,
)
from app.services.local_provider import LocalInferenceProvider
from app.services.zerogpu_provider import ZeroGPUInferenceProvider

WINDOW = np.zeros(64000, dtype=np.float32)  # 4 s @ 16 kHz contract


# ---------------------------------------------------------------------------
# 1. Provider interface / result schema
# ---------------------------------------------------------------------------
def test_inference_result_success_schema() -> None:
    r = InferenceResult(
        spoof_probability=0.42,
        speaker_embedding=[0.1, 0.2],
        inference_time_ms=12.5,
        model_version_antispoof="m-a",
        model_version_speaker="m-s",
        sample_rate=16000,
        duration_ms=4000.0,
        provider="local",
    )
    assert r.success is True
    assert r.error_code is None
    assert 0.0 <= r.spoof_probability <= 1.0
    assert r.sample_rate == 16000
    assert r.provider == "local"


def test_inference_result_failure_has_no_fake_score() -> None:
    r = InferenceResult.failure("INFERENCE_UNAVAILABLE", "boom", provider="local")
    assert r.success is False
    assert r.spoof_probability is None  # NEVER 0.5
    assert r.speaker_embedding == []
    assert r.error_code == "INFERENCE_UNAVAILABLE"


def test_backward_compatible_positional_construction() -> None:
    r = InferenceResult(0.1, [1.0], 1.0, "a", "s", 16000, 4000.0)
    assert r.spoof_probability == 0.1 and r.success is True

# ---------------------------------------------------------------------------
# 2. Factory / provider selection
# ---------------------------------------------------------------------------
def test_default_provider_preserves_current_behaviour() -> None:
    # Default (no env) MUST keep today's production behaviour.
    with mock.patch.dict(os.environ, {}, clear=True):
        assert provider_factory.get_configured_provider_name({}) == "detector"
        p = provider_factory.get_inference_provider({})
        assert isinstance(p, MockInferenceProvider)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("zerogpu", "zerogpu"),
        ("local", "local"),
        ("kaggle", "local"),  # documented alias
        ("LOCAL", "local"),
        ("detector", "detector"),
    ],
)
def test_provider_switching(value: str, expected: str) -> None:
    assert provider_factory.get_configured_provider_name(
        {"INFERENCE_PROVIDER": value}
    ) == expected


def test_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        provider_factory.get_inference_provider({"INFERENCE_PROVIDER": "kaggle-prod"})


# ---------------------------------------------------------------------------
# 3. Local provider: result mapping + explicit failures (mocked pipeline)
# ---------------------------------------------------------------------------
def _ok_payload() -> dict:
    return {
        "status": "ok",
        "spoof_probability": 0.31,
        "speaker_embedding": [0.5, -0.5],
        "speaker_embedding_dim": 2,
        "inference_time_ms": 88.0,
        "model_version_antispoof": "satyavoice/xlsr-antipoof",
        "model_version_speaker": "speechbrain/spkrec-ecapa-voxceleb",
        "sample_rate": 16000,
        "duration_ms": 4000.0,
    }


def test_local_provider_success_mapping() -> None:
    p = LocalInferenceProvider(env={"DEVICE": "cpu"})
    fake = mock.MagicMock()
    fake.infer.return_value = _ok_payload()
    p._pipeline = fake
    r = p.infer_audio_window_sync(WINDOW)
    assert r.success and r.spoof_probability == pytest.approx(0.31)
    assert r.provider == "local"
    assert r.model_version_antispoof == "satyavoice/xlsr-antipoof"


def test_local_provider_structured_error_is_explicit_failure() -> None:
    p = LocalInferenceProvider(env={"DEVICE": "cpu"})
    fake = mock.MagicMock()
    fake.infer.return_value = {
        "status": "error",
        "error": {"type": "RuntimeError", "message": "cuda oom"},
        "model_version_antispoof": "a",
        "model_version_speaker": "s",
    }
    p._pipeline = fake
    r = p.infer_audio_window_sync(WINDOW)
    assert r.success is False
    assert r.spoof_probability is None  # never a fabricated 0.5
    assert r.error_code == "INFERENCE_UNAVAILABLE"
    assert "cuda oom" in (r.error_message or "")


def test_local_provider_invalid_input_is_not_a_score() -> None:
    p = LocalInferenceProvider(env={"DEVICE": "cpu"})
    fake = mock.MagicMock()
    fake.infer.side_effect = ValueError("No audio provided")
    p._pipeline = fake
    r = p.infer_audio_window_sync(WINDOW)
    assert r.success is False
    assert r.spoof_probability is None
    assert r.error_code == "INVALID_AUDIO_INPUT"


def test_local_provider_cuda_configured_but_unavailable_refuses_silent_fallback() -> None:
    import torch

    p = LocalInferenceProvider(env={"DEVICE": "cuda"})
    if torch.cuda.is_available():
        assert p._resolve_device() == "cuda"
    else:
        with pytest.raises(RuntimeError):
            p._resolve_device()


# ---------------------------------------------------------------------------
# 4. ZeroGPU provider: result + structured error mapping (mocked client)
# ---------------------------------------------------------------------------
def _zero_provider_with(predict_return, api_name_capture: dict) -> ZeroGPUInferenceProvider:
    with mock.patch("app.services.zerogpu_provider.Client", mock.MagicMock()):
        p = ZeroGPUInferenceProvider(
            "https://huggingface.co/spaces/devanshshar01/satyavoice-gpu",
            hf_token=None,
        )

    def _predict(audio, api_name=None):
        api_name_capture["api_name"] = api_name
        if isinstance(predict_return, Exception):
            raise predict_return
        return predict_return

    p.client.predict = _predict
    return p


def test_zerogpu_provider_success_mapping() -> None:
    captured: dict = {}
    p = _zero_provider_with(_ok_payload(), captured)
    r = asyncio.run(p.infer_audio_window(WINDOW))
    assert r.success and r.spoof_probability == pytest.approx(0.31)
    assert r.provider == "zerogpu"
    # Must target the real Space endpoint, not the removed /predict
    assert captured["api_name"] == "/infer"


def test_zerogpu_provider_structured_error_mapping() -> None:
    captured: dict = {}
    err_payload = {
        "status": "error",
        "error": {"type": "RuntimeError", "message": "GPU busy"},
    }
    p = _zero_provider_with(err_payload, captured)
    r = asyncio.run(p.infer_audio_window(WINDOW))
    assert r.success is False
    assert r.spoof_probability is None
    assert r.error_code == "INFERENCE_UNAVAILABLE"


def test_zerogpu_provider_transport_failure_raises_not_fabricates() -> None:
    captured: dict = {}
    p = _zero_provider_with(RuntimeError("connection refused"), captured)
    with pytest.raises(RuntimeError):
        asyncio.run(p.infer_audio_window(WINDOW))


# ---------------------------------------------------------------------------
# 5. Mock provider sanity (CI stand-in)
# ---------------------------------------------------------------------------
def test_mock_provider_deterministic_and_available() -> None:
    p = MockInferenceProvider()
    a = p.infer_audio_window_sync(WINDOW)
    b = p.infer_audio_window_sync(WINDOW)
    assert a.spoof_probability == b.spoof_probability
    assert p.is_available()

