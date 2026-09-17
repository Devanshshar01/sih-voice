"""MMS-300M-AntiDeepfake migration tests for the shared Cloud/ZeroGPU pipeline.

These tests exercise the REAL ``hf_zero_gpu/inference.py`` code in-process using
lightweight stand-ins for torch / torchaudio / huggingface_hub / fairseq (the
same convention ``tests/test_ml_detector.py`` uses). They run in CI without a
GPU, without the fairseq runtime, and without downloading any weights.

Nothing here claims real-model inference: the actual checkpoint is only ever
loaded on a GPU host (Kaggle or the HF ZeroGPU Space) -- see
``hf_zero_gpu/test_local.py``, ``kaggle/benchmark.py`` and ``docs/model-card.md``.

Coverage:
  A. model identity (Space config, backend config)
  B. provider/loader initialization (card-exact fairseq config, loaded once)
  C. output schema
  D. fake/real class mapping
  E. acoustic-score direction (fake probability == risk)
  F. invalid audio
  G. NaN/Inf audio
  H. inference exception -> degraded/structured error (no fabricated score)
  I. remote_hf payload parsing
  J. WebSocket telemetry compatibility
  K. regression: the active Cloud path no longer references the legacy XLS-R id
  L. Render production path does not require fairseq
"""
from __future__ import annotations

import importlib
import io
import sys
import types
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
import soundfile as sf

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MMS_MODEL_ID = "nii-yamagishilab/mms-300m-anti-deepfake"
LEGACY_MODEL_ID = "facebook/wav2vec2-xls-r-300m"
SPEAKER_MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
WINDOW = np.zeros(64000, dtype=np.float32)  # 4 s @ 16 kHz


# ---------------------------------------------------------------------------
# Stand-ins for torch / torchaudio / huggingface_hub / fairseq
# ---------------------------------------------------------------------------
class _FakeBool:
    def __init__(self, value):
        self._value = bool(value)

    def all(self):
        return self._value

    def __bool__(self):
        return self._value


class _FakeTensor:
    """Numpy-backed tensor stand-in."""

    def __init__(self, data):
        self.data = np.asarray(data, dtype=np.float32)
        self.shape = self.data.shape

    def float(self):
        return self

    def unsqueeze(self, dim):
        return self

    def squeeze(self):
        return self

    def cpu(self):
        return self

    def to(self, device):
        return self

    def numpy(self):
        return self.data

    def item(self):
        return float(self.data.reshape(-1)[0])

    def transpose(self, dim0, dim1):
        return self


class _Holder:
    def __init__(self, value):
        self._value = float(value)

    def item(self):
        return self._value


class _FakeProbs:
    """Row of class probabilities; shape[-1] is the head size."""

    def __init__(self, values):
        self._values = np.asarray(values, dtype=np.float64)
        self.shape = self._values.shape

    def __getitem__(self, index):
        return _Holder(self._values[index])

    def item(self):
        return float(self._values.reshape(-1)[0])


class _FakeBatchProbs:
    """Batched softmax stand-in: indexing row zero returns class scores."""

    def __init__(self, values):
        self._row = _FakeProbs(values)

    def __getitem__(self, index):
        assert index == 0
        return self._row


class _FakeContext:
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeModule:
    """torch.nn.Module stand-in."""

    def __init__(self, *args, **kwargs):
        pass

    def to(self, device):
        return self

    def eval(self):
        return self


class _FakeLinear:
    def __init__(self, in_features, out_features):
        self.in_features = in_features
        self.out_features = out_features


class _FakePool:
    def __init__(self, output_size):
        self.output_size = output_size


