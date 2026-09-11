"""
Risk fusion engine (SIH Phase 2: mathematically explicit).

Fused equation (all weights from app.config.RISK — single source of truth):

    R_total = 100 * (Wa*A + Wi*I + Wm*M)          [convex: Wa+Wi+Wm = 1.0]
    M       = max(0, 1 - s)   identity mismatch, where
              s = speaker_similarity vs the enrolled reference,
              and M = 0 (neutral) when no reference exists (s unknown).
    I       = effective intent score; 1.0 if a hard transactional trigger
              fires (OTP/UPI/transfer phrase families) and fusion config
              enables the override.
    hard trigger: if enabled, fired, and max(A, I) >= HARD_TRIGGER_MIN_AMBIGUITY,
              R_total is forced to 100 (LOCK_VERIFY).

Policy mapping:
    ALLOW       if R_total <= WARN_THRESHOLD        (default 40)
    WARN        if WARN_THRESHOLD < R <= LOCK_THRESHOLD (default 70)
    LOCK_VERIFY if R_total > LOCK_THRESHOLD

Directional contract (verified by tests):
    * higher acoustic score      -> risk never decreases
    * higher intent score        -> risk never decreases
    * HIGHER speaker similarity  -> risk never INCREASES
      (identity consistency can only reduce or leave risk unchanged)
    * identity evidence is neutral when the vault has no reference

Degradation contract: a model that fails is replaced by its degraded value
(acoustic 0.5 = uninformative, identity 0 mismatch neutral, intent unchanged
since text analysis cannot "fail" silently) and the returned dict flags
`degraded: {stage: reason}`. Risk is still computed from whatever evidence
is available — never silently assuming the best case.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from app import config
from app.config import RiskStatus

# Uninformative placeholder used when the anti-spoof model fails: the prior
# of the detector, i.e. "no evidence either way". Configurable for symmetry
# with the degraded-fusion penalty.
_DEGRADED_ACOUSTIC = 0.5


def identity_mismatch(speaker_similarity: Optional[float]) -> float:
    """Convert a speaker similarity into an identity-RISK term.

    Direction: higher similarity -> LOWER mismatch risk.
    None (no reference / unknown identity) -> 0.0 (neutral, not fraud).
    """
    if speaker_similarity is None:
        return 0.0
    try:
        s = float(speaker_similarity)
    except (TypeError, ValueError):
        return 0.0
    s = max(0.0, min(1.0, s))
    return max(0.0, 1.0 - s)


def _classify(risk_score: int) -> str:
    if risk_score <= config.RISK.WARN_THRESHOLD:
        return RiskStatus.ALLOW
    if risk_score <= config.RISK.LOCK_VERIFY_THRESHOLD:
        return RiskStatus.WARN
    return RiskStatus.LOCK_VERIFY


def compute_risk(
    acoustic_score: float,
    intent_score: float,
    flagged_phrases: Optional[List[str]] = None,
    speaker_similarity: Optional[float] = None,
    flagged_categories: Optional[List[str]] = None,
    degraded: Optional[Dict[str, str]] = None,
    intent_details: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fuse acoustic, intent, and identity evidence into a policy decision.

    Parameters named for their semantics (not for the model that produced
    them): `speaker_similarity` is the cosine match against the enrolled
    caller reference; identity risk is derived internally via
    `identity_mismatch` so the direction can never be accidentally inverted
    by a call site.
    """
    flagged_phrases = flagged_phrases or []
    flagged_categories = flagged_categories or []
    degraded = degraded or {}
    cfg = config.RISK

    A = max(0.0, min(1.0, float(acoustic_score)))
    I = max(0.0, min(1.0, float(intent_score)))
    M = identity_mismatch(speaker_similarity)

    # --- Hard transactional trigger -------------------------------------
    hard_trigger = False
    if (
        cfg.HARD_TRIGGER_ENABLED
        and any(cat in config.HARD_TRIGGER_CATEGORIES for cat in flagged_categories)
        and max(A, I) >= cfg.HARD_TRIGGER_MIN_AMBIGUITY
    ):
        I = 1.0
        hard_trigger = True

    raw = 100.0 * (cfg.ACOUSTIC_WEIGHT * A + cfg.INTENT_WEIGHT * I + cfg.IDENTITY_MISMATCH_WEIGHT * M)

    # --- Degraded-evidence handling --------------------------------------
    if degraded:
        raw += 100.0 * cfg.DEGRADED_FUSION_PENALTY * len(degraded)

    risk_score = min(100, math.floor(raw))
    status = _classify(risk_score)

    # Safety floor: a hard trigger must never land below LOCK_VERIFY.
    if hard_trigger:
        status = RiskStatus.LOCK_VERIFY
        risk_score = max(risk_score, cfg.LOCK_VERIFY_THRESHOLD + 1)

    rationale = _build_rationale(
        status=status,
        acoustic=A,
        intent=I,
        identity_mismatch=M,
        flagged_phrases=flagged_phrases,
        hard_trigger=hard_trigger,
        degraded=degraded,
    )

    return {
        "risk_score": risk_score,
        "status": status,
        # Component evidence (all in [0,1], semantics unambiguous):
        "acoustic_score": round(A, 4),
        "intent_score": round(I, 4),
        # Kept for backward compatibility with existing consumers: this is
        # the raw SIMILARITY, not a risk term.
        "speaker_score": round(speaker_similarity, 4) if speaker_similarity is not None else None,
        "identity_mismatch": round(M, 4),
        "hard_trigger": hard_trigger,
        "degraded": degraded,
        "fusion": {
            "weights": {
                "acoustic": cfg.ACOUSTIC_WEIGHT,
                "intent": cfg.INTENT_WEIGHT,
                "identity_mismatch": cfg.IDENTITY_MISMATCH_WEIGHT,
            },
            "contributions": {
                "acoustic": round(100 * cfg.ACOUSTIC_WEIGHT * A, 2),
                "intent": round(100 * cfg.INTENT_WEIGHT * I, 2),
                "identity_mismatch": round(100 * cfg.IDENTITY_MISMATCH_WEIGHT * M, 2),
            },
            "raw_score": round(raw, 2),
        },
        "rationale": rationale,
        **({"intent_details": intent_details} if intent_details else {}),
    }


