"""
MMS-300M-AntiDeepfake provider — the active production anti-spoof detector.

Model: nii-yamagishilab/mms-300m-anti-deepfake (NII/Yamagishi Lab,
CC BY-NC-SA 4.0 — research/educational use). An AntiDeepfake model
post-trained on top of facebook/mms-300m for binary fake/real speech
detection. Currently used OFF-THE-SHELF; SatyaVoice-specific fine-tuning is
a separate future task.

Loading requirements (from the official model card — verified 2026-09):
the checkpoint is a fairseq-style Wav2Vec2 SSL front-end (MMS-300M config:
24 layers, embed 1024, FFN 4096, 16 heads, final_dim 768) with an
AdaptiveAvgPool1d + Linear(1024 -> 2) back-end, distributed via
PyTorchModelHubMixin. It CANNOT be loaded with
`transformers.AutoModelForAudioClassification` — the checkpoint has no HF
`config.json` classifier head. The loading path below mirrors the official
inference example exactly.

Preprocessing (per the official card):
    16 kHz mono waveform -> layer_norm over the whole window
(logits order: index 0 = FAKE, index 1 = REAL; verified from the card's
"real prob = prob[1], fake prob = prob[0]" output formatting.)

Output contract (SatyaVoice acoustic convention):
    acoustic_score = P(fake) — higher means MORE fraud risk. This matches
    the risk engine exactly (risk_engine treats acoustic_score as synthesis
    probability; regression-tested in tests/test_mms_detector.py).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import numpy as np

# Authoritative identifiers — the production cloud/Edge-cloud detector.
MMS_MODEL_ID = "nii-yamagishilab/mms-300m-anti-deepfake"
MMS_BASE_MODEL = "facebook/mms-300m"
MMS_LICENSE = "CC BY-NC-SA 4.0"
# Softmax index -> label mapping from the official model card.
MMS_FAKE_INDEX = 0
MMS_REAL_INDEX = 1

# MMS-300M SSL front-end configuration (from the official inference example;
# required to construct the fairseq Wav2Vec2Model before loading weights).
_MMS_W2V2_CONFIG_KWARGS = dict(
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


def validate_audio_16k_mono(
    samples: np.ndarray, sample_rate: int = 16000
) -> np.ndarray:
    """Sanitize a detector input window. Raises ValueError on hopeless input.

    Returns a float32 C-contiguous copy with NaN/Inf removed (zeroed) and
    finite values only. Amplitude is NOT renormalized here — the MMS
    preprocessing applies its own layer_norm downstream.
    """
    arr = np.asarray(samples)
    if arr.size == 0:
        raise ValueError("empty audio window")
    arr = arr.astype(np.float32, copy=True).reshape(-1)
    # NaN/Inf -> 0 (a window with a few corrupted samples stays usable;
    # callers treat a fully-corrupt window via the empty/zero path).
    bad = ~np.isfinite(arr)
    if bad.any():
        arr[bad] = 0.0
    # Reasonable amplitude sanity: clip pathological values so the model
    # never sees +/-inf-scale input after sanitization.
    np.clip(arr, -1e4, 1e4, out=arr)
    if sample_rate != 16000:
        raise ValueError(f"detector requires 16 kHz input, got {sample_rate}")
    return arr


class MMSAntiDeepfakeDetector:
    """Off-the-shelf MMS-300M-AntiDeepfake detector (fairseq loading path).

    The heavy model is loaded EXACTLY ONCE per instance (double-checked
    locking) and kept resident; every predict() reuses it under
    torch.inference_mode() with no per-request object construction beyond
    the waveform tensor.
    """

    def __init__(
        self,
        model_id: str = MMS_MODEL_ID,
        model_path: Optional[str] = None,
        device: str = "cpu",
        revision: str = "main",
        sample_rate: int = 16000,
    ):
        self.model_id = model_path or model_id
        self.expected_model_id = model_id  # for provenance assertions
        self.device = device
        self.revision = revision
        self.sample_rate = sample_rate
        self._model = None
        self._torch = None
        self._load_error: Optional[str] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def _ensure_model_loaded(self):
        """Load once (thread-safe). Returns (torch_module, model)."""
        if self._model is not None:
            return self._torch, self._model

        with self._lock:
            if self._model is not None:  # double-checked locking
                return self._torch, self._model

            try:
                import torch  # heavy, lazy
                from huggingface_hub import PyTorchModelHubMixin  # noqa: F401
                from fairseq.models.wav2vec import Wav2Vec2Config, Wav2Vec2Model
            except ImportError as exc:
                self._load_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(
                    "MMS-300M-AntiDeepfake requires torch, huggingface-hub and "
                    "fairseq (per the official model card). Install "
                    "requirements.txt before VOICETRUST_DETECTOR_MODE=real."
                ) from exc

            try:
                start = time.perf_counter()

                class _SSLModel(torch.nn.Module):
                    def __init__(self):
                        super().__init__()
                        cfg = Wav2Vec2Config(**_MMS_W2V2_CONFIG_KWARGS)
                        self.model = Wav2Vec2Model(cfg)

                    def extract_feat(self, input_data):
                        if input_data.ndim == 3:
                            input_data = input_data[:, :, 0]
                        features = self.model(
                            input_data, mask=False, features_only=True
                        )["x"]
                        return features

                class _DeepfakeDetector(torch.nn.Module):
                    def __init__(self):
                        super().__init__()
                        self.ssl_orig_output_dim = 1024
                        self.num_classes = 2
                        self.m_ssl = _SSLModel()
                        self.adap_pool1d = torch.nn.AdaptiveAvgPool1d(output_size=1)
                        self.proj_fc = torch.nn.Linear(
                            in_features=self.ssl_orig_output_dim,
                            out_features=self.num_classes,
                        )

                    def forward(self, wav):
                        emb = self.m_ssl.extract_feat(wav)  # [B, T, D]
                        emb = emb.transpose(1, 2)  # [B, D, T]
                        pooled = self.adap_pool1d(emb).squeeze(-1)  # [B, D]
                        return self.proj_fc(pooled)  # [B, 2]

                # Load the published checkpoint weights into the exact
                # architecture from the official example. from_pretrained
                # fetches model.safetensors from the Hub (or model_path).
                hub_kwargs = {}
                if self.revision and self.revision != "main":
                    hub_kwargs["revision"] = self.revision
                model = _DeepfakeDetector.from_pretrained(
                    self.model_id, **hub_kwargs
                )
                model.to(self.device)
                model.eval()  # mandatory: inference-only, no dropout/BN drift

                self._torch = torch
                self._model = model
                self._load_ms = (time.perf_counter() - start) * 1000.0
                self._load_error = None
                return self._torch, self._model
            except Exception as exc:
                self._load_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(
                    f"Could not load MMS-300M-AntiDeepfake checkpoint "
                    f"'{self.model_id}': {exc}"
                ) from exc

    # ------------------------------------------------------------------
    def _preprocess(self, samples: np.ndarray):
        """Official preprocessing: layer_norm over the whole window, then
        [B, T] tensor on device. Reuses the loaded torch module (no reimport
        per request, no unnecessary copies)."""
        torch = self._torch
        wav = torch.from_numpy(samples)  # zero-copy view over float32 numpy
        wav = torch.nn.functional.layer_norm(wav, wav.shape)
        return wav.unsqueeze(0).to(self.device)

    def predict(self, audio_window: np.ndarray) -> Dict[str, Any]:
        """One window in, acoustic result out (same contract as the old
        RealAntiSpoofDetector — nothing downstream changes)."""
        t0 = time.perf_counter()
        try:
            samples = validate_audio_16k_mono(audio_window, self.sample_rate)
        except ValueError as exc:
            # Malformed input is NEVER reported as genuine — 0.5 is the
            # uninformative prior and the telemetry carries the warning.
            return {
                "acoustic_score": 0.5,
                "details": {
                    "mode": "real",
                    "model": self.model_id,
                    "status": "degraded_input",
                    "warning": str(exc),
                },
            }

        torch, model = self._ensure_model_loaded()
        try:
            inputs = self._preprocess(samples)
            with torch.inference_mode():
                logits = model(inputs)
                probs = torch.softmax(logits, dim=-1)[0]

            fake_p = float(probs[MMS_FAKE_INDEX].item())
            real_p = float(probs[MMS_REAL_INDEX].item())
        except Exception as exc:
            # Malformed output / inference failure: uninformative prior,
            # explicitly flagged — NEVER a false "genuine" low score. (The
            # stream pipeline additionally degrades on propagated errors;
            # catching here keeps direct call sites safe too.)
            return {
                "acoustic_score": 0.5,
                "details": {
                    "mode": "real",
                    "model": self.model_id,
                    "status": "degraded_output",
                    "warning": f"{type(exc).__name__}: {exc}",
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                },
            }
        total = fake_p + real_p
        if total <= 0 or not np.isfinite(fake_p) or not np.isfinite(real_p):
            # Malformed model output: uninformative, explicitly flagged.
            return {
                "acoustic_score": 0.5,
                "details": {
                    "mode": "real",
                    "model": self.model_id,
                    "status": "degraded_output",
                    "warning": "non-finite model probabilities",
                    "latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                },
            }
        fake_p, real_p = fake_p / total, real_p / total

        return {
            # SatyaVoice convention: acoustic_score = P(fake) = fraud risk.
            "acoustic_score": round(fake_p, 4),
            "details": {
                "mode": "real",
                "model": self.model_id,
                "model_family": "mms-300m-anti-deepfake",
                "base_model": MMS_BASE_MODEL,
                "revision": self.revision,
                "license": MMS_LICENSE,
                "device": self.device,
                "status": "ok",
                # Explicit normalized probabilities (sum ~1) so downstream
                # consumers never have to re-derive the direction.
                "fake_probability": round(fake_p, 4),
                "real_probability": round(real_p, 4),
                "predicted_label": "fake" if fake_p >= real_p else "real",
                "label_map": {"0": "fake", "1": "real"},
                "sample_rate": self.sample_rate,
                "inference_latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                "load_ms": round(getattr(self, "_load_ms", 0.0), 1),
            },
        }

    # Backward-compat alias: some call sites may use infer().
    def infer(self, audio_window: np.ndarray) -> Dict[str, Any]:
        return self.predict(audio_window)


# Backward-compatible alias: the factory still calls this the "real" detector.
RealAntiSpoofDetector = MMSAntiDeepfakeDetector