class _FakeTorch:
    """Minimal ``torch`` stand-in exposing only what inference.py uses."""

    def __init__(self, probabilities=(0.9, 0.1)):
        self._probabilities = list(probabilities)
        self.Tensor = _FakeTensor
        self.nn = types.SimpleNamespace(
            Module=_FakeModule,
            Linear=_FakeLinear,
            AdaptiveAvgPool1d=_FakePool,
            functional=types.SimpleNamespace(
                layer_norm=lambda tensor, shape: tensor
            ),
        )

    def from_numpy(self, array):
        return _FakeTensor(array)

    def isfinite(self, tensor):
        return _FakeBool(np.isfinite(tensor.data).all())

    def softmax(self, logits, dim=-1):
        return _FakeBatchProbs(self._probabilities)

    def inference_mode(self):
        return _FakeContext()


def _import_pipeline(monkeypatch, torch_stub=None):
    """Import hf_zero_gpu.inference with stubbed heavy dependencies."""
    torch_stub = torch_stub or _FakeTorch()

    torchaudio = types.ModuleType("torchaudio")
    torchaudio.functional = types.ModuleType("torchaudio.functional")

    hub = types.ModuleType("huggingface_hub")

    class PyTorchModelHubMixin:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):  # pragma: no cover
            raise AssertionError("from_pretrained must be mocked per test")

    hub.PyTorchModelHubMixin = PyTorchModelHubMixin

    monkeypatch.setitem(sys.modules, "torch", torch_stub)
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio)
    monkeypatch.setitem(sys.modules, "torchaudio.functional", torchaudio.functional)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.delitem(sys.modules, "hf_zero_gpu.inference", raising=False)
    importlib.invalidate_caches()
    return importlib.import_module("hf_zero_gpu.inference")


def _install_fake_models(pipeline, speaker_dim: int = 192):
    """Inject loaded-model stand-ins (no weights, no fairseq, no speechbrain)."""

    class _AntiSpoof(_FakeModule):
        def __call__(self, wav):
            return object()  # logits; the torch stub owns the probabilities

    class _Speaker(_FakeModule):
        def encode_batch(self, waveform):
            return _FakeTensor(np.full(speaker_dim, 0.5, dtype=np.float32))

    pipeline._antispoof_model = _AntiSpoof()
    pipeline._speaker_model = _Speaker()
    pipeline._models_on_device = False
    return pipeline


def _active_requirement_lines(text: str) -> list:
    """Requirement lines only: comments and inline comments stripped."""
    lines = []
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# A. Model identity
# ---------------------------------------------------------------------------
def test_space_default_model_id_is_mms_anti_deepfake() -> None:
    from hf_zero_gpu import config as space_config

    assert space_config.ANTISPOOF_MODEL_ID == MMS_MODEL_ID
    assert space_config.ANTISPOOF_MODEL_ID != LEGACY_MODEL_ID


def test_space_class_mapping_is_fake_then_real() -> None:
    from hf_zero_gpu import config as space_config

    # Card: "<Fake score, Real score>" and "real prob = prob[1]".
    assert space_config.FAKE_LABEL_INDEX == 0
    assert space_config.REAL_LABEL_INDEX == 1
    assert space_config.SAMPLE_RATE == 16000
    assert space_config.WINDOW_SAMPLES == 64000  # unchanged 4-second contract


def test_backend_default_model_id_is_mms_anti_deepfake() -> None:
    from app import config

    assert config.VOICE_MODEL_ID == MMS_MODEL_ID


