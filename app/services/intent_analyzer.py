"""
Contextual intent analysis (SIH multilingual target languages).

Architecture:
  * Deterministic, explainable keyword rules over the six SIH target
    languages (English, Hindi, Tamil, Telugu, Bengali, Marathi) remain the
    safety net. The API is intentionally structured so a semantic intent
    classifier can be added later as an additional evidence provider without
    changing the downstream contract.
  * Every match becomes a structured ``IntentRisk`` object: category,
    confidence, evidence, matched phrase, language, severity — consumed by
    the risk engine's hard trigger and surfaced in dashboard telemetry.
  * Speech-act distinction (mention vs request vs instruction) controls
    false positives: merely MENTIONING "OTP" in a neutral sentence does not
    escalate the way an imperative REQUEST does. When the distinction cannot
    be made reliably, escalation stays conservative (side with safety) and
    the reasoning is recorded in the evidence.

"Indian English" is handled as "en" (the SIH presentation name) — we never
fabricate a language identifier the ASR model does not actually support.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import numpy as np

from app import config
from app.config import HIGH_RISK_KEYPHRASES

# Speech-act ladder (false-positive control):
#   mention     — the term appears but nothing asks the listener to act
#   request     — the caller asks the listener to do something with it
#   instruction — the caller directs a process (e.g. "share the OTP now")
#   transaction — explicit high-risk transactional ask (transfer/pay)
SPEECH_ACTS = ("mention", "request", "instruction", "transaction")

# Imperative/request markers per language. A category hit co-occurring with
# one of these in the same window escalates the speech act above "mention".
_REQUEST_MARKERS = {
    "en": ["send", "share", "give", "tell me", "read out", "confirm", "enter",
           "transfer", "pay", "process", "approve", "do it", "provide"],
    "hi": ["भेज", "बता", "दो", "दीजिए", "शेयर", "कन्फर्म", "पूछ", "ट्रांसफर",
           "भर", "डाल", "करें", "करो", "चाहिए"],
    "ta": ["அனுப்பு", "சொல்லு", "கொடு", "உறுதிப்படுத்து", "மாற்ற", "செலுத்த",
           "செய்யுங்கள்", "வேண்டும்"],
    "te": ["పంపు", "చెప్పండి", "ఇవ్వండి", "ధర్మలిస్తే", "ట్రాన్స్ఫర్", "చెల్లించు",
           "చేయండి", "కావాలి"],
    "bn": ["পাঠাও", "বলো", "দাও", "শেয়ার", "নিশ্চিত", "ট্রান্সফার", "দিন",
           "করুন", "দরকার"],
    "mr": ["पाठव", "सांग", "दे", "शेअर", "पुष्टी", "ट्रान्सफर", "भर",
           "करा", "हवं आहे"],
}

# rupee/amount pattern (digits, optionally lakh/crore words, ₹ symbol, or
# Devanagari/Tamil/Telugu/Bengali numeral context via the currency words).
_AMOUNT_PATTERN = re.compile(
    r"(?:₹\s?\d[\d,\.]*|rs\.?\s?\d[\d,\.]*|\d[\d,\.]{0,12}\s*(?:rupees?|rupaye|रुपये|रुपए|ரூபாய்|రూపాయలు|টাকা|रुपयं)|\d[\d,\.]{0,12}\s*(?:lakh|lac|crore|लाख|करोड़|லட்சம்|கோடி|లక్ష|కోట్ల|লক্ষ|কোটি))",
    re.IGNORECASE,
)


@dataclass
class IntentRisk:
    """One structured piece of contextual-risk evidence.

    ``language`` is the phrase-family language that matched (or the
    window's hint); ``window_index`` is set by the caller when known.
    """

    category: str          # otp | upi | amount | urgency
    confidence: float      # 0..1 — how strongly the evidence implies risk
    evidence: str          # human-readable explanation for the dashboard
    matched_phrase: str    # the actual phrase that fired
    language: str          # ISO code of the phrase family
    severity: str          # info | elevated | critical
    speech_act: str        # mention | request | instruction | transaction
    window_index: Optional[int] = None
    timestamp: Optional[float] = None
    span: Optional[Dict[str, int]] = field(default=None)  # char offsets in transcript

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "category": self.category,
            "confidence": round(self.confidence, 4),
            "evidence": self.evidence,
            "matched_phrase": self.matched_phrase,
            "language": self.language,
            "severity": self.severity,
            "speech_act": self.speech_act,
        }
        if self.window_index is not None:
            out["window_index"] = self.window_index
        if self.timestamp is not None:
            out["timestamp"] = self.timestamp
        if self.span is not None:
            out["span"] = self.span
        return out


class IntentAnalyzer:
    MULTILINGUAL_PHRASE_SETS = {
        "en": {
            "otp": [
                "otp",
                "one time password",
                "one-time password",
                "otp code",
                "otp number",
                "verification code",
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
            ],
            "upi": [
                "upi",
                "यूपीआई",
                "यूपीआई आईडी",
                "पेमेंट ट्रांसफर",
                "बैंक ट्रांसफर",
                "ट्रांसफर करें",
                "पैसे ट्रांसफर करें",
                "पैसे भेजें",
            ],
            "urgency": [
                "तुरंत",
                "तुरंत करें",
                "जल्दी करें",
                "अभी करें",
                "ज्यादा समय न दें",
                "किसी को मत बताना",
            ],
        },
        "bn": {
            "otp": [
                "otp",
                "ওটিপি",
                "ওটিপি কোড",
                "ওটিপি নম্বর",
                "otp কোড",
            ],
            "upi": [
                "upi",
                "ইউপিআই",
                "ইউপিআই আইডি",
                "টাকা পাঠান",
                "ব্যাংক ট্রান্সফার",
                "পেমেন্ট ট্রান্সফার",
            ],
            "urgency": [
                "এখনই",
                "এখনই করুন",
                "তাৎক্ষণিক",
                "দ্রুত করুন",
                "কাউকে বলতে হবে না",
                "জরুরি",
            ],
        },
        "mr": {
            "otp": [
                "otp",
                "ओटीपी",
                "ओटीपी कोड",
                "ओटीपी नंबर",
                "otp कोड",
            ],
            "upi": [
                "upi",
                "यूपीआय",
                "यूपीआय आयडी",
                "पैसे पाठवा",
                "बँक ट्रान्सफर",
                "पेमेंट ट्रान्सफर",
                "ट्रान्सफर करा",
            ],
            "urgency": [
                "तत्काळ",
                "तत्काळ करा",
                "जल्दी करा",
                "आता करा",
                "कुणीला सांगू नको",
                "अत्यंत गरज",
            ],
        },
        "ta": {
            "otp": [
                "otp",
                "ஓடிபி",
                "ஓடிபி குறியீடு",
                "ஓடிபி எண்",
                "otp code",
            ],
            "upi": [
                "upi",
                "யுபிஐ",
                "யுபிஐ ஐடி",
                "பணம் மாற்றவும்",
                "பேங்க் பரிமாற்றம்",
                "பணம் அனுப்பவும்",
            ],
            "urgency": [
                "உடனே செய்யுங்கள்",
                "விரைவாக",
                "இப்போது செய்",
                "யாருக்கும் சொல்லாதே",
                "மிக அவசரம்",
            ],
        },
        "te": {
            "otp": [
                "otp",
                "ఓటిపి",
                "ఓటిపి కోడ్",
                "ఓటిపి నంబర్",
                "otp కోడ్",
            ],
            "upi": [
                "upi",
                "యుపీఐ",
                "యుపీఐ ఐడి",
                "డబ్బులు పంపండి",
                "బ్యాంక్ ట్రాన్స్ఫర్",
                "పేమెంట్ ట్రాన్స్ఫర్",
            ],
            "urgency": [
                "ఇప్పుడే",
                "ఇప్పుడే చేయండి",
                "త్వరగా",
                "అవసరం",
                "ఎవరికి చెప్పకండి",
                "అత్యవసర",
            ],
        },
    }

    # Latin-script transliterations common in Hinglish and romanized Indic
    # texting (the transliteration layer the current system supports).
    TRANSLITERATION_PHRASE_SETS = {
        "hi": {
            "otp": ["otp bhejo", "otp ka code", "otp bol", "otp batado"],
            "upi": ["paisa bhejo", "paisa transfer karo", "jaldi paise bhejo", "upi id batao"],
            "urgency": ["jaldi", "jaldi karo", "turant", "turant karo", "abhi karo", "kisi ko mat batana"],
        },
        "bn": {
            "otp": ["otp pathao", "otp balo"],
            "upi": ["taka pathao", "taka transfer koro"],
            "urgency": ["ekhoni koro", "joldi koro"],
        },
        "ta": {
            "otp": ["otp anupu"],
            "upi": ["panam anupu"],
            "urgency": ["udane sei"],
        },
    }

    # Severity ladder per category (conservative defaults; a semantic
    # classifier can refine these later without changing call sites).
    CATEGORY_SEVERITY = {
        "otp": "critical",
        "upi": "critical",
        "amount": "elevated",
        "urgency": "elevated",
    }

    # Base confidence per category when the speech act is a real request/
    # instruction/transaction (mentions score lower — see below).
    CATEGORY_BASE_CONFIDENCE = {
        "otp": 0.85,
        "upi": 0.85,
        "amount": 0.55,
        "urgency": 0.5,
    }

    def __init__(
        self,
        keyphrases: Optional[List[str]] = None,
        model_size: str = "small",
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
        self._model = None  # legacy attribute kept for tests (lazy-loaded via manager)
        self._phrase_catalog = self._build_phrase_catalog()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze_text(
        self,
        transcript: str,
        language: Optional[str] = None,
        window_index: Optional[int] = None,
        timestamp: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Score a transcript chunk for social-engineering intent.

        Returns the legacy flat contract (``intent_score``,
        ``flagged_phrases``, ``flagged_categories``, ``match_details``)
        plus the new structured ``intent_risks`` list and
        ``detected_language`` telemetry.
        """
        text = transcript or ""
        normalized_text = self._normalize_text(text)

        exact_matches = self._find_exact_matches(normalized_text)
        fuzzy_matches = self._find_fuzzy_matches(normalized_text)
        flagged = self._dedupe_phrases(exact_matches + fuzzy_matches)

        # Map matched phrases back to semantic categories.
        categories: List[str] = []
        normalized_flagged = {self._normalize_text(p) for p in flagged}
        for entry in self._phrase_catalog:
            if entry["normalized"] in normalized_flagged and entry["category"] not in categories:
                categories.append(entry["category"])

        for keyphrase in self.keyphrases:
            if keyphrase in normalized_text and "urgency" not in categories:
                categories.append("urgency")

        # rupee/amount detection (any supported language, pattern-based).
        amount_hits = _AMOUNT_PATTERN.findall(text)
        if amount_hits and "amount" not in categories:
            categories.append("amount")

        # Structured evidence with speech-act control.
        intent_risks = self._build_intent_risks(
            normalized_text=normalized_text,
            flagged=flagged,
            categories=categories,
            amount_hits=amount_hits,
            language=language,
            window_index=window_index,
            timestamp=timestamp,
        )

        # Legacy score shape: 0.05 baseline, 0.5 + 0.15*n for matches. The
        # mention-level demotion keeps neutral mentions from scoring 0.5+.
        if not intent_risks:
            score = 0.05
        else:
            actioned = [r for r in intent_risks if r.speech_act != "mention"]
            if not actioned:
                # Mentions only: mild, explainable elevation — not a 0.5 hit.
                score = min(0.45, 0.15 + 0.1 * len(intent_risks))
            else:
                score = min(1.0, 0.5 + 0.15 * len(flagged))
                if any(r.category == "amount" for r in actioned) and score < 0.65:
                    score = min(1.0, score + 0.05)

        detected = self._detect_script_language(normalized_text, language)

        return {
            "intent_score": score,
            "flagged_phrases": flagged,
            "flagged_categories": categories,
            "intent_risks": [r.to_dict() for r in intent_risks],
            "detected_language": detected,
            "match_details": {
                "exact_matches": exact_matches,
                "fuzzy_matches": fuzzy_matches,
                "amount_matches": amount_hits,
                "speech_acts": sorted({r.speech_act for r in intent_risks}) or [],
                "fuzzy_tradeoff_note": (
                    "Fuzzy matching is intentionally conservative: it only runs "
                    "when there is strong token overlap with a known phrase family, "
                    "so short noisy utterances can still produce false positives. "
                    "Exact phrase hits remain the primary signal."
                ),
            },
        }

    # ------------------------------------------------------------------
    # Structured evidence construction
    # ------------------------------------------------------------------
    def _build_intent_risks(
        self,
        normalized_text: str,
        flagged: List[str],
        categories: List[str],
        amount_hits: List[str],
        language: Optional[str],
        window_index: Optional[int],
        timestamp: Optional[float],
    ) -> List[IntentRisk]:
        risks: List[IntentRisk] = []
        has_request_marker = any(
            marker in normalized_text
            for markers in _REQUEST_MARKERS.values()
            for marker in markers
        )

        def make_risk(category: str, phrase: str, phrase_lang: str) -> IntentRisk:
            if category in ("otp", "upi"):
                if has_request_marker:
                    # An actionable ask involving a transactional credential
                    # or payment rail: treat as high-risk transaction intent.
                    speech_act = "transaction"
                    confidence = self.CATEGORY_BASE_CONFIDENCE[category]
                else:
                    # Bare mention (e.g. "I got an OTP earlier"): conservative
                    # middle ground — stays below the hard-trigger floor but
                    # is recorded and explainable.
                    speech_act = "mention"
                    confidence = min(0.35, self.CATEGORY_BASE_CONFIDENCE[category] * 0.4)
            elif category == "amount":
                speech_act = "transaction" if has_request_marker else "mention"
                confidence = self.CATEGORY_BASE_CONFIDENCE["amount"]
            else:  # urgency
                speech_act = "request" if has_request_marker else "mention"
                confidence = self.CATEGORY_BASE_CONFIDENCE["urgency"]

            severity = (
                self.CATEGORY_SEVERITY[category]
                if speech_act != "mention"
                else "info"
            )
            evidence = (
                f"{category.upper()} phrase matched in a {speech_act} context "
                f"({phrase_lang}); request marker "
                f"{'present' if has_request_marker else 'absent'}."
            )
            return IntentRisk(
                category=category,
                confidence=confidence,
                evidence=evidence,
                matched_phrase=phrase,
                language=phrase_lang,
                severity=severity,
                speech_act=speech_act,
                window_index=window_index,
                timestamp=timestamp,
            )

        normalized_flagged = {self._normalize_text(p) for p in flagged}
        for entry in self._phrase_catalog:
            if entry["normalized"] in normalized_flagged:
                risks.append(make_risk(entry["category"], entry["phrase"], entry["language"]))

        for hit in amount_hits:
            risks.append(
                IntentRisk(
                    category="amount",
                    confidence=self.CATEGORY_BASE_CONFIDENCE["amount"],
                    evidence=f"Rupee/financial amount mentioned: '{hit.strip()}'.",
                    matched_phrase=hit.strip(),
                    language=language or "multi",
                    severity=self.CATEGORY_SEVERITY["amount"],
                    speech_act="transaction" if has_request_marker else "mention",
                    window_index=window_index,
                    timestamp=timestamp,
                )
            )

        # Dedupe by (category, phrase).
        seen = set()
        unique: List[IntentRisk] = []
        for r in risks:
            key = (r.category, r.matched_phrase.lower())
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique

    # ------------------------------------------------------------------
    # Catalog + matching
    # ------------------------------------------------------------------
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
        # Transliteration layer (romanized Indic texting variants).
        for language, phrase_sets in self.TRANSLITERATION_PHRASE_SETS.items():
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
                                "transliterated": True,
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

    _SCRIPT_RANGES = [
        ("hi", re.compile(r"[\u0900-\u097F]")),   # Devanagari (Hindi/Marathi)
        ("ta", re.compile(r"[\u0B80-\u0BFF]")),   # Tamil
        ("te", re.compile(r"[\u0C00-\u0C7F]")),   # Telugu
        ("bn", re.compile(r"[\u0980-\u09FF]")),   # Bengali
    ]

    @classmethod
    def _detect_script_language(cls, normalized_text: str, hint: Optional[str]) -> Optional[str]:
        """Best-effort detected-language telemetry (script + hint based)."""
        if hint and hint in config.SIH_TARGET_LANGUAGES:
            return hint
        for lang, pattern in cls._SCRIPT_RANGES:
            if pattern.search(normalized_text):
                return lang
        # Latin text: 'en' when non-empty, else None.
        return "en" if normalized_text.strip() else None

    # ------------------------------------------------------------------
    # ASR (delegates to the process-wide WhisperModelManager singleton)
    # ------------------------------------------------------------------
    def _ensure_model_loaded(self) -> None:
        """Kept for backward compatibility; loads via the singleton manager."""
        from app.services.asr import get_whisper_manager

        get_whisper_manager().get_model()

    def transcribe(
        self,
        audio_window: np.ndarray,
        language: Optional[str] = None,
    ) -> str:
        """Transcribe one 16 kHz float32 window (text only, legacy contract)."""
        text, _ = self.transcribe_detailed(audio_window, language=language)
        return text

    def transcribe_detailed(
        self,
        audio_window: np.ndarray,
        language: Optional[str] = None,
    ) -> tuple[str, Optional[str]]:
        """Transcribe and also return Whisper's detected language."""
        from app.services.asr import get_whisper_manager

        return get_whisper_manager().transcribe(audio_window, language=language)
