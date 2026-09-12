"""
Persistent, versioned, privacy-aware speaker identity vault (ECAPA-TDNN).

Storage model (see app/db/models.py):
  * ``SpeakerIdentity``  — one enrolled speaker: tenant/user identity, the
    aggregated centroid embedding, and full model provenance (encoder
    identifier, model version, normalization, embedding dimension).
  * ``SpeakerEnrollmentSample`` — one DERIVED embedding per enrollment
    sample. Raw audio is never persisted; only float32 embeddings plus
    non-biometric quality metadata (RMS/peak).

Embedding lifecycle:
  1. encode    — ECAPA-TDNN via SpeechBrain when available, deterministic
     spectral fallback otherwise (same fallback as before, explicitly
     identified by method + model_version so the two are never confused).
  2. normalize — L2 (configurable); stored embeddings are unit vectors.
  3. store     — each sample row is inserted; the centroid is recomputed as
     the L2-renormalized mean of all ACTIVE sample embeddings (robust
     aggregation rather than blind replacement).
  4. verify    — live window -> embedding (same encoder+version), cosine
     similarity against the centroid, compared to a configurable threshold.
  5. revoke    — soft delete (is_active=False); embeddings become inert and
     are excluded from every match. Hard delete is available for GDPR-style
     erasure.

Version gating: a live embedding is only compared against a stored centroid
whose (model_identifier, model_version, normalization, dimension) all match
the current runtime encoder. Mismatched identities are reported as
``model_version_mismatch`` instead of producing a meaningless similarity.

Privacy properties:
  * no raw audio ever reaches the database or the logs;
  * embeddings are never logged (see ``_log_safe``) and never returned by
    ordinary API responses (only dimensions/versions are exposed);
  * deletion/revocation is a first-class operation.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

from app import config

logger = logging.getLogger("satyavoice.speaker")  # deliberately never logs embeddings


class SpeakerVault:
    """DB-backed speaker identity store with ECAPA-TDNN provenance."""

    def __init__(self, session_factory=None) -> None:
        self.match_threshold = config.SPEAKER_MATCH_THRESHOLD
        self.embedding_dim = config.SPEAKER_EMBEDDING_DIM
        self.enabled = config.SPEAKER_VAULT_ENABLED
        self.model_identifier = config.SPEAKER_MODEL
        self.model_version = config.SPEAKER_MODEL_VERSION
        self.normalization = config.SPEAKER_EMBEDDING_NORMALIZATION
        self.aggregation = config.SPEAKER_ENROLLMENT_AGGREGATION
        self.max_samples = config.SPEAKER_MAX_ENROLLMENT_SAMPLES

        # Session factory is injectable for tests; defaults to the app engine.
        if session_factory is None:
            from app.db.database import SessionLocal

            session_factory = SessionLocal
        self._session_factory = session_factory

        self._encoder_lock = threading.Lock()
        self._speechbrain_model = None
        self._speechbrain_available = False
        self._method = "deterministic-fallback"
        self._checkpoint_status = "SpeechBrain not installed in the current environment."

        self._load_speechbrain_if_available()

    # ------------------------------------------------------------------
    # Encoder
    # ------------------------------------------------------------------
    def _load_speechbrain_if_available(self) -> None:
        try:
            from speechbrain.pretrained import EncoderClassifier  # type: ignore
        except Exception:
            return

        self._speechbrain_available = True
        self._speechbrain_model = EncoderClassifier.from_hparams(
            source=self.model_identifier,
            savedir=f"./.cache/{self.model_identifier.replace('/', '_')}",
        )
        self._method = "speechbrain-ecapa-tdnn"
        self._checkpoint_status = (
            "SpeechBrain ECAPA-TDNN checkpoint detected and ready for speaker embeddings."
        )

    def encoder_signature(self) -> Dict[str, Any]:
        """Provenance of the CURRENT runtime encoder.

        Stored enrollments must match this signature to be comparable.
        """
        return {
            "model_identifier": self.model_identifier,
            "model_version": self.model_version,
            "normalization": self.normalization,
            "embedding_dimension": self._current_embedding_dimension(),
            "method": self._method,
        }

    def _current_embedding_dimension(self) -> int:
        # SpeechBrain ECAPA produces 192-dim embeddings; the fallback uses the
        # configured dim. Keep them distinct so version gating catches swaps.
        if self._speechbrain_available:
            return 192
        return self.embedding_dim

    def _compute_embedding(self, audio_window: np.ndarray) -> np.ndarray:
        samples = np.asarray(audio_window, dtype=np.float32)
        if samples.size == 0:
            raise ValueError("Cannot compute an embedding from empty audio.")

        if self._speechbrain_available and self._speechbrain_model is not None:
            with self._encoder_lock:  # torch models are not thread-safe
                import torch

                tensor = torch.from_numpy(samples).unsqueeze(0)
                emb = self._speechbrain_model.encode_batch(tensor)
                embedding = emb.squeeze().detach().cpu().numpy().astype(np.float32)
        else:
            embedding = self._fallback_embedding(samples)

        embedding = self._normalize(embedding)
        return embedding

    def _fallback_embedding(self, samples: np.ndarray) -> np.ndarray:
        """Deterministic stand-in for ECAPA when SpeechBrain is absent.

        A mel-band log-spectrum averaged over frames — a classic "poor man's
        speaker embedding" that captures vocal-tract timbre — plus coarse
        signal statistics. Same-signature contract as the real encoder
        (fixed dimension, L2-normalized), but honestly labeled as the
        fallback so results are never mistaken for ECAPA scores.
        """
        peak = float(np.max(np.abs(samples))) if samples.size else 0.0
        if peak > 0:
            samples = samples / peak

        # Mel-spaced band energies averaged over 32 ms frames (voiced timbre).
        frame_len, hop = 512, 256
        n_frames = max(1, (samples.size - frame_len) // hop + 1)
        n_fft = frame_len
        window = np.hanning(frame_len).astype(np.float32)
        band_energy = np.zeros(min(self.embedding_dim, 40), dtype=np.float64)
        for i in range(n_frames):
            frame = samples[i * hop : i * hop + frame_len]
            if frame.size < frame_len:
                frame = np.pad(frame, (0, frame_len - frame.size))
            spectrum = np.abs(np.fft.rfft(frame * window, n=n_fft))
            mel = np.linspace(0, spectrum.size - 1, band_energy.size + 1)
            for b in range(band_energy.size):
                lo, hi = int(mel[b]), max(int(mel[b]) + 1, int(mel[b + 1]))
                band_energy[b] += float(np.mean(spectrum[lo:hi] ** 2))
        band_energy /= n_frames
        log_mel = np.log1p(band_energy)

        embedding = np.zeros(self.embedding_dim, dtype=np.float32)
        take = min(log_mel.size, self.embedding_dim)
        embedding[:take] = log_mel[:take]

        if take < self.embedding_dim:
            stats = np.array(
                [
                    float(np.mean(samples)),
                    float(np.std(samples)),
                    float(np.mean(np.abs(samples))),
                    float(np.mean(np.abs(np.diff(samples)))),
                ],
                dtype=np.float32,
            )
            room = self.embedding_dim - take
            embedding[take : take + min(stats.size, room)] = stats[: min(stats.size, room)]

        norm = float(np.linalg.norm(embedding))
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def _normalize(self, embedding: np.ndarray) -> np.ndarray:
        embedding = np.asarray(embedding, dtype=np.float32)
        if self.normalization == "l2":
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

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _pack(embedding: np.ndarray) -> bytes:
        return np.asarray(embedding, dtype=np.float32).tobytes()

    @staticmethod
    def _unpack(blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    def _get_identity(self, db, speaker_id: str, tenant_id: str, include_inactive: bool = False):
        query = db.query(_SpeakerIdentity).filter_by(
            speaker_id=speaker_id, tenant_id=tenant_id
        )
        if not include_inactive:
            query = query.filter(_SpeakerIdentity.is_active.is_(True))
        return query.first()

    # ------------------------------------------------------------------
    # Enrollment
    # ------------------------------------------------------------------
    def enroll(
        self,
        speaker_id: str,
        audio_window: np.ndarray,
        tenant_id: str = "default",
        display_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        speaker_id = (speaker_id or "").strip()
        if not speaker_id:
            raise ValueError("speaker_id is required for enrollment.")

        embedding = self._compute_embedding(audio_window)

        from app.db import models as db_models

        db = self._session_factory()
        try:
            # Look up including soft-deleted rows: the (tenant, speaker) unique
            # index means a re-enrollment must reactivate, not insert.
            identity = self._get_identity(db, speaker_id, tenant_id, include_inactive=True)
            created = identity is None
            if created:
                identity = db_models.SpeakerIdentity(
                    speaker_id=speaker_id,
                    tenant_id=tenant_id,
                    display_name=display_name,
                    model_identifier=self.model_identifier,
                    model_version=self.model_version,
                    normalization=self.normalization,
                    embedding_dimension=int(embedding.size),
                    centroid_embedding=self._pack(embedding),
                    enrollment_sample_count=1,
                    # _recompute_centroid bumps to 1 after the first sample.
                    enrollment_version=0,
                    is_active=True,
                )
                db.add(identity)
                db.flush()
            elif not identity.is_active:
                # Reactivating a revoked identity: start a fresh enrollment
                # under the CURRENT encoder (old samples are from a different
                # representation and must not pollute the new centroid).
                identity.is_active = True
                identity.deleted_at = None
                identity.display_name = display_name or identity.display_name
                identity.model_identifier = self.model_identifier
                identity.model_version = self.model_version
                identity.normalization = self.normalization
                identity.embedding_dimension = int(embedding.size)
                for old in identity.samples:
                    old.is_active = False
                db.flush()
            else:
                # Model provenance must stay coherent within one identity. An
                # enroll under a DIFFERENT encoder/version is treated as an
                # explicit fresh enrollment: old-representation samples are
                # deactivated so incompatible embedding spaces never mix.
                if (
                    identity.model_version != self.model_version
                    or identity.model_identifier != self.model_identifier
                    or identity.normalization != self.normalization
                    or identity.embedding_dimension != int(embedding.size)
                ):
                    identity.model_identifier = self.model_identifier
                    identity.model_version = self.model_version
                    identity.normalization = self.normalization
                    identity.embedding_dimension = int(embedding.size)
                    for old in identity.samples:
                        old.is_active = False
                    db.flush()

            db.add(
                db_models.SpeakerEnrollmentSample(
                    identity_id=identity.id,
                    embedding=self._pack(embedding),
                    embedding_dimension=int(embedding.size),
                    model_version=self.model_version,
                    rms=float(np.sqrt(np.mean(np.square(audio_window)))),
                    peak=float(np.max(np.abs(audio_window))),
                    is_active=True,
                )
            )
            db.flush()

            self._recompute_centroid(db, identity)
            db.commit()

            return {
                "speaker_id": speaker_id,
                "tenant_id": tenant_id,
                "embedding_dim": int(embedding.size),
                "sample_count": identity.enrollment_sample_count,
                "enrollment_version": identity.enrollment_version,
                "vault_size": self._active_vault_size(db, tenant_id),
                "match_threshold": self.match_threshold,
                "method": self._method,
                "model_version": self.model_version,
                "checkpoint_status": self._checkpoint_status,
                "enrolled": True,
            }
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _recompute_centroid(self, db, identity) -> None:
        samples = (
            db.query(_SpeakerEnrollmentSample)
            .filter_by(identity_id=identity.id, is_active=True)
            .order_by(_SpeakerEnrollmentSample.id.asc())
            .all()
        )
        # Prune beyond the retention bound (privacy: bounded biometric data).
        while len(samples) > self.max_samples:
            stale = samples.pop(0)
            stale.is_active = False

        if not samples:
            identity.centroid_embedding = b""
            identity.enrollment_sample_count = 0
            identity.enrollment_version += 1
            return

        if self.aggregation == "centroid":
            matrix = np.stack([self._unpack(s.embedding) for s in samples])
            centroid = matrix.mean(axis=0)
            centroid = self._normalize(centroid)
        else:  # newest-sample fallback (documented alternative)
            centroid = self._unpack(samples[-1].embedding)

        identity.centroid_embedding = self._pack(centroid)
        identity.enrollment_sample_count = len(samples)
        identity.enrollment_version += 1

    def _active_vault_size(self, db, tenant_id: str) -> int:
        return (
            db.query(_SpeakerIdentity)
            .filter_by(tenant_id=tenant_id, is_active=True)
            .count()
        )

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    def match(
        self,
        audio_window: np.ndarray,
        tenant_id: str = "default",
        speaker_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Verify a live window against enrolled identities.

        Returns similarity/threshold/matched/model_version. With no enrolled
        reference the similarity is None (identity evidence UNKNOWN/neutral),
        never 0.0 (which the fusion would read as a total mismatch).
        """
        try:
            embedding = self._compute_embedding(audio_window)
        except ValueError as exc:
            # Invalid audio (empty/silent): degrade rather than crash the call.
            return {
                "speaker_id": None,
                "speaker_match_score": None,
                "matched": False,
                "threshold": self.match_threshold,
                "model_version": self.model_version,
                "vault_size": self._vault_size_safe(tenant_id),
                "method": self._method,
                "checkpoint_status": self._checkpoint_status,
                "error": str(exc),
            }

        db = self._session_factory()
        try:
            query = db.query(_SpeakerIdentity).filter_by(tenant_id=tenant_id, is_active=True)
            if speaker_id:
                query = query.filter(_SpeakerIdentity.speaker_id == speaker_id)
            identities = query.all()

            if not identities:
                return {
                    "speaker_id": None,
                    "speaker_match_score": None,
                    "matched": False,
                    "threshold": self.match_threshold,
                    "model_version": self.model_version,
                    "vault_size": 0,
                    "method": self._method,
                    "checkpoint_status": self._checkpoint_status,
                }

            best_identity = None
            best_score = -1.0
            version_mismatch = False

            for identity in identities:
                comparable = (
                    identity.model_identifier == self.model_identifier
                    and identity.model_version == self.model_version
                    and identity.normalization == self.normalization
                    and identity.embedding_dimension == int(embedding.size)
                    and bool(identity.centroid_embedding)
                )
                if not comparable:
                    version_mismatch = True
                    continue
                score = self._cosine_similarity(
                    embedding, self._unpack(identity.centroid_embedding)
                )
                if score > best_score:
                    best_identity = identity
                    best_score = score

            if best_identity is None:
                # All candidates are from a different encoder/version: refuse
                # to invent a similarity across incompatible embedding spaces.
                return {
                    "speaker_id": None,
                    "speaker_match_score": None,
                    "matched": False,
                    "threshold": self.match_threshold,
                    "model_version": self.model_version,
                    "vault_size": len(identities),
                    "model_version_mismatch": True,
                    "method": self._method,
                    "checkpoint_status": self._checkpoint_status,
                }

            return {
                "speaker_id": best_identity.speaker_id,
                "speaker_match_score": round(float(best_score), 4),
                "matched": best_score >= self.match_threshold,
                "threshold": self.match_threshold,
                "model_version": self.model_version,
                "vault_size": len(identities),
                "method": self._method,
                "checkpoint_status": self._checkpoint_status,
                **({"model_version_mismatch": True} if version_mismatch else {}),
            }
        finally:
            db.close()

    def _vault_size_safe(self, tenant_id: str) -> int:
        db = self._session_factory()
        try:
            return self._active_vault_size(db, tenant_id)
        except Exception:
            return 0
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Revocation / deletion
    # ------------------------------------------------------------------
    def revoke(self, speaker_id: str, tenant_id: str = "default", hard: bool = False) -> bool:
        """Deactivate (default) or erase an enrollment. Returns True if found."""
        from app.db import models as db_models

        db = self._session_factory()
        try:
            identity = self._get_identity(db, speaker_id, tenant_id)
            if identity is None:
                return False
            if hard:
                db.delete(identity)
            else:
                identity.is_active = False
                identity.deleted_at = datetime.now(timezone.utc)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def restore(self, speaker_id: str, tenant_id: str = "default") -> bool:
        """Reactivate a soft-deleted enrollment."""
        db = self._session_factory()
        try:
            identity = self._get_identity(db, speaker_id, tenant_id, include_inactive=True)
            if identity is None:
                return False
            identity.is_active = True
            identity.deleted_at = None
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def list_speakers(self, tenant_id: str = "default") -> List[Dict[str, Any]]:
        """Metadata only — embeddings are NEVER included in listings."""
        db = self._session_factory()
        try:
            identities = (
                db.query(_SpeakerIdentity)
                .filter_by(tenant_id=tenant_id, is_active=True)
                .all()
            )
            return [
                {
                    "speaker_id": i.speaker_id,
                    "display_name": i.display_name,
                    "model_identifier": i.model_identifier,
                    "model_version": i.model_version,
                    "embedding_dimension": i.embedding_dimension,
                    "enrollment_sample_count": i.enrollment_sample_count,
                    "enrollment_version": i.enrollment_version,
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                    "updated_at": i.updated_at.isoformat() if i.updated_at else None,
                }
                for i in identities
            ]
        finally:
            db.close()

    # ------------------------------------------------------------------
    # State (telemetry; unchanged public contract)
    # ------------------------------------------------------------------
    def state(self, tenant_id: str = "default") -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "method": self._method,
            "checkpoint_status": self._checkpoint_status,
            "vault_size": self._vault_size_safe(tenant_id),
            "match_threshold": self.match_threshold,
            "embedding_dim": self._current_embedding_dimension(),
            "model_identifier": self.model_identifier,
            "model_version": self.model_version,
            "normalization": self.normalization,
            "persistence": "database",
        }


# Internal aliases so the vault body above stays readable; both point at the
# ORM models defined in app.db.models.
from app.db.models import SpeakerEnrollmentSample as _SpeakerEnrollmentSample  # noqa: E402
from app.db.models import SpeakerIdentity as _SpeakerIdentity  # noqa: E402


speaker_vault = SpeakerVault()


def get_speaker_vault() -> SpeakerVault:
    return speaker_vault