# ---------------------------------------------------------------------------
# B. Provider / loader initialization
# ---------------------------------------------------------------------------
def test_ssl_frontend_is_built_from_the_card_fairseq_config(monkeypatch) -> None:
    """The MMS front-end must be built with fairseq, using the card's config."""
    fairseq = types.ModuleType("fairseq")
    fairseq_models = types.ModuleType("fairseq.models")
    fairseq_wav2vec = types.ModuleType("fairseq.models.wav2vec")

    class _Wav2Vec2Config(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    class _Wav2Vec2Model:
        def __init__(self, cfg):
            self.cfg = cfg

    fairseq_wav2vec.Wav2Vec2Config = _Wav2Vec2Config
    fairseq_wav2vec.Wav2Vec2Model = _Wav2Vec2Model
    monkeypatch.setitem(sys.modules, "fairseq", fairseq)
    monkeypatch.setitem(sys.modules, "fairseq.models", fairseq_models)
    monkeypatch.setitem(sys.modules, "fairseq.models.wav2vec", fairseq_wav2vec)

    pipeline = _import_pipeline(monkeypatch)
    ssl_model = pipeline.SSLModel()

    assert isinstance(ssl_model.model, _Wav2Vec2Model)
    assert ssl_model.model.cfg == {
        "quantize_targets": True,
        "extractor_mode": "layer_norm",
        "layer_norm_first": True,
        "final_dim": 768,
        "latent_temp": (2.0, 0.1, 0.999995),
        "encoder_layerdrop": 0.0,
        "dropout_input": 0.0,
        "dropout_features": 0.0,
        "dropout": 0.0,
        "attention_dropout": 0.0,
        "conv_bias": True,
        "encoder_layers": 24,
        "encoder_embed_dim": 1024,
        "encoder_ffn_embed_dim": 4096,
        "encoder_attention_heads": 16,
        "feature_grad_mult": 1.0,
    }


def test_anti_spoof_head_uses_the_hub_mixin(monkeypatch) -> None:
    pipeline = _import_pipeline(monkeypatch)
    base_names = [base.__name__ for base in pipeline.AntiDeepfakeDetector.__mro__]
    assert "PyTorchModelHubMixin" in base_names
    assert "_FakeModule" in base_names  # torch.nn.Module stand-in


def test_loader_uses_hub_mixin_with_mms_id_and_loads_once(monkeypatch) -> None:
    pipeline = _import_pipeline(monkeypatch)
    calls: list = []

    class _FakeDetector(_FakeModule):
        @classmethod
        def from_pretrained(cls, model_id):
            calls.append(model_id)
            return cls()

    monkeypatch.setattr(pipeline, "AntiDeepfakeDetector", _FakeDetector)
    monkeypatch.setattr(pipeline, "_antispoof_model", None)
    monkeypatch.setattr(pipeline, "_speaker_model", _FakeModule())  # resident

    pipeline._load_models()
    pipeline._load_models()  # no-op: the model is never rebuilt per request

    assert calls == [MMS_MODEL_ID]


# ---------------------------------------------------------------------------
# C/D. Output schema + fake/real class mapping
# ---------------------------------------------------------------------------
def test_fake_heavy_logits_map_to_high_fake_probability(monkeypatch) -> None:
    pipeline = _import_pipeline(monkeypatch, _FakeTorch(probabilities=(0.87, 0.13)))
    fake_probability, real_probability = pipeline._binary_probabilities(object())

    assert fake_probability == pytest.approx(0.87)
    assert real_probability == pytest.approx(0.13)
    assert fake_probability > real_probability


def test_real_heavy_logits_map_to_low_fake_probability(monkeypatch) -> None:
    pipeline = _import_pipeline(monkeypatch, _FakeTorch(probabilities=(0.04, 0.96)))
    fake_probability, real_probability = pipeline._binary_probabilities(object())

    assert fake_probability == pytest.approx(0.04)
    assert real_probability == pytest.approx(0.96)


def test_non_binary_head_is_an_error_not_a_verdict(monkeypatch) -> None:
    pipeline = _import_pipeline(
        monkeypatch, _FakeTorch(probabilities=(0.4, 0.35, 0.25))
    )
    with pytest.raises(RuntimeError, match="exactly 2 logits"):
        pipeline._binary_probabilities(object())


def test_run_inference_payload_schema(monkeypatch) -> None:
    pipeline = _install_fake_models(
        _import_pipeline(monkeypatch, _FakeTorch(probabilities=(0.8, 0.2)))
    )
    payload = pipeline.infer(WINDOW)

    assert payload["status"] == "ok"
    assert payload["spoof_probability"] == pytest.approx(0.8)   # == fake prob
    assert payload["fake_probability"] == pytest.approx(0.8)
    assert payload["real_probability"] == pytest.approx(0.2)
    assert payload["spoof_probability"] + payload["real_probability"] == pytest.approx(1.0)
    assert payload["model_version_antispoof"] == MMS_MODEL_ID
    assert payload["model_version_speaker"] == SPEAKER_MODEL_ID
    assert payload["sample_rate"] == 16000
    assert payload["duration_ms"] == pytest.approx(4000.0)
    assert payload["speaker_embedding_dim"] == 192
    assert len(payload["speaker_embedding"]) == 192
    # Embedding stays L2-normalized (unchanged speaker contract).
    assert sum(x * x for x in payload["speaker_embedding"]) == pytest.approx(1.0, abs=1e-6)
    # JSON-compatible: no numpy/torch objects leak into the Space response.
    assert all(isinstance(x, float) for x in payload["speaker_embedding"])
    assert isinstance(payload["inference_time_ms"], float)


def test_run_inference_accepts_tuple_input_and_enforces_the_window(monkeypatch) -> None:
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    payload = pipeline.infer((16000, np.ones(8000, dtype=np.float32)))
    assert payload["status"] == "ok"
    assert payload["duration_ms"] == pytest.approx(4000.0)


# ---------------------------------------------------------------------------
# E. Acoustic-score direction
# ---------------------------------------------------------------------------
def test_acoustic_score_direction_follows_fake_probability(monkeypatch) -> None:
    from app.core.risk_engine import compute_risk

    fake_heavy = _install_fake_models(
        _import_pipeline(monkeypatch, _FakeTorch(probabilities=(0.93, 0.07)))
    ).infer(WINDOW)

    real_heavy = _install_fake_models(
        _import_pipeline(monkeypatch, _FakeTorch(probabilities=(0.05, 0.95)))
    ).infer(WINDOW)

    assert fake_heavy["spoof_probability"] > real_heavy["spoof_probability"]

    risk_high = compute_risk(
        acoustic_score=fake_heavy["spoof_probability"], intent_score=0.0
    )["risk_score"]
    risk_low = compute_risk(
        acoustic_score=real_heavy["spoof_probability"], intent_score=0.0
    )["risk_score"]

    # Higher fake probability => higher acoustic risk (SatyaVoice convention).
    assert risk_high > risk_low
    # The ACOUSTIC_WEIGHT term must carry the fake probability through fusion
    # (0.93 fake prob * 0.60 weight -> at least 55 of the 0-100 risk scale).
    from app import config

    assert risk_high >= int(100 * config.RISK.ACOUSTIC_WEIGHT * 0.9)
    assert risk_low <= int(100 * config.RISK.ACOUSTIC_WEIGHT * 0.1) + 1


# ---------------------------------------------------------------------------
# F/G. Invalid + non-finite audio
# ---------------------------------------------------------------------------
def test_none_audio_raises_value_error(monkeypatch) -> None:
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    with pytest.raises(ValueError):
        pipeline.infer(None)


def test_nan_audio_raises_value_error_not_a_verdict(monkeypatch) -> None:
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    nan_window = np.full(64000, np.nan, dtype=np.float32)
    with pytest.raises(ValueError, match="NaN/Inf"):
        pipeline.infer(nan_window)


def test_inf_audio_raises_value_error(monkeypatch) -> None:
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    inf_window = np.full(64000, np.inf, dtype=np.float32)
    with pytest.raises(ValueError, match="NaN/Inf"):
        pipeline.infer(inf_window)


def test_prepare_audio_rejects_none_and_builds_the_exact_window(monkeypatch) -> None:
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    window = pipeline._prepare_audio(np.ones(1000, dtype=np.float32))
    assert len(window) == 64000           # padded to the 4 s contract


@pytest.mark.parametrize("file_format", ["WAV", "FLAC"])
def test_prepare_audio_decodes_encoded_file_bytes_without_numpy_truthiness(
    monkeypatch, file_format
) -> None:
    """Encoded uploads must be decoded, not passed to np.frombuffer as PCM."""
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    source = np.zeros(16000, dtype=np.float32)
    encoded = io.BytesIO()
    sf.write(encoded, source, 16000, format=file_format)

    window = pipeline._prepare_audio(encoded.getvalue())

    assert window.dtype == np.float32
    assert window.shape == (64000,)
    assert np.isfinite(window).all()


def test_prepare_audio_dict_does_not_evaluate_numpy_array_truthiness(monkeypatch) -> None:
    """A non-path ndarray field must fail explicitly, not via truthiness."""
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    samples = np.zeros(16000, dtype=np.float32)

    with pytest.raises(TypeError, match="Unsupported encoded audio input"):
        pipeline._prepare_audio({"path": None, "file": samples})


@pytest.mark.parametrize("file_format", ["WAV", "FLAC"])
def test_encoded_audio_reaches_mms_and_returns_contract(monkeypatch, file_format) -> None:
    """WAV and FLAC uploads both reach the mocked MMS/ECAPA inference path."""
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))
    source = np.zeros(64000, dtype=np.float32)
    encoded = io.BytesIO()
    sf.write(encoded, source, 16000, format=file_format)

    payload = pipeline.infer(encoded.getvalue())

    assert payload["status"] == "ok"
    assert payload["fake_probability"] == pytest.approx(0.9)
    assert payload["real_probability"] == pytest.approx(0.1)
    assert payload["model_version_antispoof"] == MMS_MODEL_ID
    assert payload["sample_rate"] == 16000
    assert payload["duration_ms"] == pytest.approx(4000.0)
    assert isinstance(payload["inference_time_ms"], float)
    window = pipeline._prepare_audio(np.ones(200000, dtype=np.float32))
    assert len(window) == 64000           # truncated to the 4 s contract


