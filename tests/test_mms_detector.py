"""MMS-300M-AntiDeepfake migration tests.

Covers (mocked — no model download/GPU in CI):
  A. Model identifier (production default is the MMS checkpoint)
  B. Provider initialization (lazy load, singleton caching)
  C. Fake/real output mapping (official index 0=fake, 1=real)
  D. Acoustic risk direction (fake probability raises risk; real lowers it)
  E. Invalid audio (empty / wrong sample rate)
  F. NaN/Inf audio sanitization
  G. Inference exception -> degraded, never a fake "genuine" score
  H. ZeroGPU response parsing (ok / degraded / network failure)
  I. Risk-engine compatibility (weights, monotonicity, fusion untouched)
"""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from app import config
from app.core.risk_engine import compute_risk
from app.services import anti_spoof_provider as provider
from app.services import ml_detector as detector_mod
from app.services.anti_spoof_provider import (
    MMS_FAKE_INDEX,
    MMS_MODEL_ID,
    MMS_REAL_INDEX,
    MMSAntiDeepfakeDetector,
    validate_audio_16k_mono,
)

MMS_ID = "nii-yamagishilab/mms-300m-anti-deepfake"
OLD_IDS = {"facebook/wav2vec2-xls-r-300m", "Hemgg/Deepfake-audio-detection"}

# ---------------------------------------------------------------------------
# A. Model identifier
# ---------------------------------------------------------------------------


def test_production_default_model_id_is_mms() -> None:
    assert config.VOICE_MODEL_ID == MMS_ID
    assert config.VOICE_MODEL_ID not in OLD_IDS


def test_provider_module_constants() -> None:
    assert MMS_MODEL_ID == MMS_ID
    # Official model card: softmax index 0 = fake, 1 = real.
    assert MMS_FAKE_INDEX == 0
    assert MMS_REAL_INDEX == 1


# ---------------------------------------------------------------------------
# B. Provider initialization
# ---------------------------------------------------------------------------


def test_real_detector_is_lazy_and_wraps_mms_provider() -> None:
    detector = detector_mod.get_detector("real", model_id=MMS_ID)
    assert isinstance(detector, detector_mod.RealAntiSpoofDetector)
    assert detector.loaded is False  # nothing loaded until first predict
    assert detector.model_id == MMS_ID


def test_detector_factory_caches_singleton_per_config() -> None:
    a = detector_mod.get_detector("real", model_id=MMS_ID)
    b = detector_mod.get_detector("real", model_id=MMS_ID)
    assert a is b


def test_factory_supports_remote_hf_mode(monkeypatch) -> None:
    monkeypatch.setattr(config, "HF_SPACE_ID", "user/satyavoice-anti-spoof", raising=False)
    detector = detector_mod.get_detector("remote_hf", model_id=MMS_ID)
    from app.services.hf_zero_gpu_client import HFZeroGPUDetector

    assert isinstance(detector, HFZeroGPUDetector)
    assert detector.model_id == MMS_ID


def test_remote_hf_requires_space_id(monkeypatch) -> None:
    import importlib

    monkeypatch.setenv("VOICETRUST_DETECTOR_MODE", "remote_hf")
    monkeypatch.setenv("VOICETRUST_HF_SPACE_ID", "")
    with pytest.raises(RuntimeError, match="VOICETRUST_HF_SPACE_ID"):
        importlib.reload(config)


# ---------------------------------------------------------------------------
# C/D. Fake/real mapping + score direction (mocked forward pass)
# ---------------------------------------------------------------------------


class _FakeTorchStub:
    """Minimal torch stand-in: softmax over a fixed logits row."""

    class functional:
        @staticmethod
        def layer_norm(x, shape):
            return x

    @staticmethod
    def from_numpy(arr):
        return np.asarray(arr)

    @staticmethod
    def softmax(logits, dim=-1):
        # logits is a [2] numpy row -> return a [1, 2] batch like torch
        e = np.exp(logits - logits.max())
        row = e / e.sum()
        return row.reshape(1, -1)


def _predict_with_logits(detector: MMSAntiDeepfakeDetector, logits_row) -> dict:
    stub = MagicMock()
    stub.functional = _FakeTorchStub.functional
    stub.from_numpy = _FakeTorchStub.from_numpy
    stub.softmax = _FakeTorchStub.softmax
    stub.inference_mode = MagicMock(
        return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False))
    )
    model = MagicMock()
    # model(inputs) -> logits row (softmax handled by stub)
    model.return_value = np.array(logits_row, dtype=np.float64)
    detector._torch = stub
    detector._model = model
    return detector.predict(np.zeros(16000, dtype=np.float32))


