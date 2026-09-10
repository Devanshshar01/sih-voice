"""
Speaker vault with a SpeechBrain ECAPA-TDNN path when available and a
lightweight deterministic fallback for local demo environments.

The public contract is intentionally simple so the rest of the backend can
call into a single `SpeakerVault` instance without caring whether the
underlying encoder is a pretrained model or a local fallback embedding.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from app import config


class SpeakerVault:
    """Store enrolled speaker embeddings and compare live samples by cosine similarity."""

    def __init__(self) -> None:
        self.match_threshold = float(os.getenv("VOICETRUST_SPEAKER_MATCH_THRESHOLD", "0.80"))
        self.enabled = str(os.getenv("VOICETRUST_SPEAKER_VAULT_ENABLED", "true")).lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._entries: Dict[str, Dict[str, Any]] = {}
        self._speechbrain_model = None
        self._speechbrain_available = False
        self._speechbrain_model_name = os.getenv(
            "VOICETRUST_SPEAKER_MODEL",
            "speechbrain/spkrec-ecapa-voxceleb",
        )
        self._method = "deterministic-fallback"
        self._checkpoint_status = "SpeechBrain not installed in the current environment."

        self._load_speechbrain_if_available()
        self.embedding_dim = int(os.getenv("VOICETRUST_SPEAKER_EMBEDDING_DIM", "192" if self._speechbrain_available else "64"))

    def _load_speechbrain_if_available(self) -> None:
        try:
            try:
                from speechbrain.inference.speaker import EncoderClassifier
            except ImportError:
                from speechbrain.pretrained import EncoderClassifier
        except Exception:
            return

        self._speechbrain_available = True
        self._speechbrain_model = EncoderClassifier.from_hparams(
            source=self._speechbrain_model_name,
            savedir=f"./.cache/{self._speechbrain_model_name.replace('/', '_')}",
        )
        self._method = "speechbrain-ecapa-tdnn"
        self._checkpoint_status = (
            "SpeechBrain ECAPA-TDNN checkpoint detected and ready for speaker embeddings."
        )

    def enroll(self, speaker_id: str, audio_window: np.ndarray) -> Dict[str, Any]:
        speaker_id = (speaker_id or "").strip()
        if not speaker_id:
            raise ValueError("speaker_id is required for enrollment.")

        embedding = self._compute_embedding(audio_window)
        self._entries[speaker_id] = {
            "speaker_id": speaker_id,
            "embedding": embedding,
            "enrolled_at": time.time(),
        }

        return {
            "speaker_id": speaker_id,
            "embedding_dim": len(embedding),
            "vault_size": len(self._entries),
            "match_threshold": self.match_threshold,
            "method": self._method,
            "checkpoint_status": self._checkpoint_status,
            "enrolled": True,
        }

    def match(self, audio_window: np.ndarray) -> Dict[str, Any]:
        embedding = self._compute_embedding(audio_window)

        if not self._entries:
            return {
                "speaker_id": None,
                "speaker_match_score": 0.0,
                "matched": False,
                "vault_size": 0,
                "method": self._method,
                "checkpoint_status": self._checkpoint_status,
            }

        best_speaker_id = None
        best_score = -1.0

        for speaker_id, entry in self._entries.items():
            score = self._cosine_similarity(embedding, entry["embedding"])
            if score > best_score:
                best_speaker_id = speaker_id
                best_score = score

        return {
            "speaker_id": best_speaker_id,
            "speaker_match_score": round(float(best_score), 4),
            "matched": best_score >= self.match_threshold,
            "vault_size": len(self._entries),
            "method": self._method,
            "checkpoint_status": self._checkpoint_status,
        }

    def state(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "method": self._method,
            "checkpoint_status": self._checkpoint_status,
            "vault_size": len(self._entries),
            "match_threshold": self.match_threshold,
            "embedding_dim": self.embedding_dim,
        }

    def _compute_embedding(self, audio_window: np.ndarray) -> np.ndarray:
        samples = np.asarray(audio_window, dtype=np.float32)
        if samples.size == 0:
            dim = 192 if self._speechbrain_available else self.embedding_dim
            return np.zeros(dim, dtype=np.float32)

        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if peak > 0:
            samples = samples / peak

        if self._speechbrain_available and self._speechbrain_model is not None:
            try:
                import torch
                tensor = torch.from_numpy(samples).unsqueeze(0)
                with torch.no_grad():
                    emb = self._speechbrain_model.encode_batch(tensor)
                    emb_np = emb.squeeze().cpu().numpy().astype(np.float32)
                    norm = float(np.linalg.norm(emb_np))
                    if norm > 0:
                        emb_np = emb_np / norm
                    return emb_np
            except Exception:
                pass

        # Use a deterministic spectral feature vector. This keeps the demo
        # working in environments where SpeechBrain is not installed yet.
        spectrum = np.abs(np.fft.rfft(samples, n=2048))
        spectrum = np.log1p(np.maximum(spectrum, 1e-6))[: self.embedding_dim]

        embedding = np.zeros(self.embedding_dim, dtype=np.float32)
        embedding[: spectrum.size] = spectrum

        stats = np.array(
            [
                np.mean(samples),
                np.std(samples),
                np.mean(np.abs(samples)),
                np.mean(samples**2),
            ],
            dtype=np.float32,
        )

        if stats.size:
            embedding[-min(stats.size, 4) :] = stats[: min(stats.size, 4)]

        norm = float(np.linalg.norm(embedding))
        if norm > 0:
            embedding = embedding / norm

        return embedding

    @staticmethod
    def _cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        if denominator == 0.0:
            return 0.0
        return float(np.dot(left, right) / denominator)


speaker_vault = SpeakerVault()


def get_speaker_vault() -> SpeakerVault:
    return speaker_vault
