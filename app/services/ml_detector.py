"""
Voice authenticity detectors.

BaseVoiceDetector defines a stable interface so nothing downstream (the risk
engine, the API) ever needs to change when the model changes:

    Phase 1 (hackathon-safe, zero heavy deps): MockVoiceDetector
    Phase 2 (real model):                      RealAntiSpoofDetector
    (legacy scikit-learn path kept for compatibility: LightweightMLVoiceDetector)

Both return the same shape: {"acoustic_score": float 0-1, "details": {...}}.

The real-mode detector is the pretrained
``nii-yamagishilab/mms-300m-anti-deepfake`` checkpoint (MMS-300M-AntiDeepfake,
NII/Yamagishi Lab, CC BY-NC-SA 4.0), used off-the-shelf as an acoustic speech
deepfake/spoof detector. SatyaVoice-specific fine-tuning is a separate future
task. acoustic_score is the FAKE probability: higher score = higher risk.
"""
from __future__ import annotations

import hashlib
import os
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
    """Lazy-loaded acoustic speech deepfake detector.

    The active production checkpoint is
    ``nii-yamagishilab/mms-300m-anti-deepfake`` (MMS-300M-AntiDeepfake,
    released by NII/Yamagishi Lab under CC BY-NC-SA 4.0). It is post-trained
    for deepfake speech detection; SatyaVoice has not fine-tuned it.

    Loading follows the official model card exactly: the checkpoint is a
    fairseq ``Wav2Vec2Model`` front-end plus a fully connected binary head,
    packaged with ``PyTorchModelHubMixin``. It is therefore NOT loadable via
    ``transformers.AutoModelForAudioClassification`` (its HF config declares
    ``Wav2Vec2ForPreTraining``).

    Output convention (verified from the official inference example):
        softmax(logits)[0] == fake probability, [1] == real probability.

    SatyaVoice acoustic risk convention: HIGHER acoustic_score means MORE
    synthetic (higher risk). We therefore map fake probability ->
    acoustic_score so that fake audio raises risk and genuine audio lowers
    it. The model is loaded lazily exactly once and reused for every window.
    """

    # Official checkpoint class ordering: index 0 = fake, index 1 = real.
    FAKE_INDEX = 0
    REAL_INDEX = 1

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
        self._model = None

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return

        try:
            import torch
            from fairseq.models.wav2vec import Wav2Vec2Config, Wav2Vec2Model
            from huggingface_hub import PyTorchModelHubMixin
        except ImportError as exc:
            raise RuntimeError(
                "Real detector mode requires torch, fairseq, and huggingface-hub "
                "(see the official nii-yamagishilab/mms-300m-anti-deepfake model "
                "card). Install hf_zero_gpu/requirements.txt, which pins the "
                "fairseq/hydra MMS runtime, before setting "
                "VOICETRUST_DETECTOR_MODE=real -- the production "
                "remote_hf/zerogpu path does not need it."
            ) from exc

        try:

            class _SSLModel(torch.nn.Module):
                """MMS-300M front-end (fairseq) as specified by the model card."""

                def __init__(self) -> None:
                    super().__init__()
                    cfg = Wav2Vec2Config(
                        quantize_targets=True,
                        extractor_mode="layer_norm",
                        layer_norm_first=True,
                        final_dim=768,
                        latent_temp=(2.0, 0.1, 0.999995),
                        encoder_layerdrop=0.0,
                        dropout_input=0.0,
                        dropout_features=0.0,
                        dropout=0.0,
                        attention_dropout=0.0,
                        conv_bias=True,
                        encoder_layers=24,
                        encoder_embed_dim=1024,
                        encoder_ffn_embed_dim=4096,
                        encoder_attention_heads=16,
                        feature_grad_mult=1.0,
                    )
                    self.model = Wav2Vec2Model(cfg)

                def extract_feat(self, input_data: "torch.Tensor") -> "torch.Tensor":
                    if input_data.ndim == 3:
                        input_data = input_data[:, :, 0]
                    with torch.no_grad():
                        features = self.model(
                            input_data, mask=False, features_only=True
                        )["x"]
                    return features

            class _DeepfakeDetector(torch.nn.Module, PyTorchModelHubMixin):
                """SSL front-end + adaptive pooling + FC binary head."""

                def __init__(self) -> None:
                    super().__init__()
                    self.ssl_orig_output_dim = 1024
                    self.num_classes = 2
                    self.m_ssl = _SSLModel()
                    self.adap_pool1d = torch.nn.AdaptiveAvgPool1d(output_size=1)
                    self.proj_fc = torch.nn.Linear(
                        in_features=self.ssl_orig_output_dim,
                        out_features=self.num_classes,
                    )

                def forward(self, wav: "torch.Tensor") -> "torch.Tensor":
                    emb = self.m_ssl.extract_feat(wav)  # [B, T, D]
                    emb = emb.transpose(1, 2)  # [B, D, T]
                    pooled = self.adap_pool1d(emb).squeeze(-1)  # [B, D]
                    return self.proj_fc(pooled)  # [B, 2]

            model = _DeepfakeDetector.from_pretrained(
                self.model_id, revision=self.revision
            ).to(self.device)
            model.eval()
            self._model = model
        except Exception as exc:
            raise RuntimeError(
                f"Could not load real detector checkpoint '{self.model_id}': {exc}"
            ) from exc

    def _prepare_input(self, samples: np.ndarray):
        """Validate a 16 kHz mono float window; return (samples, warning).

        Pure-numpy validation so malformed input never requires torch. Returns
        (None, reason) for unusable input. Tensor conversion and the official
        layer_norm preprocessing happen in predict() once torch is available.
        """
        samples = np.asarray(samples, dtype=np.float32)
        if samples.size == 0:
            return None, "empty_audio_window"

        warning = None
        finite = samples[np.isfinite(samples)]
        if finite.size != samples.size:
            warning = "non_finite_samples_removed"
            samples = finite
        if samples.size == 0:
            return None, "all_non_finite_samples"

        if warning is None and float(np.max(np.abs(samples))) > 8.0:
            warning = "unusual_amplitude_range"
            samples = np.clip(samples, -1.0, 1.0)

        return samples, warning

    def predict(self, audio_window: np.ndarray) -> Dict[str, Any]:
        import time

        started = time.perf_counter()
        samples, warning = self._prepare_input(audio_window)
        if samples is None:
            # Degraded result: neutral score with explicit warning, never a
            # confident "genuine" verdict.
            return {
                "acoustic_score": 0.5,
                "details": {
                    "mode": "real",
                    "model": self.model_id,
                    "status": "degraded",
                    "warning": warning,
                },
            }

        try:
            import torch

            self._ensure_model_loaded()
            waveform = torch.from_numpy(np.ascontiguousarray(samples)).to(self.device)
            # Official preprocessing: per-waveform layer normalization.
            waveform = torch.nn.functional.layer_norm(waveform, waveform.shape)
            with torch.inference_mode():
                logits = self._model(waveform.unsqueeze(0))
                probabilities = torch.softmax(logits, dim=-1)[0]

            fake_probability = float(probabilities[self.FAKE_INDEX].item())
            real_probability = float(probabilities[self.REAL_INDEX].item())
            predicted_label = (
                "fake" if fake_probability >= real_probability else "real"
            )
        except Exception as exc:
            # Degraded mode (including model-load failure): do not crash the
            # stream and do not fake confidence.
            return {
                "acoustic_score": 0.5,
                "details": {
                    "mode": "real",
                    "model": self.model_id,
                    "status": "degraded",
                    "error": f"{type(exc).__name__}: {exc}",
                },
            }

        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        details: Dict[str, Any] = {
            "mode": "real",
            "model": self.model_id,
            "revision": self.revision,
            "predicted_label": predicted_label,
            "fake_probability": round(fake_probability, 4),
            "real_probability": round(real_probability, 4),
            "inference_latency_ms": latency_ms,
            "sample_rate": self.sample_rate,
            "status": "ok",
        }
        if warning:
            details["warning"] = warning
        return {
            "acoustic_score": round(fake_probability, 4),
            "details": details,
        }