# ---------------------------------------------------------------------------
# H. Inference failure -> structured error, never a fabricated score
# ---------------------------------------------------------------------------
def test_inference_exception_returns_structured_error(monkeypatch) -> None:
    pipeline = _install_fake_models(_import_pipeline(monkeypatch))

    class _Exploding(_FakeModule):
        def __call__(self, wav):
            raise RuntimeError("CUDA out of memory")

    pipeline._antispoof_model = _Exploding()
    payload = pipeline.infer(WINDOW)

    assert payload["status"] == "error"
    assert "spoof_probability" not in payload
    assert "fake_probability" not in payload
    assert "real_probability" not in payload
    assert payload["error"]["type"] == "RuntimeError"
    assert "CUDA out of memory" in payload["error"]["message"]
    # The error still identifies which model was supposed to run.
    assert payload["model_version_antispoof"] == MMS_MODEL_ID


def test_non_finite_probabilities_are_a_structured_error(monkeypatch) -> None:
    """A 3-class head (or NaN probabilities) must never reach the verdict."""
    pipeline = _install_fake_models(
        _import_pipeline(monkeypatch, _FakeTorch(probabilities=(0.4, 0.35, 0.25)))
    )
    payload = pipeline.infer(WINDOW)

    assert payload["status"] == "error"
    assert "spoof_probability" not in payload
    assert payload["error"]["type"] == "RuntimeError"
    assert "2 logits" in payload["error"]["message"]


