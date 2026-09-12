"""
Voice authenticity detectors.

BaseVoiceDetector defines a stable interface so nothing downstream (the risk
engine, the API) ever needs to change when the model changes:

    Phase 1 (hackathon-safe, zero heavy deps): MockVoiceDetector
    Phase 2 (real model):                      LightweightMLVoiceDetector

Both return the same shape: {"acoustic_score": float 0-1, "details": {...}}.
"""
from __future__ import annotations

import hashlib
import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Tuple

import numpy as np


class BaseVoiceDetector(ABC):
    @abstractmethod
    def predict(self, audio_window: np.ndarray) -> Dict[str, Any]:
        """Return {'acoustic_score': float in [0,1], 'details': {...}}."""
        raise NotImplementedError


class MockVoiceDetector(BaseVoiceDetector):
    """
    Deterministic, zero-latency detector for demos and for frontend/backend
    development before a trained model exists.

    - Produces a low, stable score for ordinary audio so genuine calls stay
      green throughout a normal conversation.
    - Accepts `force_score` so the judge-demo "backup audio injection"
      toggle (see stream.py) can deterministically trigger the cloned-voice
      scenario without depending on a live microphone.
    """

    def __init__(self, baseline: float = 0.12, jitter: float = 0.03):
        self.baseline = baseline
        self.jitter = jitter

    def predict(
        self, audio_window: np.ndarray, force_score: Optional[float] = None
    ) -> Dict[str, Any]:
        if force_score is not None:
            score = max(0.0, min(1.0, force_score))
        else:
            # Deterministic pseudo-variance derived from the audio content
            # itself, so the same window always produces the same score.
            digest = hashlib.sha1(audio_window.tobytes()).hexdigest()
            pseudo = (int(digest[:8], 16) % 1000) / 1000.0
            score = min(1.0, max(0.0, self.baseline + (pseudo - 0.5) * 2 * self.jitter))

        pitch_variance = float(np.std(audio_window)) if audio_window.size else 0.0
        return {
            "acoustic_score": score,
            "details": {
                "pitch_variance": round(pitch_variance, 4),
                "spectral_centroid": None,
                "mode": "mock",
            },
        }


class LightweightMLVoiceDetector(BaseVoiceDetector):
    """
    Phase 2 detector: classical acoustic features (pitch variance, MFCCs,
    spectral centroid, spectral roll-off, zero-crossing rate) feeding a
    trained scikit-learn classifier (Logistic Regression / Random Forest).

    Heavy dependencies (librosa, scikit-learn) are imported lazily so the API
    can boot and demo in mock mode even before a model has been trained --
    install them with: pip install librosa scikit-learn joblib
    """

    def __init__(self, model_path: Optional[str] = None, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._model = None
        self._model_path = model_path

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return
        import joblib  # lazy import

        if not self._model_path:
            raise RuntimeError(
                "LightweightMLVoiceDetector requires a trained model_path. "
                "Train one in Phase 3 and point VOICETRUST_MODEL_PATH at it."
            )
        self._model = joblib.load(self._model_path)

    @staticmethod
    def extract_features(audio_window: np.ndarray, sample_rate: int) -> Dict[str, float]:
        import librosa  # lazy import, heavy dependency

        y = audio_window.astype(np.float32)
        mfccs = librosa.feature.mfcc(y=y, sr=sample_rate, n_mfcc=13)
        spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sample_rate)
        spectral_rolloff = librosa.feature.spectral_rolloff(y=y, sr=sample_rate)
        zcr = librosa.feature.zero_crossing_rate(y)
        f0, _voiced_flag, _ = librosa.pyin(
            y, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"), sr=sample_rate
        )
        f0_voiced = f0[~np.isnan(f0)] if f0 is not None else np.array([])

        return {
            "mfcc_mean": float(np.mean(mfccs)),
            "spectral_centroid_mean": float(np.mean(spectral_centroid)),
            "spectral_rolloff_mean": float(np.mean(spectral_rolloff)),
            "zero_crossing_rate_mean": float(np.mean(zcr)),
            "pitch_mean": float(np.mean(f0_voiced)) if f0_voiced.size else 0.0,
            "pitch_variance": float(np.var(f0_voiced)) if f0_voiced.size else 0.0,
        }

    def predict(self, audio_window: np.ndarray) -> Dict[str, Any]:
        self._ensure_model_loaded()
        features = self.extract_features(audio_window, self.sample_rate)
        feature_vector = np.array([list(features.values())])
        proba = self._model.predict_proba(feature_vector)[0]
        # Assumes class index 1 == "synthetic/cloned"
        score = float(proba[1]) if len(proba) > 1 else float(proba[0])
        return {"acoustic_score": score, "details": {**features, "mode": "ml"}}