def _build_rationale(
    status: str,
    acoustic: float,
    intent: float,
    identity_mismatch: float,
    flagged_phrases: List[str],
    hard_trigger: bool,
    degraded: Dict[str, str],
) -> List[str]:
    rationale: List[str] = []
    if hard_trigger:
        rationale.append(
            "Hard transactional trigger: OTP/UPI/transfer request detected — escalation enforced."
        )
    if degraded:
        stages = ", ".join(sorted(degraded))
        rationale.append(f"Degraded evidence (model failure): {stages}.")
    if identity_mismatch > 0:
        rationale.append(
            f"Caller identity does not match the enrolled reference "
            f"(mismatch {identity_mismatch:.0%})."
        )
    elif identity_mismatch == 0.0 and status != RiskStatus.ALLOW:
        rationale.append("No enrolled reference for this caller; identity evidence neutral.")

    if status == RiskStatus.ALLOW:
        if not rationale:
            rationale.append("Acoustic and conversational signals within normal range.")
    elif status == RiskStatus.WARN:
        if acoustic > 0.4:
            rationale.append(f"Acoustic synthesis vector elevated ({acoustic:.0%}).")
        if flagged_phrases:
            rationale.append(f"Urgency phrases detected: {', '.join(flagged_phrases)}.")
    else:  # LOCK_VERIFY
        if acoustic > 0.4:
            rationale.append(f"Acoustic synthesis vector high ({acoustic:.0%}).")
        if flagged_phrases:
            rationale.append(
                f"Urgent financial request vector high: {', '.join(flagged_phrases)}."
            )
        rationale.append("Sensitive workflow controls locked pending out-of-band verification.")

    return rationale
