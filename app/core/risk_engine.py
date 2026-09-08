"""
Hybrid risk engine: fuses the acoustic and intent scores into a single 0-100
composite SatyaVoice risk score and maps it to a policy decision.

    R_total = min(100, floor(w_a * R_acoustic + w_i * R_intent))

with w_a = 0.55, w_i = 0.45 (see app.config). If high-risk financial
keyphrases are detected, intent is overridden to 1.0 so a genuinely urgent
fraud attempt can't be diluted by a calm-sounding acoustic score.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.config import RiskStatus


def compute_risk(
    acoustic_score: float,
    intent_score: float,
    flagged_phrases: Optional[List[str]] = None,
) -> Dict[str, Any]:
    flagged_phrases = flagged_phrases or []

    effective_intent = 1.0 if flagged_phrases else intent_score

    raw = (config.ACOUSTIC_WEIGHT * acoustic_score * 100) + (
        config.INTENT_WEIGHT * effective_intent * 100
    )
    risk_score = min(100, math.floor(raw))

    status, rationale = _classify(risk_score, acoustic_score, flagged_phrases)

    return {
        "risk_score": risk_score,
        "acoustic_score": round(acoustic_score, 4),
        "intent_score": round(effective_intent, 4),
        "status": status,
        "rationale": rationale,
    }


def _classify(
    risk_score: int, acoustic_score: float, flagged_phrases: List[str]
) -> Tuple[str, List[str]]:
    rationale: List[str] = []

    if risk_score <= config.RISK_LOW_MAX:
        status = RiskStatus.ALLOW
        rationale.append("Acoustic and conversational signals within normal range.")
    elif risk_score <= config.RISK_MEDIUM_MAX:
        status = RiskStatus.WARN
        if acoustic_score > 0.4:
            rationale.append(f"Acoustic synthesis vector elevated ({acoustic_score:.0%}).")
        if flagged_phrases:
            rationale.append(f"Urgency phrases detected: {', '.join(flagged_phrases)}.")
    else:
        status = RiskStatus.LOCK_VERIFY
        rationale.append(f"Acoustic synthesis vector high ({acoustic_score:.0%}).")
        if flagged_phrases:
            rationale.append(
                f"Urgent financial request vector high: {', '.join(flagged_phrases)}."
            )
        rationale.append("Sensitive workflow controls locked pending out-of-band verification.")

    return status, rationale
