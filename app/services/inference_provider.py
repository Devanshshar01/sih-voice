"""
Abstract base class for inference providers and mock implementations.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Optional, List

import numpy as np


@dataclass
class InferenceResult:
    """Result of audio window inference."""
    spoof_probability: float
    speaker_embedding: List[float]
    inference_time_ms: float
    model_version_antispoof: str
    model_version_speaker: str
    sample_rate: int
    duration_ms: float


class InferenceProvider(abc.ABC):
    """Abstract base class for inference providers."""

    @abc.abstractmethod
    def infer_audio_window_sync(
        self, audio_window: np.ndarray
    ) -> InferenceResult:
        """
        Run inference on a single audio window (synchronous).

        Parameters
        ----------
        audio_window : np.ndarray
            Mono audio signal as a 1D numpy array of float32 samples.
            Expected to be at 16 kHz and approximately 4 seconds long.
            The provider may pad or truncate to a fixed length.

        Returns
        -------
        InferenceResult
            The inference result containing spoof probability and speaker embedding.
        """
        raise NotImplementedError

    async def infer_audio_window(
        self, audio_window: np.ndarray
    ) -> InferenceResult:
        """
        Run inference on a single audio window (asynchronous).

        Parameters
        ----------
        audio_window : np.ndarray
            Mono audio signal as a 1D numpy array of float32 samples.
            Expected to be at 16 kHz and approximately 4 seconds long.
            The provider may pad or truncate to a fixed length.

        Returns
        -------
        InferenceResult
            The inference result containing spoof probability and speaker embedding.
        """
        # Run the synchronous method in a thread pool to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.infer_audio_window_sync, audio_window
        )

    @abc.abstractmethod
    def is_available(self) -> bool:
        """
        Check if the provider is available and ready to serve requests.

        Returns
        -------
        bool
            True if the provider is available, False otherwise.
        """
        raise NotImplementedError


class MockInferenceProvider(InferenceProvider):
    """Mock inference provider for testing and fallback."""

    def __init__(self, baseline_spoof: float = 0.1, embedding_dim: int = 64):
        self.baseline_spoof = baseline_spoof
        self.embedding_dim = embedding_dim

    def infer_audio_window_sync(self, audio_window: np.ndarray) -> InferenceResult:
        """
        Run mock inference on a single audio window.

        Returns a deterministic result based on the audio content.
        """
        # Use the audio window to generate a deterministic pseudo-random number
        # for the spoof probability and the embedding.
        if audio_window.size == 0:
            # Return neutral values for empty audio
            spoof_probability = 0.5
            # Return a zero embedding
            speaker_embedding = [0.0] * self.embedding_dim
        else:
            # Deterministic pseudo-variance derived from the audio content
            # itself, so the same window always produces the same score.
            # We use a simple hash of the audio window's bytes.
            import hashlib
            digest = hashlib.sha1(audio_window.tobytes()).hexdigest()
            pseudo = (int(digest[:8], 16) % 1000) / 1000.0  # 0-1
            # Map to a spoof probability around the baseline
            spoof_probability = max(
                0.0, min(1.0, self.baseline_spoof + (pseudo - 0.5) * 2 * 0.1)
            )  # jitter of 0.1
            # Generate a deterministic embedding from the audio
            # We'll use the first `embedding_dim` coefficients of the DFT
            # as a simple feature.
            spectrum = np.abs(np.fft.rfft(audio_window, n=2048))
            # Take the first `embedding_dim` coefficients, or pad with zeros
            if spectrum.size >= self.embedding_dim:
                embedding = spectrum[: self.embedding_dim]
            else:
                embedding = np.pad(
                    spectrum, (0, self.embedding_dim - spectrum.size), mode="constant"
                )
            # Normalize the embedding
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
            speaker_embedding = embedding.tolist()

        return InferenceResult(
            spoof_probability=float(spoof_probability),
            speaker_embedding=speaker_embedding,
            inference_time_ms=1.0,  # mock is fast
            model_version_antispoof="mock",
            model_version_speaker="mock",
            sample_rate=16000,
            duration_ms=4000,
        )

    async def infer_audio_window(
        self, audio_window: np.ndarray
    ) -> InferenceResult:
        """
        Async version of infer_audio_window (just calls the sync version).
        """
        return self.infer_audio_window_sync(audio_window)

    def is_available(self) -> bool:
        """Mock provider is always available."""
        return True