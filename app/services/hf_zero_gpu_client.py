"""
Render-side client for the hf_zero_gpu Space (MMS-300M-AntiDeepfake).

When the backend runs with VOICETRUST_DETECTOR_MODE=remote_hf, the
anti-spoof stage is delegated to the ZeroGPU Space (the only GPU-heavy
component in the stack). The fairseq/torch stack is NOT installed on the
web tier; this client speaks the Space's Gradio JSON contract instead.

Response mapping (contract-preserving):
  * Space {"ok": true, "fake_probability": p, ...}
        -> {"acoustic_score": p, "details": {...}}  (same shape the
           in-process MMS provider returns — risk fusion and telemetry
           are untouched).
  * Space {"ok": false, "status": "degraded", ...}
        -> {"acoustic_score": 0.5, "details": {status: degraded_input...}}
           — the uninformative prior, explicitly flagged. NEVER mapped to
           a "genuine" (low) score.
  * Network/timeout failure
        -> same degraded shape with the error surfaced in details.

Configuration:
    VOICETRUST_HF_SPACE_ID     e.g. "devanssnarul-satyavoice-anti-spoof"
    VOICETRUST_HF_TOKEN        optional, for private Spaces
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

import numpy as np

from app.services.anti_spoof_provider import (
    MMS_MODEL_ID,
    validate_audio_16k_mono,
)

_DEGRADED_SCORE = 0.5  # uninformative prior — matches parallel_inference


class HFZeroGPUDetector:
    """Gradio-Client-backed detector implementing the BaseVoiceDetector
    predict() contract. One client instance per process (cached singleton
    via get_detector)."""

    def __init__(
        self,
        space_id: str,
        token: Optional[str] = None,
        timeout_seconds: float = 30.0,
        sample_rate: int = 16000,
    ):
        if not space_id:
            raise ValueError(
                "HFZeroGPUDetector requires VOICETRUST_HF_SPACE_ID "
                "(e.g. 'user/satyavoice-anti-spoof')."
            )
        self.space_id = space_id
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.sample_rate = sample_rate
        self._client = None
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        # What actually runs on the Space (provenance must be truthful).
        return MMS_MODEL_ID

    @property
    def loaded(self) -> bool:
        return self._client is not None

    def _get_client(self):
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                from gradio_client import Client
            except ImportError as exc:
                raise RuntimeError(
                    "VOICETRUST_DETECTOR_MODE=remote_hf requires the "
                    "gradio-client package (pip install gradio_client)."
                ) from exc
            self._client = Client(self.space_id, hf_token=self.token)
            return self._client

    def _degraded(self, status: str, warning: str) -> Dict[str, Any]:
        return {
            "acoustic_score": _DEGRADED_SCORE,
            "details": {
                "mode": "real",
                "provider": "hf_zero_gpu",
                "model": self.model_id,
                "space": self.space_id,
                "status": status,
                "warning": warning[:300],
            },
        }

    def predict(self, audio_window: np.ndarray) -> Dict[str, Any]:
        t0 = time.perf_counter()
        try:
            samples = validate_audio_16k_mono(audio_window, self.sample_rate)
        except ValueError as exc:
            return self._degraded("degraded_input", str(exc))

        payload = {
            "wav": samples.tolist(),
            "sample_rate": self.sample_rate,
        }
        try:
            client = self._get_client()
            raw = client.predict(
                api_name="/detect",
                wav_json=__import__("json").dumps(payload),
            )
        except Exception as exc:
            # Network/Space failure: degraded, never "genuine".
            return self._degraded(
                "degraded_remote",
                f"{type(exc).__name__}: {exc}",
            )

        import json as _json

        try:
            result = raw if isinstance(raw, dict) else _json.loads(raw)
        except Exception as exc:
            return self._degraded(
                "degraded_output", f"unparseable Space response: {exc}"
            )

        if not result.get("ok"):
            return self._degraded(
                result.get("status", "degraded"),
                result.get("error", "Space reported failure"),
            )

        fake_p = float(result.get("fake_probability", _DEGRADED_SCORE))
        real_p = float(result.get("real_probability", 1.0 - fake_p))
        return {
            "acoustic_score": round(fake_p, 4),
            "details": {
                "mode": "real",
                "provider": "hf_zero_gpu",
                "model": result.get("model_id", self.model_id),
                "base_model": result.get("base_model"),
                "revision": result.get("revision"),
                "license": result.get("license"),
                "space": self.space_id,
                "status": "ok",
                "fake_probability": round(fake_p, 4),
                "real_probability": round(real_p, 4),
                "predicted_label": result.get("predicted_label"),
                "sample_rate": self.sample_rate,
                "inference_latency_ms": round(
                    (time.perf_counter() - t0) * 1000.0, 2
                ),
                "remote_inference_ms": result.get("inference_latency_ms"),
                "remote_device": result.get("device"),
            },
        }

    def infer(self, audio_window: np.ndarray) -> Dict[str, Any]:
        return self.predict(audio_window)