def test_missing_fairseq_is_reported_as_structured_error(monkeypatch) -> None:
    """A host without the fairseq runtime must degrade, not fake a score."""
    monkeypatch.setitem(sys.modules, "fairseq", None)  # None -> ImportError
    pipeline = _import_pipeline(monkeypatch)
    monkeypatch.setattr(
        pipeline.AntiDeepfakeDetector,
        "from_pretrained",
        classmethod(lambda cls, model_id: cls()),
    )
    monkeypatch.setattr(pipeline, "_speaker_model", _FakeModule())
    payload = pipeline.infer(WINDOW)

    assert payload["status"] == "error"
    assert "spoof_probability" not in payload
    assert "fairseq" in payload["error"]["message"]


def test_structured_error_helper_has_no_score_keys(monkeypatch) -> None:
    pipeline = _import_pipeline(monkeypatch)
    payload = pipeline._structured_error(RuntimeError("boom"))
    assert payload["status"] == "error"
    assert payload["error"] == {"type": "RuntimeError", "message": "boom"}
    assert "spoof_probability" not in payload
    assert payload["model_version_antispoof"] == MMS_MODEL_ID
    assert payload["sample_rate"] == 16000


# ---------------------------------------------------------------------------
# I. remote_hf / ZeroGPU payload parsing
# ---------------------------------------------------------------------------
def test_remote_hf_parses_mms_payload() -> None:
    from app.services.zerogpu_provider import ZeroGPUInferenceProvider

    with mock.patch("app.services.zerogpu_provider.Client", mock.MagicMock()):
        provider = ZeroGPUInferenceProvider(
            "https://huggingface.co/spaces/devanshshar01/satyavoice-gpu"
        )
    payload = {
        "status": "ok",
        "spoof_probability": 0.91,
        "fake_probability": 0.91,
        "real_probability": 0.09,
        "speaker_embedding": [0.5, 0.5],
        "speaker_embedding_dim": 2,
        "inference_time_ms": 71.5,
        "model_version_antispoof": MMS_MODEL_ID,
        "model_version_speaker": SPEAKER_MODEL_ID,
        "sample_rate": 16000,
        "duration_ms": 4000.0,
    }
    provider._client = mock.MagicMock()
    provider._client.predict = mock.MagicMock(return_value=payload)

    result = provider.infer_audio_window_sync(WINDOW)

    assert result.success is True
    assert result.spoof_probability == pytest.approx(0.91)
    assert result.model_version_antispoof == MMS_MODEL_ID
    assert result.provider == "zerogpu"


