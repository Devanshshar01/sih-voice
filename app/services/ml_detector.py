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
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

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
                "Train one in Phase 3 and point SATYAVOICE_MODEL_PATH at it."
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


def get_detector(mode: str, model_path: Optional[str] = None) -> BaseVoiceDetector:
    if mode == "ml":
        return LightweightMLVoiceDetector(model_path=model_path)
    return MockVoiceDetector()
