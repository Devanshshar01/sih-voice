"""
Conversational intent analysis.

Phase 1 scans a provided transcript for urgency / financial / social-
engineering keyphrases -- fast, explainable, and safe to demo without any
ASR model wired in yet. Phase 2 can swap in a real intent classifier while
keeping the exact same return shape.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import HIGH_RISK_KEYPHRASES


class IntentAnalyzer:
    def __init__(self, keyphrases: Optional[List[str]] = None):
        self.keyphrases = [kp.lower() for kp in (keyphrases or HIGH_RISK_KEYPHRASES)]

    def analyze_text(self, transcript: str) -> Dict[str, Any]:
        """
        Score a transcript chunk for urgency/financial social-engineering intent.
        """
        text = (transcript or "").lower()
        flagged = [kp for kp in self.keyphrases if kp in text]

        if not flagged:
            score = 0.05
        else:
            # A single strong hit already dominates the score, matching the
            # blueprint's "intent override" behaviour for financial urgency;
            # additional matches push it further toward 1.0.
            score = min(1.0, 0.5 + 0.15 * len(flagged))

        return {"intent_score": score, "flagged_phrases": flagged}

    def transcribe(self, audio_window) -> str:
        """
        Placeholder transcription hook. Phase 1 ships without a live ASR
        model -- callers pass a transcript directly (e.g. from a browser-side
        Web Speech API) into analyze_text(). Wire in a local Whisper model
        here for Phase 2 if GPU hardware becomes available.
        """
        raise NotImplementedError(
            "No ASR backend configured. Pass a transcript to analyze_text() "
            "directly, or wire a transcription model in here."
        )