class ZeroGPUVoiceDetectorAdapter(BaseVoiceDetector):
    """Adapter wrapping ZeroGPUInferenceProvider into the BaseVoiceDetector interface."""

    def __init__(self, provider=None):
        if provider is None:
            from app.services.provider_factory import get_inference_provider
            provider = get_inference_provider()
        self.provider = provider

    def predict(self, audio_window: np.ndarray) -> Dict[str, Any]:
        result = self.provider.infer_audio_window_sync(audio_window)
        if not result.success or result.spoof_probability is None:
            return {
                "acoustic_score": None,
                "success": False,
                "inference_available": False,
                "detector_status": "unavailable",
                "error_code": result.error_code or "INFERENCE_UNAVAILABLE",
                "error_message": result.error_message or "ZeroGPU inference unavailable",
                "details": {
                    "mode": "zerogpu",
                    "status": "unavailable",
                    "error": result.error_message,
                },
            }
        return {
            "acoustic_score": round(result.spoof_probability, 4),
            "success": True,
            "inference_available": True,
            "detector_status": "ok",
            "details": {
                "mode": "zerogpu",
                "model": result.model_version_antispoof,
                "inference_time_ms": result.inference_time_ms,
            },
        }


def get_detector(
    mode: str,
    model_path: Optional[str] = None,
    model_id: str = "nii-yamagishilab/mms-300m-anti-deepfake",
    device: str = "cpu",
    revision: str = "main",
) -> BaseVoiceDetector:
    from app import config

    normalized_mode = mode.strip().lower()
    env_name = (
        os.getenv("ENVIRONMENT")
        or os.getenv("VOICETRUST_ENVIRONMENT")
        or config.ENVIRONMENT
    ).strip().lower()
    is_prod = env_name in {"production", "prod"}

    if is_prod and normalized_mode == "mock":
        raise RuntimeError(
            "PRODUCTION ENVIRONMENT SAFETY VIOLATION: "
            "MockVoiceDetector is strictly prohibited in production mode. "
            "Production must use a real inference provider (e.g. zerogpu)."
        )


    # "remote_hf" is the Render deployment spelling of the ZeroGPU remote
    # provider; both route to the Hugging Face Space through gradio_client.
    if normalized_mode in {"zerogpu", "remote_hf"}:
        return ZeroGPUVoiceDetectorAdapter()
    if normalized_mode == "real":
        return RealAntiSpoofDetector(
            model_id=model_id,
            model_path=model_path,
            device=device,
            revision=revision,
        )
    if normalized_mode == "ml":
        return LightweightMLVoiceDetector(model_path=model_path)
    if normalized_mode == "mock":
        return MockVoiceDetector()

    raise ValueError(
        f"Unknown VOICE_DETECTOR_MODE '{mode}'. "
        f"Expected one of: 'zerogpu'/'remote_hf', 'real', 'ml', 'mock'."
    )

