"""
Conversational intent analysis.

Phase 1 scans a provided transcript for urgency / financial / social-
engineering keyphrases -- fast, explainable, and safe to demo without any
ASR model wired in yet. Phase 2 can swap in a real intent classifier while
keeping the exact same return shape.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import numpy as np

from app.config import HIGH_RISK_KEYPHRASES


class IntentAnalyzer:
    MULTILINGUAL_PHRASE_SETS = {
        "en": {
            "otp": [
                "otp",
                "one time password",
                "one-time password",
                "otp code",
                "otp number",
            ],
            "upi": [
                "upi",
                "upi id",
                "upi address",
                "bank transfer",
                "wire transfer",
                "transfer money",
                "send money immediately",
                "account number",
                "routing number",
            ],
            "urgency": [
                "urgent",
                "act now",
                "immediately",
                "do it now",
                "right now",
                "don't tell anyone",
                "dont tell anyone",
            ],
        },
        "hi": {
            "otp": [
                "otp",
                "ओटीपी",
                "ओटीपी कोड",
                "ओटीपी नंबर",
                "otp ka code",
                "otp number",
                "otp btao",
                "otp batao",
            ],
            "upi": [
                "upi",
                "यूपीआई",
                "यूपीआई आईडी",
                "पेमेंट ट्रांसफर",
                "बैंक ट्रांसफर",
                "पैसे ट्रांसफर करें",
                "पैसे भेजें",
                "paisa bhejo",
                "paise transfer karo",
                "upi pin",
                "gpay",
                "phonepe",
            ],
            "urgency": [
                "तुरंत",
                "तुरंत करें",
                "जल्दी करें",
                "अभी करें",
                "ज्यादा समय न दें",
                "किसी को मत बताना",
                "digital arrest",
                "डिजिटल अरेस्ट",
                "police station",
                "पुलिस स्टेशन",
                "cbi officer",
                "सीबीआई अधिकारी",
                "account block",
                "खाता ब्लॉक",
                "kyc update",
                "urgent transfer karo",
            ],
        },
        "bn": {
            "otp": [
                "otp",
                "ওটিপি",
                "ওটিপি কোড",
                "ওটিপি নম্বর",
                "otp কোড",
                "otp bolun",
            ],
            "upi": [
                "upi",
                "ইউপিআই",
                "ইউপিআই আইডি",
                "টাকা পাঠান",
                "ব্যাংক ট্রান্সফার",
                "পেমেন্ট ট্রান্সফার",
                "taka pathan",
                "upi pin",
            ],
            "urgency": [
                "এখনই করুন",
                "তাৎক্ষণিক",
                "দ্রুত করুন",
                "কাউকে বলতে হবে না",
                "জরুরি",
                "ডিজিটাল অ্যারেস্ট",
                "পুলিশ স্টেশন",
                "সিবিআই অফিসার",
                "অ্যাকাউন্ট ব্লক",
                "কেওয়াইসি আপডেট",
                "digital arrest",
            ],
        },
        "mr": {
            "otp": [
                "otp",
                "ओटीपी",
                "ओटीपी कोड",
                "ओटीपी नंबर",
                "otp कोड",
                "otp sanga",
            ],
            "upi": [
                "upi",
                "यूपीआय",
                "यूपीआय आयडी",
                "पैसे पाठवा",
                "बँक ट्रान्सफर",
                "पेमेंट ट्रान्सफर",
                "paise pathva",
                "upi pin",
            ],
            "urgency": [
                "तत्काळ करा",
                "जल्दी करा",
                "आता करा",
                "कुणीला सांगू नको",
                "अत्यंत गरज",
                "डिजिटल अटक",
                "पोलीस स्टेशन",
                "सीबीआय अधिकारी",
                "खाते ब्लॉक",
                "केवायसी अपडेट",
                "digital arrest",
            ],
        },
        "ta": {
            "otp": [
                "otp",
                "ஓடிபி",
                "ஓடிபி குறியீடு",
                "ஓடிபி எண்",
                "otp code",
                "otp sollunga",
            ],
            "upi": [
                "upi",
                "யுபிஐ",
                "யுபிஐ ஐடி",
                "பணம் மாற்றவும்",
                "பேங்க் பரிமாற்றம்",
                "பணம் அனுப்பவும்",
                "panam anuppavum",
                "upi pin",
            ],
            "urgency": [
                "உடனே செய்யுங்கள்",
                "விரைவாக",
                "இப்போது செய்",
                "யாருக்கும் சொல்லாதே",
                "மிக அவசரம்",
                "டிஜிட்டல் கைது",
                "போலீஸ் நிலையம்",
                "சிபிஐ அதிகாரி",
                "கணக்கு முடக்கம்",
                "கேஒய்சி புதுப்பிப்பு",
                "digital arrest",
            ],
        },
        "te": {
            "otp": [
                "otp",
                "ఓటిపి",
                "ఓటిపి కోడ్",
                "ఓటిపి నంబర్",
                "otp కోడ్",
                "otp cheppandi",
            ],
            "upi": [
                "upi",
                "యుపీఐ",
                "యుపీఐ ఐడి",
                "డబ్బులు పంపండి",
                "బ్యాంక్ ట్రాన్స్ఫర్",
                "పేమెంట్ ట్రాన్స్ఫర్",
                "dabbulu pampandi",
                "upi pin",
            ],
            "urgency": [
                "ఇప్పుడే చేయండి",
                "త్వరగా",
                "అవసరం",
                "ఎవరికి చెప్పకండి",
                "అత్యవసర",
                "డిజిటల్ అరెస్ట్",
                "పోలీస్ స్టేషన్",
                "సిబిఐ అధికారి",
                "ఖాతా బ్లాక్",
                "కేవైసీ అప్‌డేట్",
                "digital arrest",
            ],
        },
    }

    def analyze_text(self, transcript: str) -> Dict[str, Any]:
        """
        Score a transcript chunk for urgency/financial social-engineering intent.

        The matcher now supports multilingual phrase families and uses a
        conservative fuzzy layer only when token overlap is strong enough to
        justify a low-risk paraphrase match. Because fuzzy matching can raise
        false positives on short, noisy phrases, the response explicitly
        surfaces that tradeoff via match_details.
        """
        text = transcript or ""
        normalized_text = self._normalize_text(text)

        exact_matches = self._find_exact_matches(normalized_text)
        fuzzy_matches = self._find_fuzzy_matches(normalized_text)

        flagged = self._dedupe_phrases(exact_matches + fuzzy_matches)

        if not flagged:
            score = 0.05
        else:
            score = min(1.0, 0.5 + 0.15 * len(flagged))

        return {
            "intent_score": score,
            "flagged_phrases": flagged,
            "match_details": {
                "exact_matches": exact_matches,
                "fuzzy_matches": fuzzy_matches,
                "fuzzy_tradeoff_note": (
                    "Fuzzy matching is intentionally conservative: it only runs "
                    "when there is strong token overlap with a known phrase family, "
                    "so short noisy utterances can still produce false positives. "
                    "Exact phrase hits remain the primary signal."
                ),
            },
        }

    def __init__(
        self,
        keyphrases: Optional[List[str]] = None,
        model_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        sample_rate: int = 16000,
    ):
        self.keyphrases = [
            kp.lower() for kp in (keyphrases or HIGH_RISK_KEYPHRASES)
        ]
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.sample_rate = sample_rate
        self._model = None
        self._phrase_catalog = self._build_phrase_catalog()

    def _build_phrase_catalog(self) -> List[Dict[str, Any]]:
        catalog: List[Dict[str, Any]] = []
        for language, phrase_sets in self.MULTILINGUAL_PHRASE_SETS.items():
            for category, variants in phrase_sets.items():
                for phrase in variants:
                    phrase = (phrase or "").strip()
                    if phrase:
                        catalog.append(
                            {
                                "language": language,
                                "category": category,
                                "phrase": phrase,
                                "normalized": self._normalize_text(phrase),
                            }
                        )
        return catalog

    def _find_exact_matches(self, normalized_text: str) -> List[str]:
        matches: List[str] = []
        for entry in self._phrase_catalog:
            if entry["normalized"] in normalized_text:
                matches.append(entry["phrase"])

        for keyphrase in self.keyphrases:
            if keyphrase in normalized_text and keyphrase not in matches:
                matches.append(keyphrase)

        return self._dedupe_phrases(matches)

    def _find_fuzzy_matches(self, normalized_text: str) -> List[str]:
        matches: List[str] = []
        normalized_tokens = set(normalized_text.split())

        for entry in self._phrase_catalog:
            if entry["normalized"] in normalized_text:
                continue

            phrase_tokens = entry["normalized"].split()
            if len(phrase_tokens) <= 1:
                continue

            token_overlap = len(set(phrase_tokens) & normalized_tokens) / len(phrase_tokens)
            sequence_ratio = SequenceMatcher(None, normalized_text, entry["normalized"]).ratio()

            if token_overlap >= 0.5 and sequence_ratio >= 0.72:
                matches.append(entry["phrase"])

        return self._dedupe_phrases(matches)

    @staticmethod
    def _dedupe_phrases(phrases: List[str]) -> List[str]:
        seen = set()
        deduped: List[str] = []
        for phrase in phrases:
            normalized_phrase = IntentAnalyzer._normalize_text(phrase)
            if normalized_phrase not in seen:
                seen.add(normalized_phrase)
                deduped.append(phrase)
        return deduped

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text or "")
        normalized = normalized.lower()
        normalized = normalized.replace("’", "'")
        normalized = re.sub(r"[^\w\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _ensure_model_loaded(self) -> None:
        """Load the faster-whisper model if it has not already been loaded."""
        if self._model is not None:
            return

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "ASR mode requires faster-whisper. Install requirements.txt "
                "before setting VOICETRUST_ASR_MODE=real."
            ) from exc

        try:
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not load faster-whisper model "
                f"'{self.model_size}': {exc}"
            ) from exc

    def transcribe(
        self,
        audio_window: np.ndarray,
        language: Optional[str] = None,
    ) -> str:
        """Transcribe one 16 kHz Float32 window when real ASR mode is enabled."""
        self._ensure_model_loaded()

        samples = np.asarray(audio_window, dtype=np.float32)

        if samples.size == 0:
            return ""

        segments, _info = self._model.transcribe(
            samples,
            language=language or None,
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )

        return " ".join(
            segment.text.strip() for segment in segments
        ).strip()