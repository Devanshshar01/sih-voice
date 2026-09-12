"""Phase 2 risk-fusion tests (SIH multimodal inference alignment).

Deterministic, dependency-light. Verifies:
  * identity-risk direction (higher similarity can NEVER raise risk)
  * explicit fusion equation + contribution math
  * threshold transitions (ALLOW/WARN/LOCK_VERIFY)
  * hard transactional trigger (OTP/UPI/transfer)
  * missing speaker evidence (no vault reference) is neutral, not fraud
  * missing/failed ASR is neutral and does not crash fusion
  * detector exception -> degraded fusion, still safe
  * concurrent inference: parallel fan-out with failure isolation
  * risk monotonicity in every input dimension
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from app import config
from app.core import risk_engine
from app.core.parallel_inference import run_window_inference
from app.core.risk_engine import compute_risk, identity_mismatch


# ---------------------------------------------------------------------------
# 1. Identity risk direction (the core semantic fix)
# ---------------------------------------------------------------------------

def test_identity_mismatch_direction() -> None:
    # Perfect match -> zero identity risk. Zero similarity -> full mismatch.
    assert identity_mismatch(1.0) == 0.0
    assert identity_mismatch(0.9) == pytest.approx(0.1)
    assert identity_mismatch(0.0) == 1.0
    assert identity_mismatch(-0.5) == 1.0  # clamp: negative similarity = worst
    # Unknown identity is NEUTRAL, not fraud.
    assert identity_mismatch(None) == 0.0


def test_higher_similarity_never_raises_risk() -> None:
    base = dict(acoustic_score=0.2, intent_score=0.1, flagged_phrases=[])
    scores = [0.0, 0.2, 0.5, 0.75, 0.9, 0.98]  # ascending similarity
    risks = [compute_risk(speaker_similarity=s, **base)["risk_score"] for s in scores]
    for s_lower, s_higher, r_lower, r_higher in zip(scores, scores[1:], risks, risks[1:]):
        assert r_higher <= r_lower, (
            f"similarity {s_lower}->{s_higher} raised risk {r_lower}->{r_higher}"
        )


def test_similarity_1_0_is_strictly_less_risky_than_0_0() -> None:
    base = dict(acoustic_score=0.45, intent_score=0.2)
    r_match = compute_risk(speaker_similarity=1.0, **base)["risk_score"]
    r_mismatch = compute_risk(speaker_similarity=0.0, **base)["risk_score"]
    assert r_mismatch > r_match
    assert r_mismatch - r_match == pytest.approx(100 * config.RISK.IDENTITY_MISMATCH_WEIGHT)


def test_missing_reference_is_neutral_not_fraud() -> None:
    # Empty vault previously returned similarity 0.0 => mismatch 1.0 => every
    # genuine unenrolled call would hit LOCK_VERIFY. Regression guard:
    base = dict(acoustic_score=0.05, intent_score=0.05)
    r_unknown = compute_risk(speaker_similarity=None, **base)["risk_score"]
    r_known_match = compute_risk(speaker_similarity=1.0, **base)["risk_score"]
    assert r_unknown == r_known_match  # identical: identity evidence neutral
    assert r_unknown < config.RISK.WARN_THRESHOLD  # and the call stays ALLOW


def test_weights_sum_to_one() -> None:
    assert config.RISK.WEIGHT_SUM == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 2. Explicit fusion equation
# ---------------------------------------------------------------------------

def test_fusion_equation_matches_documented_formula() -> None:
    A, I, s = 0.8, 0.6, 0.3
    cfg = config.RISK
    expected = 100 * (cfg.ACOUSTIC_WEIGHT * A + cfg.INTENT_WEIGHT * I + cfg.IDENTITY_MISMATCH_WEIGHT * (1 - s))
    result = compute_risk(acoustic_score=A, intent_score=I, speaker_similarity=s)
    assert result["risk_score"] == int(expected)  # floor, no override fired
    assert result["fusion"]["contributions"]["acoustic"] == pytest.approx(100 * cfg.ACOUSTIC_WEIGHT * A, abs=0.02)
    assert result["fusion"]["contributions"]["intent"] == pytest.approx(100 * cfg.INTENT_WEIGHT * I, abs=0.02)
    assert result["fusion"]["contributions"]["identity_mismatch"] == pytest.approx(100 * cfg.IDENTITY_MISMATCH_WEIGHT * (1 - s), abs=0.02)


def test_speaker_score_field_is_similarity_not_risk() -> None:
    result = compute_risk(acoustic_score=0.1, intent_score=0.1, speaker_similarity=0.85)
    assert result["speaker_score"] == pytest.approx(0.85)  # raw similarity preserved
    assert result["identity_mismatch"] == pytest.approx(0.15)  # derived risk term


# ---------------------------------------------------------------------------
# 3. Threshold transitions
# ---------------------------------------------------------------------------

def test_threshold_transitions() -> None:
    warn = config.RISK.WARN_THRESHOLD
    lock = config.RISK.LOCK_VERIFY_THRESHOLD

    # ALLOW: below warn threshold.
    r_low = compute_risk(acoustic_score=0.0, intent_score=0.0, speaker_similarity=None)
    assert r_low["risk_score"] <= warn and r_low["status"] == "ALLOW"

    # Cross the WARN boundary: A=0.5 (30 pts) + I=0.5 (15 pts) = 45 > 40.
    r_warn = compute_risk(acoustic_score=0.5, intent_score=0.5, speaker_similarity=None)
    assert warn < r_warn["risk_score"] <= lock
    assert r_warn["status"] == "WARN"

    # Exactly at the WARN/LOCK boundary stays WARN; above it locks.
    at_boundary = compute_risk(
        acoustic_score=config.RISK.LOCK_VERIFY_THRESHOLD / 100.0,
        intent_score=0.0,
        speaker_similarity=None,
    )
    assert at_boundary["risk_score"] <= lock and at_boundary["status"] == "WARN"

    # LOCK: extreme evidence.
    r_lock = compute_risk(acoustic_score=1.0, intent_score=1.0, speaker_similarity=0.0)
    assert r_lock["status"] == "LOCK_VERIFY" and r_lock["risk_score"] >= lock


def test_status_monotone_in_score() -> None:
    prev_status_rank = -1
    rank = {"ALLOW": 0, "WARN": 1, "LOCK_VERIFY": 2}
    for a in np.linspace(0, 1, 21):
        result = compute_risk(acoustic_score=float(a), intent_score=0.1, speaker_similarity=0.5)
        assert rank[result["status"]] >= prev_status_rank
        prev_status_rank = rank[result["status"]]


# ---------------------------------------------------------------------------
# 4. Hard transactional trigger
# ---------------------------------------------------------------------------

def test_hard_trigger_forces_lock_verify() -> None:
    # Realistic analyzer output for an OTP phrase: intent >= 0.5.
    result = compute_risk(
        acoustic_score=0.02,
        intent_score=0.5,
        flagged_categories=["otp"],  # transactional trigger
        speaker_similarity=None,
    )
    assert result["hard_trigger"] is True
    assert result["status"] == "LOCK_VERIFY"
    assert result["risk_score"] > config.RISK.LOCK_VERIFY_THRESHOLD


def test_urgency_alone_does_not_hard_trigger() -> None:
    # Urgency phrases are weighted intent, not a transactional hard trigger.
    result = compute_risk(
        acoustic_score=0.02,
        intent_score=0.5,
        flagged_categories=["urgency"],
        speaker_similarity=None,
    )
    assert result["hard_trigger"] is False


def test_hard_trigger_respects_ambiguity_floor() -> None:
    # A stray fuzzy match on an otherwise-certain-genuine call must not lock.
    result = compute_risk(
        acoustic_score=0.0,
        intent_score=0.0,
        flagged_categories=["upi"],
        speaker_similarity=None,
    )
    assert result["hard_trigger"] is False  # max(A, I)=0 < HARD_TRIGGER_MIN_AMBIGUITY


def test_intent_analyzer_emits_categories_for_trigger() -> None:
    from app.services.intent_analyzer import IntentAnalyzer

    analyzer = IntentAnalyzer()
    result = analyzer.analyze_text("Share the OTP and do the UPI transfer right now.")
    assert "otp" in result["flagged_categories"]
    assert "upi" in result["flagged_categories"]

    genuine = analyzer.analyze_text("Confirming the quarterly expense numbers.")
    assert genuine["flagged_categories"] == []


# ---------------------------------------------------------------------------
# 5. Missing speaker / ASR evidence
# ---------------------------------------------------------------------------

def test_missing_asr_is_neutral() -> None:
    with_asr = compute_risk(acoustic_score=0.3, intent_score=0.2, speaker_similarity=None)
    without_asr = compute_risk(acoustic_score=0.3, intent_score=0.2, speaker_similarity=None, degraded={"asr": "timeout"})
    # Missing ASR only adds the documented degraded penalty, nothing else.
    assert without_asr["risk_score"] == pytest.approx(
        with_asr["risk_score"] + 100 * config.RISK.DEGRADED_FUSION_PENALTY
    )
    assert without_asr["degraded"] == {"asr": "timeout"}


def test_speaker_failure_degrades_neutrally() -> None:
    result = compute_risk(
        acoustic_score=0.3,
        intent_score=0.2,
        speaker_similarity=None,  # what a speaker-stage failure yields
        degraded={"speaker": "RuntimeError: model oom"},
    )
    assert result["identity_mismatch"] == 0.0  # neutral, not fraud
    assert result["status"] == "ALLOW"
    assert "speaker" in result["degraded"]


# ---------------------------------------------------------------------------
# 6. Detector exception handling
# ---------------------------------------------------------------------------

def test_detector_exception_yields_degraded_safe_state() -> None:
    """A raising detector must produce a degraded result, not a crash."""
    window = np.zeros(1000, dtype=np.float32)

    def broken_detector(_win):
        raise RuntimeError("CUDA OOM")

    async def scenario() -> tuple:
        return await run_window_inference(
            window,
            run_anti_spoof=broken_detector,
            run_asr=None,
            run_speaker=None,
        )

    acoustic, transcript, speaker, degraded = asyncio.run(scenario())
    assert degraded["anti_spoof"].startswith("RuntimeError")
    assert acoustic["acoustic_score"] == 0.5  # uninformative prior
    assert acoustic["details"]["mode"] == "degraded"
    assert speaker["speaker_match_score"] is None  # neutral identity

    # Fusion on degraded evidence stays computable and flags the degradation.
    result = compute_risk(
        acoustic_score=acoustic["acoustic_score"],
        intent_score=0.1,
        speaker_similarity=None,
        degraded=degraded,
    )
    assert "anti_spoof" in result["degraded"]
    assert 0 <= result["risk_score"] <= 100


def test_degraded_score_is_higher_than_clean_equivalent() -> None:
    clean = compute_risk(acoustic_score=0.5, intent_score=0.2, speaker_similarity=None)
    degraded = compute_risk(acoustic_score=0.5, intent_score=0.2, speaker_similarity=None, degraded={"anti_spoof": "boom"})
    assert degraded["risk_score"] > clean["risk_score"]


# ---------------------------------------------------------------------------
# 7. Concurrent inference behavior
# ---------------------------------------------------------------------------

def test_parallel_inference_runs_stages_concurrently() -> None:
    """Three ~200ms stages must overlap: wall clock < sum of stage times."""

    def slow_acoustic(_w):
        time.sleep(0.2)
        return {"acoustic_score": 0.1, "details": {"mode": "test"}}

    def slow_asr(_w):
        time.sleep(0.2)
        return "hello"

    def slow_speaker(_w):
        time.sleep(0.2)
        return {"speaker_id": "a", "speaker_match_score": 0.9, "matched": True, "vault_size": 1,
                "method": "test", "checkpoint_status": "test"}

    async def scenario():
        start = time.perf_counter()
        result = await run_window_inference(np.zeros(64), run_anti_spoof=slow_acoustic, run_asr=slow_asr, run_speaker=slow_speaker)
        return time.perf_counter() - start, result

    elapsed, (acoustic, transcript, speaker, degraded) = asyncio.run(scenario())
    assert elapsed < 0.55, f"stages ran serially: {elapsed:.2f}s >= 0.6s"
    assert transcript == "hello"
    assert speaker["speaker_match_score"] == pytest.approx(0.9)
    assert degraded == {}


def test_parallel_inference_isolates_stage_failures() -> None:
    def ok_acoustic(_w):
        return {"acoustic_score": 0.2, "details": {"mode": "test"}}

    def failing_asr(_w):
        raise ValueError("whisper exploded")

    def failing_speaker(_w):
        raise RuntimeError("ecapa unavailable")

    async def scenario():
        return await run_window_inference(np.zeros(64), run_anti_spoof=ok_acoustic, run_asr=failing_asr, run_speaker=failing_speaker)

    acoustic, transcript, speaker, degraded = asyncio.run(scenario())
    assert acoustic["acoustic_score"] == 0.2  # unaffected
    assert transcript is None
    assert speaker["speaker_match_score"] is None
    assert set(degraded) == {"asr", "speaker"}
    # ASR/speaker failures are captured, not raised — fusion can proceed.


def test_lane_serialization_per_model() -> None:
    """Two concurrent calls to the same lane must serialize (no GPU races)."""
    import threading

    active = 0
    max_active = 0
    lock = threading.Lock()

    def model(_w):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        return {"acoustic_score": 0.1, "details": {}}

    async def scenario():
        await asyncio.gather(*[
            run_window_inference(np.zeros(8), run_anti_spoof=model, run_asr=None, run_speaker=None)
            for _ in range(4)
        ])

    asyncio.run(scenario())
    assert max_active == 1, "anti-spoof lane allowed concurrent model invocations"


# ---------------------------------------------------------------------------
# 8. Risk monotonicity
# ---------------------------------------------------------------------------

def test_risk_monotone_in_all_inputs() -> None:
    prev = 0
    for a in np.linspace(0, 1, 11):
        r = compute_risk(acoustic_score=float(a), intent_score=0.2, speaker_similarity=0.5)["risk_score"]
        assert r >= prev
        prev = r

    prev = 0
    for i in np.linspace(0, 1, 11):
        r = compute_risk(acoustic_score=0.2, intent_score=float(i), speaker_similarity=0.5)["risk_score"]
        assert r >= prev
        prev = r

    # Identity: DECREASING similarity must never DECREASE risk.
    prev = 0
    for s in np.linspace(1, 0, 11):
        r = compute_risk(acoustic_score=0.2, intent_score=0.2, speaker_similarity=float(s))["risk_score"]
        assert r >= prev
        prev = r


def test_clamping_of_out_of_range_inputs() -> None:
    assert compute_risk(acoustic_score=5.0, intent_score=-2, speaker_similarity=7)["risk_score"] == \
        compute_risk(acoustic_score=1.0, intent_score=0.0, speaker_similarity=1.0)["risk_score"]


# ---------------------------------------------------------------------------
# Latency instrumentation
# ---------------------------------------------------------------------------

def test_latency_tracker_percentiles() -> None:
    from app.core.latency import LatencyStats, LatencyTracker

    stats = LatencyStats()
    for ms in (10, 20, 30, 40, 100):
        tracker = LatencyTracker()
        tracker.record("anti_spoof", ms)
        tracker.record("total", ms + 5)
        stats.record(tracker)
    snap = stats.snapshot()
    assert snap["anti_spoof"]["p50"] == pytest.approx(30.0)
    assert snap["anti_spoof"]["p95"] >= snap["anti_spoof"]["p50"]
    assert snap["anti_spoof"]["n"] == 5