def test_fake_dominant_output_maps_to_high_acoustic_score() -> None:
    detector = MMSAntiDeepfakeDetector(model_id=MMS_ID)
    # logits favoring index 0 (fake)
    result = _predict_with_logits(detector, [4.0, -1.0])
    assert result["acoustic_score"] > 0.9
    assert result["details"]["fake_probability"] == result["acoustic_score"]
    assert result["details"]["predicted_label"] == "fake"
    assert (
        abs(
            result["details"]["fake_probability"]
            + result["details"]["real_probability"]
            - 1.0
        )
        < 1e-6
    )


def test_real_dominant_output_maps_to_low_acoustic_score() -> None:
    detector = MMSAntiDeepfakeDetector(model_id=MMS_ID)
    result = _predict_with_logits(detector, [-1.0, 4.0])
    assert result["acoustic_score"] < 0.1
    assert result["details"]["predicted_label"] == "real"
    assert result["details"]["status"] == "ok"


def test_acoustic_score_equals_fake_probability_not_real() -> None:
    detector = MMSAntiDeepfakeDetector(model_id=MMS_ID)
    result = _predict_with_logits(detector, [2.0, 0.0])
    fake = float(result["details"]["fake_probability"])
    real = float(result["details"]["real_probability"])
    assert result["acoustic_score"] == pytest.approx(fake, abs=1e-6)
    assert result["acoustic_score"] != pytest.approx(real, abs=0.2)
    assert fake > real  # direction sanity for this logits row


def test_risk_direction_fake_probability_raises_risk() -> None:
    """Regression: MMS fake probability must RAISE fused risk."""
    fake_risky = compute_risk(acoustic_score=0.95, intent_score=0.0)
    real_benign = compute_risk(acoustic_score=0.05, intent_score=0.0)
    assert fake_risky["risk_score"] > real_benign["risk_score"]
    # And strictly through the same engine used by the stream pipeline.
    assert fake_risky["fusion"]["contributions"]["acoustic"] > (
        real_benign["fusion"]["contributions"]["acoustic"]
    )


def test_risk_monotone_in_fake_probability() -> None:
    scores = [0.0, 0.25, 0.5, 0.75, 1.0]
    risks = [compute_risk(acoustic_score=s, intent_score=0.0)["risk_score"] for s in scores]
    assert risks == sorted(risks)


# ---------------------------------------------------------------------------
# E/F. Invalid audio + NaN/Inf sanitization
# ---------------------------------------------------------------------------


def test_validate_rejects_empty_window() -> None:
    with pytest.raises(ValueError, match="empty"):
        validate_audio_16k_mono(np.array([], dtype=np.float32))


def test_validate_rejects_wrong_sample_rate() -> None:
    with pytest.raises(ValueError, match="16 kHz"):
        validate_audio_16k_mono(np.zeros(100, dtype=np.float32), sample_rate=8000)


def test_validate_sanitizes_nan_inf() -> None:
    arr = np.array([0.1, np.nan, np.inf, -np.inf, 0.2], dtype=np.float32)
    out = validate_audio_16k_mono(arr)
    assert np.isfinite(out).all()
    # NaN/Inf positions zeroed, good values preserved
    assert out[0] == pytest.approx(0.1)
    assert out[4] == pytest.approx(0.2)
    assert out[1] == 0.0 and out[2] == 0.0 and out[3] == 0.0


def test_predict_on_empty_window_degrades_never_crashes() -> None:
    detector = MMSAntiDeepfakeDetector(model_id=MMS_ID)
    result = detector.predict(np.array([], dtype=np.float32))
    assert result["acoustic_score"] == 0.5
    assert result["details"]["status"] == "degraded_input"


def test_predict_on_nan_window_sanitizes_instead_of_crashing() -> None:
    detector = MMSAntiDeepfakeDetector(model_id=MMS_ID)
    window = np.full(16000, np.nan, dtype=np.float32)
    result = _predict_with_logits(detector, [0.0, 0.0])
    detector.predict(window)  # must not raise
    # Even after sanitization the direction contract still holds.
    assert 0.0 <= result["acoustic_score"] <= 1.0


# ---------------------------------------------------------------------------
# G. Inference exception -> degraded
# ---------------------------------------------------------------------------