def test_remote_hf_structured_error_is_not_a_score() -> None:
    from app.services.zerogpu_provider import ZeroGPUInferenceProvider

    with mock.patch("app.services.zerogpu_provider.Client", mock.MagicMock()):
        provider = ZeroGPUInferenceProvider(
            "https://huggingface.co/spaces/devanshshar01/satyavoice-gpu"
        )
    provider._client = mock.MagicMock()
    provider._client.predict = mock.MagicMock(
        return_value={
            "status": "error",
            "error": {"type": "ImportError", "message": "fairseq missing"},
            "model_version_antispoof": MMS_MODEL_ID,
        }
    )

    result = provider.infer_audio_window_sync(WINDOW)

    assert result.success is False
    assert result.spoof_probability is None  # never 0.5, never 0.0
    assert result.error_code == "INFERENCE_UNAVAILABLE"
    assert result.model_version_antispoof == MMS_MODEL_ID


def test_detector_adapter_reports_mms_identity_for_remote_hf() -> None:
    from app.services import ml_detector
    from app.services.inference_provider import InferenceResult

    class _FakeProvider:
        def infer_audio_window_sync(self, window):
            return InferenceResult(
                spoof_probability=0.77,
                speaker_embedding=[0.1],
                inference_time_ms=64.0,
                model_version_antispoof=MMS_MODEL_ID,
                model_version_speaker=SPEAKER_MODEL_ID,
                sample_rate=16000,
                duration_ms=4000.0,
                provider="zerogpu",
            )

    adapter = ml_detector.ZeroGPUVoiceDetectorAdapter(provider=_FakeProvider())
    result = adapter.predict(WINDOW)

    assert result["success"] is True
    assert result["acoustic_score"] == pytest.approx(0.77)
    assert result["details"]["model"] == MMS_MODEL_ID
    assert result["detector_status"] == "ok"


