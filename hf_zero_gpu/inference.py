"""
hf_zero_gpu.inference — the ONLY module that owns the MMS model.

The single heavy GPU object in the SatyaVoice stack. Loaded exactly once at
Space startup (see hf_zero_gpu/app.py -> load_model at import time), kept in
eval() mode and GPU-resident; every request runs under torch.inference_mode()
with no per-request architecture construction.

Model: nii-yamagishilab/mms-300m-anti-deepfake (NII Yamagishi Lab,
CC BY-NC-SA 4.0). fairseq-based loading per the official model card —
NOT AutoModelForAudioClassification (this checkpoint has no HF classifier
head and cannot be read that way).

Response schema (JSON-compatible, stable contract consumed by the Render
backend's anti-spoof client):

    {
      "ok": true,
      "model_id": "nii-yamagishilab/mms-300m-anti-deepfake",
      "base_model": "facebook/mms-300m",
      "revision": "<pinned at startup>",
      "license": "CC BY-NC-SA 4.0",
      "fake_probability": float,     # index 0 of the softmax
      "real_probability": float,     # index 1 of the softmax (sum ~= 1)
      "predicted_label": "fake" | "real",
      "sample_rate": 16000,
      "inference_latency_ms": float, # model call only (excludes network)
      "load_ms": float,              # one-time startup load cost
      "device": "cuda" | "cpu",
    }

Failure schema (never fake a "genuine" result):

    {"ok": false, "error_type": "...", "error": "...", "status": "degraded"}

The Render backend maps "ok": false to its existing degraded-acoustic
path (acoustic_score = 0.5 uninformative prior + degraded flag in
telemetry). It never maps failure to a low score.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger("hf_zero_gpu.inference")

MODEL_ID = "nii-yamagishilab/mms-300m-anti-deepfake"
BASE_MODEL = "facebook/mms-300m"
LICENSE = "CC BY-NC-SA 4.0"
FAKE_INDEX = 0   # from the official model card: prob[0] = fake
REAL_INDEX = 1   # prob[1] = real

# MMS-300M SSL front-end configuration (official example; required to build
# the fairseq architecture before loading the checkpoint weights).
_W2V2_CONFIG_KWARGS = dict(
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

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "model": None,
    "torch": None,
    "device": None,
    "revision": None,
    "load_ms": None,
    "load_error": None,
}


def _resolve_device() -> str:
    """ZeroGPU: cuda when the platform assigns a GPU, else CPU fallback."""
    try:
        import torch

        if torch.cuda.is_available():
            # ZeroGPU slices appear as cuda:0 to the process.
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _resolve_revision() -> str:
    import os

    return os.getenv("MMS_MODEL_REVISION", "main").strip() or "main"


def load_model() -> Dict[str, Any]:
    """Load the checkpoint exactly once. Safe to call repeatedly.

    Called once at Space startup (module import in app.py). Subsequent calls
    are no-ops returning the current state — per-request loading is the
    thing this module exists to prevent.
    """
    if _state["model"] is not None:
        return _model_info()

    with _lock:
        if _state["model"] is not None:  # double-checked locking
            return _model_info()

        import torch
        from fairseq.models.wav2vec import Wav2Vec2Config, Wav2Vec2Model
        from huggingface_hub import PyTorchModelHubMixin  # noqa: F401

        device = _resolve_device()
        revision = _resolve_revision()
        start = time.perf_counter()

        class _SSLModel(torch.nn.Module):
            def __init__(self):
                super().__init__()
                cfg = Wav2Vec2Config(**_W2V2_CONFIG_KWARGS)
                self.model = Wav2Vec2Model(cfg)

            def extract_feat(self, input_data):
                if input_data.ndim == 3:
                    input_data = input_data[:, :, 0]
                features = self.model(input_data, mask=False, features_only=True)["x"]
                return features

        class _DeepfakeDetector(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.ssl_orig_output_dim = 1024
                self.num_classes = 2
                self.m_ssl = _SSLModel()
                self.adap_pool1d = torch.nn.AdaptiveAvgPool1d(output_size=1)
                self.proj_fc = torch.nn.Linear(
                    in_features=self.ssl_orig_output_dim, out_features=self.num_classes
                )

            def forward(self, wav):
                emb = self.m_ssl.extract_feat(wav)  # [B, T, D]
                emb = emb.transpose(1, 2)           # [B, D, T]
                pooled = self.adap_pool1d(emb).squeeze(-1)  # [B, D]
                return self.proj_fc(pooled)         # [B, 2]

        hub_kwargs = {} if revision == "main" else {"revision": revision}
        model = _DeepfakeDetector.from_pretrained(MODEL_ID, **hub_kwargs)
        model.to(device)
        model.eval()

        _state.update(
            {
                "model": model,
                "torch": torch,
                "device": device,
                "revision": revision,
                "load_ms": (time.perf_counter() - start) * 1000.0,
                "load_error": None,
            }
        )
        logger.info(
            "MMS-300M-AntiDeepfake loaded once at startup: device=%s load_ms=%.0f",
            device,
            _state["load_ms"],
        )
        return _model_info()


def _model_info() -> Dict[str, Any]:
    return {
        "model_id": MODEL_ID,
        "base_model": BASE_MODEL,
        "license": LICENSE,
        "loaded": _state["model"] is not None,
        "device": _state["device"],
        "revision": _state["revision"],
        "load_ms": _state["load_ms"],
        "load_error": _state["load_error"],
    }


def model_info() -> Dict[str, Any]:
    """Public status snapshot (safe to expose on a Gradio status endpoint)."""
    return _model_info()


def _failure(error_type: str, message: str) -> Dict[str, Any]:
    return {
        "ok": False,
        "status": "degraded",
        "error_type": error_type,
        "error": message[:300],
        "model_id": MODEL_ID,
    }


def detect_fake(wav: np.ndarray, sample_rate: int = 16000) -> Dict[str, Any]:
    """One 16 kHz mono float32 waveform -> fake/real probabilities.

    Never raises to the caller: every failure mode returns the degraded
    schema so the backend can flag acoustic evidence unavailable instead of
    silently assuming genuine audio.
    """
    t0 = time.perf_counter()

    # ---- Input validation (never crash the handler on bad input) --------
    try:
        arr = np.asarray(wav)
        if arr.size == 0:
            return _failure("invalid_input", "empty waveform")
        arr = arr.astype(np.float32, copy=True).reshape(-1)
        bad = ~np.isfinite(arr)
        if bad.any():
            arr[bad] = 0.0
        np.clip(arr, -1e4, 1e4, out=arr)
        if int(sample_rate) != 16000:
            return _failure(
                "invalid_input", f"sample_rate must be 16000, got {sample_rate}"
            )
    except Exception as exc:
        return _failure("invalid_input", f"{type(exc).__name__}: {exc}")

    # ---- Model availability (startup load should have happened) ---------
    if _state["model"] is None:
        try:
            load_model()
        except Exception as exc:
            return _failure(
                "model_unavailable", f"startup load failed: {type(exc).__name__}: {exc}"
            )

    torch = _state["torch"]
    model = _state["model"]

    try:
        # Official preprocessing: layer_norm over the whole window.
        wav_t = torch.from_numpy(arr)
        wav_t = torch.nn.functional.layer_norm(wav_t, wav_t.shape)
        inputs = wav_t.unsqueeze(0).to(_state["device"])

        with torch.inference_mode():
            logits = model(inputs)
            probs = torch.softmax(logits, dim=-1)[0]

        fake_p = float(probs[FAKE_INDEX].item())
        real_p = float(probs[REAL_INDEX].item())
        total = fake_p + real_p
        if total <= 0 or not np.isfinite(fake_p) or not np.isfinite(real_p):
            return _failure("invalid_output", "non-finite model probabilities")

        fake_p, real_p = fake_p / total, real_p / total
        inference_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "ok": True,
            "model_id": MODEL_ID,
            "base_model": BASE_MODEL,
            "revision": _state["revision"],
            "license": LICENSE,
            "fake_probability": round(fake_p, 4),
            "real_probability": round(real_p, 4),
            "predicted_label": "fake" if fake_p >= real_p else "real",
            "sample_rate": 16000,
            "inference_latency_ms": round(inference_ms, 2),
            "load_ms": round(_state["load_ms"] or 0.0, 1),
            "device": _state["device"],
        }
    except Exception as exc:
        return _failure(
            "inference_error", f"{type(exc).__name__}: {exc}"
        )