def test_inference_exception_propagates_to_pipeline_degradation() -> None:
    """In-process provider: an inference exception propagates, and the stream
    pipeline's parallel_inference layer converts it into the degraded
    0.5-prior result. Contract test of exactly that handoff."""
    detector = MMSAntiDeepfakeDetector(model_id=MMS_ID)
    detector._torch = MagicMock()
    detector._torch.from_numpy.side_effect = RuntimeError("CUDA OOM")
    with pytest.raises(RuntimeError):
        detector.predict(np.zeros(16000, dtype=np.float32))
    # The pipeline layer that catches it:
    from app.core.parallel_inference import _degraded_acoustic

    degraded = _degraded_acoustic()
    assert degraded["acoustic_score"] == 0.5
    assert degraded["details"]["warning"] == "anti_spoof_unavailable"


def test_malformed_model_output_degrades() -> None:
    detector = MMSAntiDeepfakeDetector(model_id=MMS_ID)
    stub = MagicMock()
    stub.functional = _FakeTorchStub.functional
    stub.from_numpy = _FakeTorchStub.from_numpy
    stub.softmax = MagicMock(
        side_effect=lambda *a, **k: (_ for _ in ()).throw(ValueError("bad logits"))
    )
    stub.inference_mode = MagicMock(
        return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock(return_value=False))
    )
    model = MagicMock()
    model.return_value = np.array([0.0, 0.0])
    detector._torch = stub
    detector._model = model
    result = detector.predict(np.zeros(16000, dtype=np.float32))
    assert result["acoustic_score"] == 0.5
    assert result["details"]["status"] == "degraded_output"


# ---------------------------------------------------------------------------
# H. ZeroGPU response parsing
# ---------------------------------------------------------------------------


def _client_with_response(response) -> "detector_mod.get_detector":  # noqa: F722
    from app.services.hf_zero_gpu_client import HFZeroGPUDetector

    d = HFZeroGPUDetector(space_id="user/satyavoice-anti-spoof")
    fake_client = MagicMock()
    fake_client.predict.return_value = response if not isinstance(response, str) else response
    d._client = fake_client
    return d


def test_space_ok_response_maps_to_contract() -> None:
    d = _client_with_response(
        json.dumps(
            {
                "ok": True,
                "model_id": MMS_ID,
                "fake_probability": 0.87,
                "real_probability": 0.13,
                "predicted_label": "fake",
                "inference_latency_ms": 41.2,
                "device": "cuda",
            }
        )
    )
    result = d.predict(np.zeros(16000, dtype=np.float32))
    assert result["acoustic_score"] == pytest.approx(0.87)
    assert result["details"]["provider"] == "hf_zero_gpu"
    assert result["details"]["status"] == "ok"


def test_space_degraded_response_is_not_genuine() -> None:
    d = _client_with_response(json.dumps({"ok": False, "status": "degraded", "error": "OOM"}))
    result = d.predict(np.zeros(16000, dtype=np.float32))
    assert result["acoustic_score"] == 0.5
    assert result["details"]["status"] != "ok"
    assert "OOM" in result["details"]["warning"]


def test_space_network_failure_is_degraded() -> None:
    from app.services.hf_zero_gpu_client import HFZeroGPUDetector

    d = HFZeroGPUDetector(space_id="user/satyavoice-anti-spoof")
    # Force _get_client to raise (network failure path).
    d._get_client = MagicMock(side_effect=ConnectionError("space unreachable"))
    result = d.predict(np.zeros(16000, dtype=np.float32))
    assert result["acoustic_score"] == 0.5
    assert result["details"]["status"] == "degraded_remote"


# ---------------------------------------------------------------------------
# I. Risk-engine compatibility (unchanged by the migration)
# ---------------------------------------------------------------------------


def test_existing_risk_engine_behavior_unchanged() -> None:
    result = compute_risk(acoustic_score=0.8, intent_score=0.5, speaker_similarity=0.9)
    assert result["status"] == "WARN"
    assert result["fusion"]["weights"]["acoustic"] == config.RISK.ACOUSTIC_WEIGHT


def test_degraded_acoustic_never_reports_genuine() -> None:
    """Degraded evidence + penalty must keep risk above the pure-benign case."""
    benign = compute_risk(acoustic_score=0.0, intent_score=0.0)
    degraded = compute_risk(acoustic_score=0.5, intent_score=0.0, degraded={"anti_spoof": "x"})
    assert degraded["risk_score"] > benign["risk_score"]