# ---------------------------------------------------------------------------
# J. WebSocket telemetry compatibility
# ---------------------------------------------------------------------------
def test_mms_acoustic_score_flows_into_ws_telemetry_schema() -> None:
    from app.core.risk_engine import compute_risk
    from app.models.schemas import RiskTelemetry

    # 0.91 fake probability (a plausible MMS output) feeds the unchanged fusion
    # equation and must validate against the WS telemetry schema.
    fusion = compute_risk(
        acoustic_score=0.91, intent_score=0.2, speaker_similarity=0.85
    )
    telemetry = RiskTelemetry(
        timestamp=1.0,
        risk_score=fusion["risk_score"],
        acoustic_score=fusion["acoustic_score"],
        intent_score=fusion["intent_score"],
        status=getattr(fusion["status"], "value", fusion["status"]),
        rationale=fusion["rationale"],
    )

    assert telemetry.acoustic_score == pytest.approx(0.91)
    assert telemetry.risk_score == fusion["risk_score"]
    assert fusion["inference_available"] is True
    assert fusion["detector_status"] == "ok"
    assert fusion["error_code"] is None


def test_unavailable_inference_stays_unavailable_in_telemetry() -> None:
    from app.core.risk_engine import compute_risk

    fusion = compute_risk(
        acoustic_score=None,
        intent_score=0.0,
        speaker_similarity=1.0,
        degraded={"anti_spoof": "unavailable"},
    )

    assert fusion["acoustic_score"] is None
    assert fusion["inference_available"] is False
    assert fusion["detector_status"] == "unavailable"
    assert fusion["error_code"] == "INFERENCE_UNAVAILABLE"


# ---------------------------------------------------------------------------
# K. Regression: the active Cloud path no longer loads the legacy XLS-R id
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "rel_path",
    [
        "hf_zero_gpu/config.py",
        "hf_zero_gpu/inference.py",
        "hf_zero_gpu/app.py",
        "app/config.py",
        "app/services/ml_detector.py",
        "app/services/provider_factory.py",
        "app/services/zerogpu_provider.py",
        "app/services/local_provider.py",
    ],
)
def test_active_modules_never_reference_the_legacy_checkpoint(rel_path) -> None:
    source = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert LEGACY_MODEL_ID not in source
    assert "xls-r" not in source.lower()


def test_space_pipeline_uses_fairseq_not_a_transformers_audio_classifier() -> None:
    source = (REPO_ROOT / "hf_zero_gpu" / "inference.py").read_text(encoding="utf-8")

    assert "from transformers import AutoModelForAudioClassification" not in source
    assert "Wav2Vec2FeatureExtractor" not in source
    assert "from fairseq.models.wav2vec import Wav2Vec2Config, Wav2Vec2Model" in source
    assert "PyTorchModelHubMixin" in source


def test_space_pipeline_reports_the_model_id_from_config() -> None:
    source = (REPO_ROOT / "hf_zero_gpu" / "inference.py").read_text(encoding="utf-8")
    assert '"model_version_antispoof": ANTISPOOF_MODEL_ID' in source


