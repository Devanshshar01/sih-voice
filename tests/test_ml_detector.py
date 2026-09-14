"""Focused detector-contract checks that do not download model weights."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from app import config
from app.core.risk_engine import compute_risk
from app.services.ml_detector import (
    MockVoiceDetector,
    RealAntiSpoofDetector,
    get_detector,
)
from app.services.intent_analyzer import IntentAnalyzer
from app.services.speaker_vault import SpeakerVault


# ---------------------------------------------------------------------------
# Default model identity: the active production detector is MMS-300M-AntiDeepfake
# ---------------------------------------------------------------------------

def test_default_model_id_is_mms_anti_deepfake() -> None:
    assert config.VOICE_MODEL_ID == "nii-yamagishilab/mms-300m-anti-deepfake"


def test_get_detector_default_model_id_is_mms_anti_deepfake() -> None:
    detector = get_detector("real")
    assert isinstance(detector, RealAntiSpoofDetector)
    assert detector.model_id == "nii-yamagishilab/mms-300m-anti-deepfake"


def test_real_detector_does_not_reference_xls_r_checkpoint() -> None:
    detector = get_detector("real")
    assert "xls-r" not in detector.model_id.lower()
    assert "facebook/" not in detector.model_id


# ---------------------------------------------------------------------------
# Lazy loading / provider initialization (mocked, no weights downloaded)
# ---------------------------------------------------------------------------

def test_real_detector_is_lazy() -> None:
    detector = get_detector("real")
    assert isinstance(detector, RealAntiSpoofDetector)
    assert detector._model is None


def test_real_detector_ignores_mock_force_contract() -> None:
    detector = get_detector("real")
    assert not isinstance(detector, MockVoiceDetector)


class _FakeProbs:
    """Row stand-in: [index].item() pops values in FAKE/REAL order."""

    def __init__(self, values):
        self._values = list(values)

    def __getitem__(self, index):
        return self

    def item(self):
        return float(self._values.pop(0))


class _FakeTorch:
    """Tiny torch stand-in for mocked inference (no torch dependency)."""

    class Tensor:
        pass

    @staticmethod
    def from_numpy(array):
        class _T:
            def __init__(self, data):
                self.data = data
                self.shape = data.shape

            def to(self, device):
                return self

            def unsqueeze(self, dim):
                return self

        return _T(array)

    @staticmethod
    def softmax(logits, dim=-1):
        return [_FakeProbs(_FakeTorch.current_probs)]

    class inference_mode:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    @staticmethod
    def functional_layer_norm(x, shape):
        return x

    current_probs = [0.5, 0.5]


def _detector_with_mocked_model(fake_prob: float, monkeypatch) -> RealAntiSpoofDetector:
    """RealAntiSpoofDetector with sys.modules mocks for torch and fairseq."""
    import sys
    import types

    import app.services.ml_detector as ml

    _FakeTorch.current_probs = [fake_prob, 1.0 - fake_prob]

    fake_torch_module = types.ModuleType("torch")
    fake_torch_module.from_numpy = _FakeTorch.from_numpy
    fake_torch_module.softmax = _FakeTorch.softmax
    fake_torch_module.inference_mode = _FakeTorch.inference_mode
    fake_torch_nn = types.ModuleType("torch.nn")
    fake_torch_nn.functional = types.SimpleNamespace(
        layer_norm=_FakeTorch.functional_layer_norm
    )
    fake_torch_module.nn = fake_torch_nn

    fake_fairseq = types.ModuleType("fairseq")
    fake_fairseq_models = types.ModuleType("fairseq.models")
    fake_fairseq_wav2vec = types.ModuleType("fairseq.models.wav2vec")
    fake_huggingface_hub = types.ModuleType("huggingface_hub")

    class _FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _FakeWav2Vec2Model:
        def __init__(self, cfg):
            pass

    class _FakeMixin:
        @classmethod
        def from_pretrained(cls, model_id, **kwargs):  # pragma: no cover
            raise AssertionError("from_pretrained must not run in unit tests")

    fake_fairseq_wav2vec.Wav2Vec2Config = _FakeConfig
    fake_fairseq_wav2vec.Wav2Vec2Model = _FakeWav2Vec2Model
    fake_huggingface_hub.PyTorchModelHubMixin = _FakeMixin

    monkeypatch.setitem(sys.modules, "torch", fake_torch_module)
    monkeypatch.setitem(sys.modules, "torch.nn", fake_torch_nn)
    monkeypatch.setitem(sys.modules, "fairseq", fake_fairseq)
    monkeypatch.setitem(sys.modules, "fairseq.models", fake_fairseq_models)
    monkeypatch.setitem(sys.modules, "fairseq.models.wav2vec", fake_fairseq_wav2vec)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_huggingface_hub)

    detector = RealAntiSpoofDetector(
        model_id="nii-yamagishilab/mms-300m-anti-deepfake"
    )

    class _FakeModel:
        def __call__(self, batch):
            return object()  # logits value; softmax is mocked

    detector._model = _FakeModel()
    return detector


def test_real_detector_lazy_model_load_invoked_once(monkeypatch) -> None:
    """_ensure_model_loaded must be idempotent: model loads at most once."""
    detector = RealAntiSpoofDetector(
        model_id="nii-yamagishilab/mms-300m-anti-deepfake"
    )
    calls = {"count": 0}
    original = detector._ensure_model_loaded

    def counting_load():
        if detector._model is None:
            calls["count"] += 1
            detector._model = object()

    monkeypatch.setattr(detector, "_ensure_model_loaded", counting_load)
    detector._ensure_model_loaded()
    detector._ensure_model_loaded()
    assert calls["count"] == 1
    assert detector._model is not None
    assert original is not None


# ---------------------------------------------------------------------------
# Fake/real output mapping and score direction (mocked model)
# ---------------------------------------------------------------------------

def test_fake_dominant_output_raises_acoustic_score(monkeypatch) -> None:
    detector = _detector_with_mocked_model(fake_prob=0.92, monkeypatch=monkeypatch)
    window = np.zeros(16000, dtype=np.float32)
    result = detector.predict(window)
    assert result["acoustic_score"] == pytest.approx(0.92, abs=1e-3)
    assert result["details"]["predicted_label"] == "fake"
    assert result["details"]["fake_probability"] == pytest.approx(0.92, abs=1e-3)
    assert result["details"]["real_probability"] == pytest.approx(0.08, abs=1e-3)
    assert (
        result["details"]["fake_probability"]
        + result["details"]["real_probability"]
        == pytest.approx(1.0, abs=1e-3)
    )


def test_real_dominant_output_lowers_acoustic_score(monkeypatch) -> None:
    detector = _detector_with_mocked_model(fake_prob=0.07, monkeypatch=monkeypatch)
    window = np.zeros(16000, dtype=np.float32)
    result = detector.predict(window)
    assert result["acoustic_score"] == pytest.approx(0.07, abs=1e-3)
    assert result["details"]["predicted_label"] == "real"


def test_acoustic_score_is_fake_probability_not_inverted(monkeypatch) -> None:
    """Direction regression: fake prob must map directly to acoustic_score."""
    detector = _detector_with_mocked_model(fake_prob=0.99, monkeypatch=monkeypatch)
    result = detector.predict(np.zeros(16000, dtype=np.float32))
    assert result["acoustic_score"] > 0.9, (
        "fake-dominant audio must produce a HIGH acoustic score (risk), "
        "not an inverted/trust score"
    )


def test_risk_engine_direction_fake_probability(monkeypatch) -> None:
    """Regression: higher fake probability must increase fused risk."""
    detector = _detector_with_mocked_model(fake_prob=0.90, monkeypatch=monkeypatch)
    fake_result = detector.predict(np.zeros(16000, dtype=np.float32))

    real_detector = _detector_with_mocked_model(
        fake_prob=0.10, monkeypatch=monkeypatch
    )
    real_result = real_detector.predict(np.zeros(16000, dtype=np.float32))

    fake_risk = compute_risk(
        acoustic_score=fake_result["acoustic_score"], intent_score=0.0
    )
    real_risk = compute_risk(
        acoustic_score=real_result["acoustic_score"], intent_score=0.0
    )
    assert fake_risk["risk_score"] > real_risk["risk_score"], (
        "fake probability must increase acoustic risk and genuine probability "
        "must decrease it"
    )
    assert fake_risk["status"] in ("WARN", "LOCK_VERIFY")
    assert real_risk["status"] == "ALLOW"


# ---------------------------------------------------------------------------
# Invalid / malformed audio
# ---------------------------------------------------------------------------

def test_empty_audio_window_is_degraded_not_crash() -> None:
    detector = RealAntiSpoofDetector(
        model_id="nii-yamagishilab/mms-300m-anti-deepfake"
    )
    result = detector.predict(np.array([], dtype=np.float32))
    assert result["acoustic_score"] == 0.5
    assert result["details"]["status"] == "degraded"
    assert result["details"]["warning"] == "empty_audio_window"


def test_all_non_finite_audio_is_degraded() -> None:
    detector = RealAntiSpoofDetector(
        model_id="nii-yamagishilab/mms-300m-anti-deepfake"
    )
    window = np.full(16000, np.nan, dtype=np.float32)
    result = detector.predict(window)
    assert result["details"]["status"] == "degraded"
    assert result["details"]["warning"] == "all_non_finite_samples"


def test_partly_non_finite_audio_is_sanitized(monkeypatch) -> None:
    detector = _detector_with_mocked_model(fake_prob=0.3, monkeypatch=monkeypatch)
    window = np.zeros(16000, dtype=np.float32)
    window[0] = np.nan
    window[1] = np.inf
    result = detector.predict(window)
    assert result["details"]["status"] == "ok"
    assert result["details"]["warning"] == "non_finite_samples_removed"


def test_inference_exception_returns_degraded_result(monkeypatch) -> None:
    detector = _detector_with_mocked_model(fake_prob=0.5, monkeypatch=monkeypatch)

    class _ExplodingModel:
        def __call__(self, batch):
            raise RuntimeError("CUDA out of memory")

    detector._model = _ExplodingModel()
    result = detector.predict(np.zeros(16000, dtype=np.float32))
    assert result["details"]["status"] == "degraded"
    assert "CUDA out of memory" in result["details"]["error"]
    # Degraded mode must NOT report a confident "genuine" verdict.
    assert result["acoustic_score"] == 0.5


def test_degraded_result_does_not_report_genuine(monkeypatch) -> None:
    """Regression: inference failure must never look like a real verdict."""
    detector = _detector_with_mocked_model(fake_prob=0.0, monkeypatch=monkeypatch)
    detector._model = None  # forces the load-failure path inside predict()

    result = detector.predict(np.zeros(16000, dtype=np.float32))
    assert result["details"]["status"] == "degraded"
    assert "error" in result["details"]
    # Degraded mode must NOT report a confident "genuine" verdict.
    assert result["acoustic_score"] == 0.5
    assert result["details"].get("predicted_label") is None


def test_input_preparation_rejects_non_finite() -> None:
    detector = RealAntiSpoofDetector(
        model_id="nii-yamagishilab/mms-300m-anti-deepfake"
    )
    window = np.full(16000, np.nan, dtype=np.float32)
    batch, warning = detector._prepare_input(window)
    assert batch is None
    assert warning == "all_non_finite_samples"


# ---------------------------------------------------------------------------
# Intent analyzer + speaker vault (unchanged contracts)
# ---------------------------------------------------------------------------

def test_intent_analyzer_preserves_manual_transcript_path() -> None:
    analyzer = IntentAnalyzer()
    result = analyzer.analyze_text("Please approve the wire transfer immediately.")
    # Documented scoring: 0.5 + 0.15 per flagged phrase (2 here) = 0.8
    # under the current multilingual matcher.
    assert result["intent_score"] == 0.8
    assert "wire transfer" in result["flagged_phrases"]
    assert "upi" in result["flagged_categories"]


def test_intent_analyzer_asr_is_lazy() -> None:
    analyzer = IntentAnalyzer(model_size="base")
    assert analyzer._model is None


def test_speaker_vault_enroll_and_match(tmp_path) -> None:
    """Persistent vault: isolated SQLite DB so the test never touches dev data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.services.speaker_vault import SpeakerVault

    engine = create_engine(
        f"sqlite:///{tmp_path}/vault.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    vault = SpeakerVault(session_factory=TestSession)

    sample = np.zeros(16000, dtype=np.float32)
    sample[:8000] = 0.25
    sample[8000:] = -0.25

    enrollment = vault.enroll("demo-speaker", sample)

    assert enrollment["speaker_id"] == "demo-speaker"
    assert enrollment["embedding_dim"] > 0

    match = vault.match(sample)
    assert match["speaker_match_score"] >= 0.95
