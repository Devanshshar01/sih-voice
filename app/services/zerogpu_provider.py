"""
ZeroGPU inference provider for calling the Hugging Face Space.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import math
import os
import tempfile
import time
import wave
from typing import List, Optional

import numpy as np
from gradio_client import Client, handle_file

from .inference_provider import InferenceProvider, InferenceResult


MMS_MODEL_ID = "nii-yamagishilab/mms-300m-anti-deepfake"

# Canonical SatyaVoice acoustic window: 4 s @ 16 kHz, mono, float32 in [-1, 1].
TARGET_SAMPLE_RATE = 16000

logger = logging.getLogger("satyavoice.zerogpu")

# ZeroGPU free-tier quota exhaustion. When the Space (or gradio_client) rejects
# a call because the account is out of GPU minutes, every further attempt burns
# nothing but latency — and the failure is per-account, not per-request. The
# circuit breaker latches this state so the stream stops issuing GPU requests
# for every 4-second window and instead degrades safely (risk engine treats
# anti-spoof as unavailable, which raises — not lowers — the risk score).
QUOTA_EXHAUSTED_MARKERS = (
    "You have exceeded your ZeroGPU runs limit",
    "exceeded your ZeroGPU",
    "ZeroGPU runs limit",
    "GPU quota",
    "quota exceeded",
    "Quota exceeded",
)


def _auth_token_kwarg() -> str:
    """Return the auth keyword gradio_client.Client accepts on THIS install.

    gradio_client renamed its authentication parameter over major versions:
      - 1.x: Client(..., hf_token=...)
      - 2.x+ (Gradio 6 era): Client(..., token=...)
    Passing the wrong name either raises TypeError or (worse on 1.x) is
    silently forwarded as an unknown kwarg and dropped, leaving every Space
    call UNAUTHENTICATED — which surfaces to users as the quota-exhaustion
    error even when a perfectly valid HF_TOKEN is configured.
    """
    try:
        params = inspect.signature(Client.__init__).parameters
        if "token" in params:
            return "token"
        if "hf_token" in params:
            return "hf_token"
    except (TypeError, ValueError):  # pragma: no cover - defensive
        pass
    # Sensible default for unknown signatures: 1.x name.
    return "hf_token"



def _probability(value: object, field: str) -> float:
    """Return a finite probability or reject the remote payload."""
    probability = float(value)
    if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
        raise ValueError(f"Remote HF field {field!r} is not a valid probability")
    return probability


class ZeroGPUInferenceProvider(InferenceProvider):
    """Provider that calls a Hugging Face ZeroGPU Space for inference."""

    def __init__(
        self,
        space_url: str,
        hf_token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        if not space_url or not space_url.strip():
            raise ValueError(
                "HF_ZERO_GPU_SPACE configuration is required for ZeroGPUInferenceProvider"
            )
        self.space_url = space_url.rstrip("/")
        self.hf_token = hf_token
        self.timeout = timeout
        # Version-aware auth: 1.x wants hf_token=, 2.x+ wants token=. Never
        # log the token value itself.
        self._token_kwarg = _auth_token_kwarg()
        self.client_kwargs: dict = {"verbose": False}
        if self.hf_token:
            self.client_kwargs[self._token_kwarg] = self.hf_token
        logger.info(
            "ZeroGPU provider initialised: space=%s auth_kwarg=%s token_configured=%s",
            self.space_url,
            self._token_kwarg,
            bool(self.hf_token),
        )
        self._client = None

        # We'll use the predict API endpoint
        # NOTE: the Space's named endpoint is "/infer" (Gradio maps it to
        # /gradio_api/call/infer). "/predict" does not exist on this Space.
        self.api_name = "/infer"
        self._available = True
        # Quota-exhaustion circuit breaker: latched when the Space reports the
        # ZeroGPU runs limit is spent. Only reset by process restart or by an
        # explicitly defined cooldown (see QUOTA_COOLDOWN_SECONDS below).
        self._quota_exhausted_at: Optional[float] = None

    # Cooldown after quota exhaustion before the breaker allows a single probe
    # call again. ZeroGPU free quota resets on a rolling window (~minutes per
    # account tier); 10 minutes is conservative and bounded — not per-window.
    QUOTA_COOLDOWN_SECONDS = 600.0

    def _is_quota_error(self, exc: BaseException) -> bool:
        text = str(exc)
        return any(marker in text for marker in QUOTA_EXHAUSTED_MARKERS)

    def _mark_quota_exhausted(self, exc: BaseException) -> None:
        self._quota_exhausted_at = time.monotonic()
        logger.error(
            "ZeroGPU quota exhausted — circuit breaker OPEN for %.0fs. "
            "error_type=%s",
            self.QUOTA_COOLDOWN_SECONDS,
            type(exc).__name__,
        )

    def _quota_breaker_open(self) -> bool:
        if self._quota_exhausted_at is None:
            return False
        elapsed = time.monotonic() - self._quota_exhausted_at
        if elapsed >= self.QUOTA_COOLDOWN_SECONDS:
            # Cooldown elapsed: allow one probe attempt (half-open state).
            self._quota_exhausted_at = None
            self._available = True
            logger.info("ZeroGPU quota cooldown elapsed — breaker half-open, allowing probe")
            return False
        return True

    def quota_exhausted(self) -> bool:
        """True while the quota circuit breaker is latched open.

        Lazily evaluates the cooldown so a caller that only polls this method
        (without invoking inference) still sees the breaker half-open once the
        cooldown has elapsed.
        """
        return self._quota_breaker_open()

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = Client(self.space_url, **self.client_kwargs)
        return self._client

    def infer_audio_window_sync(
        self, audio_window: np.ndarray
    ) -> InferenceResult:
        """Run inference by calling the Hugging Face Space (blocking)."""
        # Circuit breaker: fail fast WITHOUT any GPU request while latched.
        if self._quota_breaker_open():
            return InferenceResult.failure(
                "QUOTA_EXHAUSTED",
                "ZeroGPU quota exhausted (circuit breaker open); "
                "anti-spoof evidence unavailable until cooldown elapses.",
                provider="zerogpu",
            )
        tmp_path: Optional[str] = None
        try:
            client = self._get_client()
            # gradio_client>=1.0 cannot serialize a bare numpy array for the
            # Space's gr.Audio input: construct_args() raises "The truth value
            # of an array with more than one element is ambiguous" BEFORE any
            # HTTP request is sent. Serialize the window to a 16 kHz mono WAV
            # and upload it via handle_file() instead (verified against the
            # live Space).
            samples = np.asarray(audio_window, dtype=np.float32).reshape(-1)
            fd, tmp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
            with wave.open(tmp_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(TARGET_SAMPLE_RATE)
                wav_file.writeframes(pcm.tobytes())
            result = client.predict(
                handle_file(tmp_path),  # the audio input, uploaded as a WAV
                api_name=self.api_name,
            )
            # The Space returns a structured error payload (status="error")
            # instead of a fake score on failure -- map that explicitly.
            if isinstance(result, dict) and result.get("status") == "error":
                error = result.get("error") or {}
                return InferenceResult.failure(
                    "INFERENCE_UNAVAILABLE",
                    str(error.get("message", "unknown Space error")),
                    provider="zerogpu",
                    model_version_antispoof=str(
                        result.get("model_version_antispoof", "unknown")
                    ),
                    model_version_speaker=str(
                        result.get("model_version_speaker", "unknown")
                    ),
                )
            if not isinstance(result, dict):
                raise ValueError("Remote HF response is not a JSON object")

            # The live Space returns both names.  SatyaVoice's canonical
            # acoustic score is the MMS fake probability; retain the legacy
            # spoof_probability name as an alias for that same value.
            fake_probability = _probability(
                result.get("fake_probability", result.get("spoof_probability")),
                "fake_probability",
            )
            if "real_probability" in result:
                real_probability = _probability(result["real_probability"], "real_probability")
            else:
                # Backward-compatible provider payloads exposed only the
                # canonical spoof_probability field. The live HF MMS Space
                # supplies both fields and therefore takes the strict path.
                real_probability = 1.0 - fake_probability
            if not math.isclose(fake_probability + real_probability, 1.0, abs_tol=0.01):
                raise ValueError("Remote HF fake/real probabilities do not sum to 1")
            spoof_probability = _probability(
                result.get("spoof_probability", fake_probability), "spoof_probability"
            )
            if not math.isclose(spoof_probability, fake_probability, abs_tol=1e-6):
                raise ValueError("Remote HF spoof_probability does not match fake_probability")
            model_version_antispoof = str(result.get("model_version_antispoof", ""))
            if model_version_antispoof != MMS_MODEL_ID:
                raise ValueError(
                    "Remote HF returned an unexpected antispoof model: "
                    f"{model_version_antispoof or '<missing>'}; expected {MMS_MODEL_ID}"
                )

            return InferenceResult(
                spoof_probability=fake_probability,
                speaker_embedding=result["speaker_embedding"],
                inference_time_ms=float(result["inference_time_ms"]),
                model_version_antispoof=model_version_antispoof,
                model_version_speaker=str(result["model_version_speaker"]),
                sample_rate=int(result["sample_rate"]),
                duration_ms=float(result["duration_ms"]),
                provider="zerogpu",
                success=True,
            )
        except Exception as e:
            # Quota exhaustion is a distinct, latched failure mode: stop issuing
            # GPU requests entirely instead of retrying every audio window.
            if self._is_quota_error(e):
                self._mark_quota_exhausted(e)
                return InferenceResult.failure(
                    "QUOTA_EXHAUSTED",
                    f"ZeroGPU quota exhausted: {e}",
                    provider="zerogpu",
                )
            # Any other failure: mark the provider unavailable and return an
            # explicit failure. NEVER fabricate a score or return a mock score
            # on transport failure.
            self._available = False
            logger.warning(
                "ZeroGPU call failed: error_type=%s message=%s",
                type(e).__name__,
                str(e)[:300],
            )
            return InferenceResult.failure(
                "INFERENCE_UNAVAILABLE",
                f"Failed to call ZeroGPU Space: {e}",
                provider="zerogpu",
            )
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


    def is_available(self) -> bool:
        """Check if the provider can currently serve requests.

        The quota circuit breaker participates: while latched open the provider
        is NOT available, so callers that consult is_available() skip it. No
        network probe is performed here (a health check that itself consumes
        quota would defeat the breaker).
        """
        if self._quota_breaker_open():
            return False
        return self._available