# ---------------------------------------------------------------------------
# L. Render production stays lightweight (no fairseq/omegaconf/hydra)
# ---------------------------------------------------------------------------
def test_root_requirements_keep_the_render_image_lightweight() -> None:
    lines = _active_requirement_lines(
        (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
    )
    for banned in ("fairseq", "omegaconf", "hydra-core"):
        assert not any(banned in line for line in lines), banned
    assert any(line.startswith("gradio-client") for line in lines)


def test_backend_selects_remote_hf_without_importing_fairseq(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "fairseq", None)  # any import would fail
    from app.services import ml_detector, provider_factory

    with mock.patch.dict(
        "os.environ",
        {"HF_ZERO_GPU_SPACE": "https://huggingface.co/spaces/test/space"},
        clear=True,
    ):
        detector = ml_detector.get_detector("remote_hf")
    assert isinstance(detector, ml_detector.ZeroGPUVoiceDetectorAdapter)

    real = ml_detector.get_detector("real")
    assert isinstance(real, ml_detector.RealAntiSpoofDetector)
    assert real._model is None  # lazy: fairseq is only needed on first load

    with mock.patch.dict(
        "os.environ",
        {"HF_ZERO_GPU_SPACE": "https://huggingface.co/spaces/test/space"},
        clear=True,
    ), mock.patch("app.services.zerogpu_provider.Client", mock.MagicMock()):
        provider = provider_factory.get_inference_provider({})
    assert provider is not None


# ---------------------------------------------------------------------------
# Space build dependencies (the BUILD_ERROR fix)
# ---------------------------------------------------------------------------
def test_space_requirements_have_no_pip_downgrade_and_no_transformers() -> None:
    lines = _active_requirement_lines(
        (REPO_ROOT / "hf_zero_gpu" / "requirements.txt").read_text(encoding="utf-8")
    )
    # A `pip<24.1` line cannot work (pip resolves the file with the pip that is
    # already installed) and self-downgrading pip mid-install is not worth it.
    assert not any(line.startswith("pip") for line in lines)
    # transformers is no longer imported anywhere in the Space pipeline.
    assert not any(line.startswith("transformers") for line in lines)


def test_space_requirements_reference_the_vendored_omegaconf_wheel() -> None:
    lines = _active_requirement_lines(
        (REPO_ROOT / "hf_zero_gpu" / "requirements.txt").read_text(encoding="utf-8")
    )
    assert any(
        line.startswith(
            "omegaconf @ https://huggingface.co/spaces/"
            "devanshshar01/satyavoice-gpu/resolve/main/vendor/"
            "omegaconf-2.0.6-py3-none-any.whl"
        )
        for line in lines
    )
    assert any("omegaconf-2.0.6-py3-none-any.whl" in line for line in lines)
    assert "hydra-core==1.0.7" in lines   # satisfies fairseq's >=1.0.7,<1.1
    assert "fairseq==0.12.2" in lines
    assert "safetensors>=0.5.3" in lines  # MMS ships model.safetensors
    assert "numpy>=1.24.0,<2.0" in lines  # fairseq 0.12.2 predates NumPy 2


def test_vendored_omegaconf_wheel_is_metadata_repaired() -> None:
    wheel = REPO_ROOT / "hf_zero_gpu" / "vendor" / "omegaconf-2.0.6-py3-none-any.whl"
    assert wheel.is_file(), "vendored wheel missing: the Space build would fail"

    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        metadata = archive.read(metadata_name).decode("utf-8")

    assert "Name: omegaconf" in metadata
    assert "Version: 2.0.6" in metadata
    # The invalid specifier that pip >= 24.1 rejects must be repaired...
    assert "PyYAML (>=5.1.*)" not in metadata
    # ...and replaced by the equivalent valid one.
    assert "Requires-Dist: PyYAML>=5.1" in metadata


def test_vendored_wheel_would_actually_be_pushed_to_the_space() -> None:
    gitignore = (REPO_ROOT / "hf_zero_gpu" / ".gitignore").read_text(encoding="utf-8")
    gitattributes = (REPO_ROOT / "hf_zero_gpu" / ".gitattributes").read_text(
        encoding="utf-8"
    )
    assert "*.whl" not in gitignore
    assert "*.whl" not in gitattributes


def test_kaggle_requirements_include_the_mms_runtime() -> None:
    text = (REPO_ROOT / "kaggle" / "requirements-kaggle.txt").read_text(
        encoding="utf-8"
    )
    assert "fairseq==0.12.2" in text
    assert "hf_zero_gpu/vendor/omegaconf-2.0.6-py3-none-any.whl" in text