"""Persistent speaker identity vault tests (Phase: cross-session vault).

Covers: enrollment, multiple samples/centroid aggregation, DB persistence
across "restart" (new vault instance + fresh session factory over the same
database), verification, model-version mismatch, no enrolled identity,
threshold behavior, deletion/revocation, database restart, invalid audio,
and missing-ECAPA fallback behavior.

SpeechBrain is not installed in CI/test environments, so these tests
deterministically exercise the fallback encoder path — the persistence,
aggregation, and versioning logic is encoder-independent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.services.speaker_vault import SpeakerVault


# ---------------------------------------------------------------------------
# Fixtures: an isolated SQLite database + deterministic audio
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_url(tmp_path):
    return f"sqlite:///{tmp_path}/test_vault.db"


@pytest.fixture()
def make_vault(db_url):
    """Factory building SpeakerVault instances against the shared test DB.

    Calling it twice simulates an application restart: a brand-new vault and
    session factory, same persistent database.
    """
    engine = create_engine(
        db_url, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _make() -> SpeakerVault:
        return SpeakerVault(session_factory=TestSession)

    _make.engine = engine
    return _make


def _speech_like(seed: int, seconds: float = 4.0, freq: float = 180.0) -> np.ndarray:
    """Deterministic pseudo-speech signal (voiced fundamental + harmonics)."""
    rng = np.random.default_rng(seed)
    n = int(16000 * seconds)
    t = np.arange(n, dtype=np.float32) / 16000.0
    signal = (
        0.5 * np.sin(2 * np.pi * freq * t)
        + 0.25 * np.sin(2 * np.pi * 2 * freq * t)
        + 0.12 * np.sin(2 * np.pi * 3 * freq * t)
    )
    # Slow amplitude modulation emulates natural speech envelope.
    signal *= 0.6 + 0.4 * np.abs(np.sin(2 * np.pi * 2.5 * t))
    signal += 0.01 * rng.standard_normal(n).astype(np.float32)
    return signal.astype(np.float32)


# ---------------------------------------------------------------------------
# Enrollment
# ---------------------------------------------------------------------------

def test_enroll_creates_identity_and_returns_metadata(make_vault) -> None:
    vault = make_vault()
    result = vault.enroll("alice", _speech_like(1))

    assert result["enrolled"] is True
    assert result["speaker_id"] == "alice"
    assert result["sample_count"] == 1
    assert result["enrollment_version"] == 1
    assert result["model_version"] == vault.model_version
    assert result["embedding_dim"] > 0
    assert result["method"] == "deterministic-fallback"  # honest about encoder


def test_enroll_requires_speaker_id(make_vault) -> None:
    vault = make_vault()
    with pytest.raises(ValueError):
        vault.enroll("   ", _speech_like(1))


def test_enroll_rejects_invalid_audio(make_vault) -> None:
    vault = make_vault()
    with pytest.raises(ValueError):
        vault.enroll("alice", np.array([], dtype=np.float32))


def test_multiple_samples_update_centroid_not_replace(make_vault) -> None:
    vault = make_vault()
    r1 = vault.enroll("bob", _speech_like(2, freq=170.0))
    assert r1["sample_count"] == 1

    r2 = vault.enroll("bob", _speech_like(3, freq=175.0))
    assert r2["sample_count"] == 2
    assert r2["enrollment_version"] == 2  # representation was re-derived


def test_sample_retention_bound_is_enforced(make_vault, monkeypatch) -> None:
    monkeypatch.setattr("app.config.SPEAKER_MAX_ENROLLMENT_SAMPLES", 3)
    vault = make_vault()
    for seed in range(6):
        vault.enroll("carol", _speech_like(seed))
    assert vault.state()["vault_size"] == 1

    from app.db.database import Base  # inspect via a fresh session
    import sqlalchemy as sa
    engine = make_vault.engine
    with sa.orm.Session(bind=engine) as s:
        from app.db.models import SpeakerIdentity
        identity = s.query(SpeakerIdentity).filter_by(speaker_id="carol").one()
        active = [x for x in identity.samples if x.is_active]
        assert len(active) <= 3
        assert identity.enrollment_sample_count == len(active)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def test_verify_matches_enrolled_speaker(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1, freq=180.0))

    result = vault.match(_speech_like(20, freq=180.0))
    assert result["speaker_id"] == "alice"
    assert result["speaker_match_score"] is not None
    assert result["matched"] is True
    assert result["model_version"] == vault.model_version
    assert result["threshold"] == vault.match_threshold


def test_verify_returns_contract_fields(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))
    result = vault.match(_speech_like(1))
    for key in ("speaker_id", "speaker_match_score", "matched", "threshold", "model_version"):
        assert key in result


def test_no_enrolled_identity_is_neutral_not_mismatch(make_vault) -> None:
    vault = make_vault()
    result = vault.match(_speech_like(5))

    assert result["speaker_id"] is None
    assert result["speaker_match_score"] is None
    assert result["matched"] is False
    assert result["vault_size"] == 0


def test_impostor_speaker_scores_below_match(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1, freq=180.0))

    # An impostor with a completely different spectral profile: broadband
    # noise (the fallback encoder is spectral, so a harmonic tone — even a
    # far-away fundamental — retains overlap; noise does not).
    rng = np.random.default_rng(999)
    impostor_audio = (0.3 * rng.standard_normal(16000 * 4)).astype(np.float32)
    result = vault.match(impostor_audio)
    assert result["matched"] is False
    assert result["speaker_match_score"] < vault.match_threshold


def test_threshold_behavior_is_monotonic(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))
    score = vault.match(_speech_like(1))["speaker_match_score"]

    assert vault.match_threshold > 0
    # Same audio re-embedded must reproduce the same decision boundary check.
    assert (score >= vault.match_threshold) == vault.match(_speech_like(1))["matched"]


def test_invalid_audio_at_verification_degrades_not_crashes(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))
    result = vault.match(np.array([], dtype=np.float32))

    assert result["matched"] is False
    assert result["speaker_match_score"] is None
    assert "error" in result


# ---------------------------------------------------------------------------
# Persistence / cross-session
# ---------------------------------------------------------------------------

def test_cross_session_enroll_restart_verify(make_vault) -> None:
    """THE critical SIH requirement: enroll, 'restart' the app, still match."""
    # Session 1: enroll.
    vault_a = make_vault()
    vault_a.enroll("alice", _speech_like(1, freq=180.0))
    vault_a.enroll("alice", _speech_like(2, freq=182.0))
    del vault_a

    # Session 2: a completely new vault instance over the same database.
    vault_b = make_vault()
    assert vault_b.state()["vault_size"] == 1
    result = vault_b.match(_speech_like(20, freq=180.0))
    assert result["speaker_id"] == "alice"
    assert result["matched"] is True


def test_database_restart_preserves_metadata(make_vault) -> None:
    vault_a = make_vault()
    r = vault_a.enroll("bob", _speech_like(3))
    del vault_a

    vault_b = make_vault()
    speakers = vault_b.list_speakers()
    assert len(speakers) == 1
    assert speakers[0]["speaker_id"] == "bob"
    assert speakers[0]["enrollment_sample_count"] == r["sample_count"]
    # Embeddings are never part of the listing.
    assert "embedding" not in speakers[0]
    assert "centroid" not in speakers[0]


# ---------------------------------------------------------------------------
# Model-version gating
# ---------------------------------------------------------------------------

def test_model_version_mismatch_blocks_comparison(make_vault) -> None:
    vault_a = make_vault()
    vault_a.enroll("alice", _speech_like(1))
    del vault_a

    # "Upgrade" the runtime encoder: new version, different dimension.
    vault_b = make_vault()
    vault_b.model_version = "ecapa-voxceleb-v2"
    result = vault_b.match(_speech_like(1))

    assert result["speaker_match_score"] is None
    assert result["matched"] is False
    assert result.get("model_version_mismatch") is True


def test_reenroll_after_version_change_starts_fresh(make_vault) -> None:
    vault_a = make_vault()
    vault_a.enroll("alice", _speech_like(1))
    del vault_a

    # An enrollment under a new encoder version starts a fresh representation
    # (old-version samples are deactivated, never mixed across spaces).
    vault_b = make_vault()
    vault_b.model_version = "ecapa-voxceleb-v2"
    r = vault_b.enroll("alice", _speech_like(1))
    assert r["sample_count"] == 1
    assert vault_b.match(_speech_like(1))["matched"] is True


# ---------------------------------------------------------------------------
# Deletion / revocation
# ---------------------------------------------------------------------------

def test_revoke_soft_deletes_and_stops_matching(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))

    assert vault.revoke("alice") is True
    assert vault.state()["vault_size"] == 0

    # After revocation the caller is UNENROLLED: identity neutral, not fraud.
    result = vault.match(_speech_like(1))
    assert result["speaker_id"] is None
    assert result["speaker_match_score"] is None


def test_hard_delete_removes_rows(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))
    assert vault.revoke("alice", hard=True) is True
    assert vault.list_speakers() == []

    import sqlalchemy as sa
    from app.db.models import SpeakerIdentity, SpeakerEnrollmentSample
    with sa.orm.Session(bind=make_vault.engine) as s:
        assert s.query(SpeakerIdentity).count() == 0
        assert s.query(SpeakerEnrollmentSample).count() == 0


def test_restore_reactivates_revoked_identity(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))
    vault.revoke("alice")
    assert vault.restore("alice") is True
    assert vault.match(_speech_like(1))["matched"] is True


def test_revoke_unknown_speaker_returns_false(make_vault) -> None:
    assert make_vault().revoke("nobody") is False


# ---------------------------------------------------------------------------
# Privacy properties
# ---------------------------------------------------------------------------

def test_listings_and_state_never_expose_embeddings(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))

    for speaker in vault.list_speakers():
        assert "embedding" not in speaker and "centroid" not in speaker
    state = vault.state()
    assert "embedding" not in state and "centroid" not in state
    match = vault.match(_speech_like(1))
    assert "embedding" not in match and "centroid" not in match


def test_embeddings_are_l2_normalized_in_db(make_vault) -> None:
    vault = make_vault()
    vault.enroll("alice", _speech_like(1))

    import sqlalchemy as sa
    from app.db.models import SpeakerEnrollmentSample
    with sa.orm.Session(bind=make_vault.engine) as s:
        sample = s.query(SpeakerEnrollmentSample).first()
        vec = np.frombuffer(sample.embedding, dtype=np.float32)
        assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-5
