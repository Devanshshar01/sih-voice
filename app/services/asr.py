"""
faster-whisper model manager: a process-wide singleton with safe lazy
initialization.

Why a manager instead of per-request loads: WhisperModel construction pulls
several hundred MB of weights and converts them to the requested compute
type. Loading per request would make the <500 ms decision target
unreachable and thrash memory. This module guarantees at most ONE model
instance per process (per unique config), created on first real use, with
double-checked locking so concurrent WebSocket lanes cannot race a load.

Failure semantics: if faster-whisper or the checkpoint is unavailable,
``transcribe`` raises RuntimeError once and the caller (stream pipeline)
degrades gracefully — the WS never crashes, and the failure is surfaced in
telemetry. The manager also reports availability so capability endpoints can
answer honestly.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from app import config


class WhisperModelManager:
    """Lazy, thread-safe holder for one faster-whisper model."""

    def __init__(
        self,
        model_size: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
    ) -> None:
        self.model_size = model_size or config.ASR_MODEL_SIZE
        self.device = device or config.ASR_DEVICE
        self.compute_type = compute_type or config.ASR_COMPUTE_TYPE
        self._lock = threading.Lock()
        self._model = None
        self._load_error: Optional[str] = None

    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """True if faster-whisper is importable (not necessarily loaded)."""
        try:
            import faster_whisper  # noqa: F401
            return True
        except Exception:
            return False

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def get_model(self):
        """Return the loaded model, loading it exactly once if needed."""
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:  # double-checked locking
                return self._model
            try:
                from faster_whisper import WhisperModel

                start = time.perf_counter()
                self._model = WhisperModel(
                    self.model_size,
                    device=self.device,
                    compute_type=self.compute_type,
                )
                _load_ms = (time.perf_counter() - start) * 1000.0
                self._load_error = None
                return self._model
            except Exception as exc:
                # Record the failure but do not cache a broken state: the
                # next call retries, so a transient download hiccup can heal.
                self._load_error = f"{type(exc).__name__}: {exc}"
                raise RuntimeError(
                    f"Could not load faster-whisper model "
                    f"'{self.model_size}' ({self.device}/{self.compute_type}): {exc}"
                ) from exc

    def transcribe(
        self,
        audio_window: np.ndarray,
        language: Optional[str] = None,
        beam_size: Optional[int] = None,
        vad_filter: Optional[bool] = None,
    ) -> tuple[str, Optional[str]]:
        """Transcribe one 16 kHz float32 window.

        Returns ``(text, detected_language)``. ``language`` is a per-window
        hint; None lets Whisper auto-detect. Raises RuntimeError on model
        failure — the caller is responsible for degradation.
        """
        samples = np.asarray(audio_window, dtype=np.float32)
        if samples.size == 0:
            return "", None

        model = self.get_model()
        segments, info = model.transcribe(
            samples,
            language=(language or None),
            beam_size=beam_size or config.ASR_BEAM_SIZE,
            vad_filter=config.ASR_VAD_FILTER if vad_filter is None else vad_filter,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        detected = getattr(info, "language", None)
        return text, detected


# Process-wide singleton (one model per process, per config).
whisper_manager = WhisperModelManager()


def get_whisper_manager() -> WhisperModelManager:
    return whisper_manager