class RealAntiSpoofDetector(BaseVoiceDetector):
    """Lazy-loaded pretrained audio deepfake classifier.

    The default checkpoint is a Wav2Vec2 classifier published on Hugging Face.
    It is loaded only when real mode receives its first audio window so mock
    mode remains lightweight and deterministic.
    """

    def __init__(
        self,
        model_id: str,
        model_path: Optional[str] = None,
        device: str = "cpu",
        revision: str = "main",
        sample_rate: int = 16000,
    ):
        self.model_id = model_path or model_id
        self.device = device
        self.revision = revision
        self.sample_rate = sample_rate
        self._processor = None
        self._model = None

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return

        try:
            import torch
            from transformers import AutoModelForAudioClassification, Wav2Vec2FeatureExtractor
        except ImportError as exc:
            raise RuntimeError(
                "Real detector mode requires torch and transformers. "
                "Install requirements.txt before setting VOICETRUST_DETECTOR_MODE=real."
            ) from exc

        try:
            self._processor = Wav2Vec2FeatureExtractor.from_pretrained(
                self.model_id, revision=self.revision
            )
            self._model = AutoModelForAudioClassification.from_pretrained(
                self.model_id, revision=self.revision
            ).to(self.device)
            self._model.eval()
        except Exception as exc:
            raise RuntimeError(
                f"Could not load real detector checkpoint '{self.model_id}': {exc}"
            ) from exc

    def predict(self, audio_window: np.ndarray) -> Dict[str, Any]:
        self._ensure_model_loaded()
        import torch

        samples = np.asarray(audio_window, dtype=np.float32)
        if samples.size == 0:
            return {
                "acoustic_score": 0.5,
                "details": {
                    "mode": "real",
                    "model": self.model_id,
                    "warning": "empty_audio_window",
                },
            }

        inputs = self._processor(
            samples,
            sampling_rate=self.sample_rate,
            return_tensors="pt",
            padding=True,
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.inference_mode():
            logits = self._model(**inputs).logits
            probabilities = torch.softmax(logits, dim=-1)[0]

        labels = getattr(self._model.config, "id2label", {})
        synthetic_index = next(
            (index for index, label in labels.items() if "ai" in label.lower() or "fake" in label.lower() or "spoof" in label.lower()),
            0,
        )
        score = float(probabilities[int(synthetic_index)].item())
        label = labels.get(int(torch.argmax(probabilities).item()), "unknown")
        return {
            "acoustic_score": round(score, 4),
            "details": {
                "mode": "real",
                "model": self.model_id,
                "revision": self.revision,
                "predicted_label": label,
                "labels": labels,
                "sample_rate": self.sample_rate,
            },
        }


_DETECTOR_CACHE: Dict[Tuple[str, Optional[str], str, str, str], BaseVoiceDetector] = {}
_CACHE_LOCK = threading.Lock()


def get_detector(
    mode: str,
    model_path: Optional[str] = None,
    model_id: str = "Hemgg/Deepfake-audio-detection",
    device: str = "cpu",
    revision: str = "main",
) -> BaseVoiceDetector:
    """Process-wide detector factory (cached singleton per configuration).

    Each instance holds its own HF pipeline and GPU/CPU memory; per-call-site
    instantiation (stream, analyze, tasks) multiplied resident model copies.
    """
    key = (mode, model_path, model_id, device, revision)
    with _CACHE_LOCK:
        cached = _DETECTOR_CACHE.get(key)
        if cached is not None:
            return cached
        if mode == "real":
            detector: BaseVoiceDetector = RealAntiSpoofDetector(
                model_id=model_id,
                model_path=model_path,
                device=device,
                revision=revision,
            )
        elif mode == "ml":
            detector = LightweightMLVoiceDetector(model_path=model_path)
        else:
            detector = MockVoiceDetector()
        _DETECTOR_CACHE[key] = detector
        return detector
