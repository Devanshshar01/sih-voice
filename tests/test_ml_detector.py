"""Focused detector-contract checks that do not download model weights."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app.services.ml_detector import MockVoiceDetector, RealAntiSpoofDetector, get_detector
from app.services.intent_analyzer import IntentAnalyzer
from app.services.speaker_vault import SpeakerVault


def test_mock_detector_is_deterministic() -> None:
    detector = MockVoiceDetector()
    window = np.zeros(16000, dtype=np.float32)
    first = detector.predict(window)
    second = detector.predict(window)
    assert first == second
    assert first["details"]["mode"] == "mock"


def test_real_detector_is_lazy() -> None:
    detector = get_detector("real", model_id="Hemgg/Deepfake-audio-detection")
    assert isinstance(detector, RealAntiSpoofDetector)
    assert detector._model is None


def test_real_detector_ignores_mock_force_contract() -> None:
    detector = get_detector("real", model_id="Hemgg/Deepfake-audio-detection")
    assert not isinstance(detector, MockVoiceDetector)


def test_intent_analyzer_preserves_manual_transcript_path() -> None:
    analyzer = IntentAnalyzer()
    result = analyzer.analyze_text("Please approve the wire transfer immediately.")
    # Documented scoring: 0.5 + 0.15 per flagged phrase (2 here) + 0.05
    # amount bump is not applied (no amount). Matches the formula since the
    # phrase sets were introduced.
    assert result["intent_score"] == 0.8
    assert "wire transfer" in result["flagged_phrases"]
    assert "upi" in result["flagged_categories"]


def test_intent_analyzer_asr_is_lazy() -> None:
    analyzer = IntentAnalyzer(model_size="base")
    assert analyzer._model is None


def test_speaker_vault_enroll_and_match(tmp_path) -> None:
    """Persistent vault: isolated SQLite DB so the test never touches dev data."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.services.speaker_vault import SpeakerVault

    engine = create_engine(
        f"sqlite:///{tmp_path}/vault.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    vault = SpeakerVault(session_factory=TestSession)

    sample = np.zeros(16000, dtype=np.float32)
    sample[:8000] = 0.25
    sample[8000:] = -0.25

    enrollment = vault.enroll("demo-speaker", sample)

    assert enrollment["speaker_id"] == "demo-speaker"
    assert enrollment["embedding_dim"] > 0

    match = vault.match(sample)
    assert match["speaker_match_score"] >= 0.95
