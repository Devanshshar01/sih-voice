"""Multilingual ASR/context subsystem tests (SIH six target languages).

Covers: Hindi, Tamil, Telugu, Bengali, Marathi, English — representative
phrases plus noisy/transliterated variants; Unicode/case normalization;
transliteration; speech-act false-positive control; missing transcript;
Whisper failure; unsupported language; and the WhisperModelManager loading
strategy.

All tests are deterministic and require no model downloads: the faster-
whisper tests exercise the failure/availability contract via stubbing, since
no checkpoint is downloaded in CI.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from app import config
from app.services import asr as asr_module
from app.services.asr import WhisperModelManager
from app.services.intent_analyzer import IntentAnalyzer


@pytest.fixture(scope="module")
def analyzer() -> IntentAnalyzer:
    return IntentAnalyzer()


# ---------------------------------------------------------------------------
# Language coverage: representative escalation phrases per target language
# ---------------------------------------------------------------------------

# (language, transcript, expected categories, request-context present)
MULTILINGUAL_ESCALATION_CASES = [
    # English (Indian English is represented as "en" in config)
    ("en", "Please share the OTP immediately.", {"otp", "urgency"}),
    ("en", "Send 50000 rupees to this account right now.", {"amount"}),
    ("en", "Do a UPI transfer of 2 lakh urgently.", {"upi", "amount", "urgency"}),
    # Hindi
    ("hi", "कृपया ओटीपी तुरंत बताइए।", {"otp", "urgency"}),
    ("hi", "पाँच हज़ार रुपये तुरंत ट्रांसफर करें।", {"upi", "urgency"}),
    # Tamil
    ("ta", "ஓடிபி எண்ணை உடனே சொல்லுங்கள்.", {"otp"}),
    ("ta", "பணம் அனுப்பவும், விரைவாக.", {"upi", "urgency"}),
    # Telugu
    ("te", "ఓటిపి నంబర్ చెప్పండి త్వరగా.", {"otp", "urgency"}),
    ("te", "డబ్బులు పంపండి ఇప్పుడే.", {"upi", "urgency"}),
    # Bengali
    ("bn", "ওটিপি কোড এখনই বলুন।", {"otp", "urgency"}),
    ("bn", "টাকা পাঠান দ্রুত করুন।", {"upi", "urgency"}),
    # Marathi
    ("mr", "ओटीपी कोड तत्काळ सांगा.", {"otp", "urgency"}),
    ("mr", "पैसे पाठवा आता करा.", {"upi", "urgency"}),
]


@pytest.mark.parametrize("lang,text,categories", MULTILINGUAL_ESCALATION_CASES)
def test_escalation_phrases_fire_per_language(analyzer, lang, text, categories) -> None:
    result = analyzer.analyze_text(text, language=lang)
    assert categories.issubset(set(result["flagged_categories"])), (
        f"{lang}: expected {categories} in {result['flagged_categories']} "
        f"(flagged={result['flagged_phrases']})"
    )
    assert result["intent_score"] > 0.05


@pytest.mark.parametrize(
    "lang,text,expected",
    [
        ("hi", "ओटीपी कोड", "otp"),
        ("ta", "யுபிஐ ஐடி", "upi"),
        ("te", "ఓటిపి", "otp"),
        ("bn", "ওটিপি কোড", "otp"),
        ("mr", "यूपीआय", "upi"),
    ],
)
def test_native_script_phrase_families_match(analyzer, lang, text, expected) -> None:
    result = analyzer.analyze_text(text, language=lang)
    assert expected in result["flagged_categories"]


def test_detected_language_reflects_script(analyzer) -> None:
    assert analyzer.analyze_text("जल्दी करें")["detected_language"] == "hi"
    assert analyzer.analyze_text("பணம் அனுப்பவும்")["detected_language"] == "ta"
    assert analyzer.analyze_text("డబ్బులు పంపండి")["detected_language"] == "te"
    assert analyzer.analyze_text("টাকা পাঠান")["detected_language"] == "bn"
    assert analyzer.analyze_text("तत्काळ करा")["detected_language"] == "hi"  # Devanagari shared
    assert analyzer.analyze_text("wire transfer")["detected_language"] == "en"


# ---------------------------------------------------------------------------
# Noisy / transliterated variants
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "lang,text,expected",
    [
        # Romanized (transliteration) variants
        ("hi", "otp bhejo jaldi", {"otp", "urgency"}),
        ("hi", "paisa bhejo turant", {"upi", "urgency"}),
        ("bn", "taka pathao ekhoni", {"upi"}),
        # Whisper-style noisy casing/punctuation
        ("en", "Please... SHARE the OTP code!! immediately,", {"otp", "urgency"}),
        ("en", "WIRE TRANSFER right NOW", {"upi", "urgency"}),
    ],
)
def test_noisy_and_transliterated_variants(analyzer, lang, text, expected) -> None:
    result = analyzer.analyze_text(text, language=lang)
    assert expected.issubset(set(result["flagged_categories"]))


def test_unicode_and_case_normalization(analyzer) -> None:
    # Full-width characters (NFKC), odd punctuation, mixed case.
    noisy = "ＯＴＰ ｃｏｄｅ…  ＢＡＴＡＯ jaldi!!!"
    result = analyzer.analyze_text(noisy)
    assert "otp" in result["flagged_categories"]


def test_transliteration_entries_are_labeled(analyzer) -> None:
    labels = [
        e["language"]
        for e in analyzer._phrase_catalog
        if e.get("transliterated")
    ]
    assert {"hi", "bn", "ta"}.issubset(set(labels))


# ---------------------------------------------------------------------------
# Contextual / rupee-amount evidence
# ---------------------------------------------------------------------------

def test_rupee_amount_detected(analyzer) -> None:
    result = analyzer.analyze_text("transfer ₹50,000 now", language="en")
    assert "amount" in result["flagged_categories"]
    risks = [r for r in result["intent_risks"] if r["category"] == "amount"]
    assert risks and "₹50,000" in risks[0]["matched_phrase"]


def test_lakh_crore_amounts_detected(analyzer) -> None:
    for text in ("2 lakh transfer karo", "send 5 crore rupees"):
        result = analyzer.analyze_text(text, language="en")
        assert "amount" in result["flagged_categories"], text


# ---------------------------------------------------------------------------
# False-positive control: mention vs request
# ---------------------------------------------------------------------------

def test_bare_otp_mention_does_not_score_as_transaction(analyzer) -> None:
    result = analyzer.analyze_text("I read about OTP scams in the news today.", language="en")
    assert result["intent_score"] < 0.5
    risks = result["intent_risks"]
    assert risks and all(r["speech_act"] == "mention" for r in risks)
    assert all(r["severity"] == "info" for r in risks)


def test_otp_with_request_marker_escalates_to_transaction(analyzer) -> None:
    result = analyzer.analyze_text("Share the OTP with me right now.", language="en")
    transaction = [r for r in result["intent_risks"] if r["category"] == "otp"]
    assert transaction
    assert transaction[0]["speech_act"] == "transaction"
    assert transaction[0]["severity"] == "critical"
    assert result["intent_score"] >= 0.5


def test_intent_risk_structure(analyzer) -> None:
    result = analyzer.analyze_text("Send the OTP immediately", language="en")
    assert result["intent_risks"]
    for risk in result["intent_risks"]:
        for key in ("category", "confidence", "evidence", "matched_phrase",
                    "language", "severity", "speech_act"):
            assert key in risk


def test_window_index_and_timestamp_attached(analyzer) -> None:
    result = analyzer.analyze_text("share the otp", language="en", window_index=7, timestamp=123.5)
    assert all(r.get("window_index") == 7 and r.get("timestamp") == 123.5 for r in result["intent_risks"])


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------

def test_missing_transcript_is_neutral(analyzer) -> None:
    result = analyzer.analyze_text("")
    assert result["intent_score"] == 0.05
    assert result["flagged_phrases"] == []
    assert result["intent_risks"] == []
    assert result["detected_language"] is None


def test_none_transcript_is_neutral(analyzer) -> None:
    assert analyzer.analyze_text(None)["intent_score"] == 0.05


def test_unsupported_language_hint_falls_back_to_full_catalog(analyzer) -> None:
    # An unknown hint must not crash or narrow matching: every phrase family
    # stays available (language hints steer telemetry, not availability).
    result = analyzer.analyze_text("share the otp immediately", language="xx")
    assert "otp" in result["flagged_categories"]


def test_sih_target_language_registry() -> None:
    assert set(config.SIH_TARGET_LANGUAGES) == {"en", "hi", "ta", "te", "bn", "mr"}


# ---------------------------------------------------------------------------
# WhisperModelManager: loading strategy + failure handling
# ---------------------------------------------------------------------------

def test_model_manager_is_lazy_and_singleton() -> None:
    manager = asr_module.get_whisper_manager()
    assert manager.loaded is False  # nothing loaded at import time
    assert asr_module.get_whisper_manager() is manager


def test_model_manager_reports_availability_honestly() -> None:
    manager = WhisperModelManager()
    available = manager.is_available()
    if not available:
        with pytest.raises(RuntimeError):
            manager.get_model()
        assert manager.load_error  # failure is recorded, not swallowed


def test_transcribe_failure_raises_in_manager_but_degrades_in_stream(monkeypatch) -> None:
    """Whisper failure: the manager raises (recorded), the stream WS degrades."""
    manager = WhisperModelManager()

    class _Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("checkpoint unavailable")

    monkeypatch.setattr(manager, "get_model", lambda: _Boom())
    audio = np.sin(np.linspace(0, 440 * 2 * np.pi, 16000)).astype(np.float32)

    # Manager contract: raise so the caller knows ASR is unavailable.
    with pytest.raises(RuntimeError):
        manager.transcribe(audio)

    # Stream contract: the WS lane catches and degrades to empty text.
    from app.api.v1 import stream as stream_module

    monkeypatch.setattr(
        stream_module.intent_analyzer,
        "transcribe_detailed",
        lambda w, language=None: (_ for _ in ()).throw(RuntimeError("checkpoint unavailable")),
    )
    text = stream_module._run_asr_blocking(audio)
    assert text == ""
    assert stream_module._run_asr_blocking.detected_language is None
    assert "checkpoint unavailable" in stream_module._run_asr_blocking.last_error


def test_empty_audio_short_circuits_without_model_load() -> None:
    manager = WhisperModelManager()
    # No get_model call: empty audio returns before any load attempt.
    text, detected = manager.transcribe(np.array([], dtype=np.float32))
    assert text == "" and detected is None
    assert manager.loaded is False


def test_intent_analyzer_transcribe_delegates_to_manager(monkeypatch) -> None:
    analyzer = IntentAnalyzer()
    calls = {}

    def fake_transcribe(audio, language=None):
        calls["language"] = language
        return "hello", "en"

    from app.services import asr
    monkeypatch.setattr(asr.get_whisper_manager(), "transcribe", fake_transcribe)
    text = analyzer.transcribe(np.zeros(16000, dtype=np.float32), language="en")
    assert text == "hello"
    assert calls["language"] == "en"
    assert analyzer._model is None  # legacy lazy attribute untouched
