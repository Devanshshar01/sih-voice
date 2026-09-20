"""Remote anti-spoof cadence: single-flight, safe reuse, honest degradation.

Regression coverage for the cadence defect: the stream emits a 4-second window
every 0.5 s while one remote MMS inference costs ~8 s on ZeroGPU, so a request
per window backlogs the ring buffer and scores audio that is already stale.

Requirements asserted here:
  * at most ONE remote inference in flight per call/session
  * audio windows keep resolving (0.5 s hop preserved) during inference
  * the retained result is reused as `stale` while a newer inference is pending
  * it expires to `unavailable` past the bounded age
  * provider failure never yields a synthetic score (no 0.0/0.5)
  * the quota circuit breaker stops new GPU requests immediately
  * session shutdown with an inference in flight stops all further scheduling
  * the cadence is configurable by environment variable
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before app imports: the streaming module builds a detector at
# import time and requires these settings.
os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-acoustic-cadence")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

from app.core.parallel_inference import run_window_inference
from app.services.acoustic_evidence import (
    STATUS_FRESH,
    STATUS_STALE,
    STATUS_UNAVAILABLE,
    AcousticEvidenceScheduler,
)

WINDOW = np.zeros(16000, dtype=np.float32)  # 1 s is enough for the states under test


class _Clock:
    """Deterministic monotonic clock: cadence tests must not depend on sleeps."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _success(score: float = 0.42, latency_ms: float = 8000.0) -> dict:
    return {
        "acoustic_score": score,
        "success": True,
        "inference_available": True,
        "detector_status": "ok",
        "details": {"mode": "zerogpu", "inference_time_ms": latency_ms},
    }


def _provider_failure(reason: str = "Failed to call ZeroGPU Space: connection reset") -> dict:
    """Exactly what ZeroGPUVoiceDetectorAdapter returns on provider failure."""
    return {
        "acoustic_score": None,
        "success": False,
        "inference_available": False,
        "detector_status": "unavailable",
        "error_code": "INFERENCE_UNAVAILABLE",
        "error_message": reason,
        "details": {"mode": "zerogpu", "status": "unavailable"},
    }


class _Inference:
    """Records remote calls; can be held open to simulate a slow MMS request."""

    def __init__(self, results: list | None = None) -> None:
        self.calls = 0
        self.peak_in_flight = 0
        self.windows: list = []
        self._in_flight = 0
        self._results = list(results or [])
        self._gate: asyncio.Event | None = None

    @property
    def in_flight(self) -> int:
        return self._in_flight

    def block(self) -> None:
        self._gate = asyncio.Event()

    def release(self) -> None:
        if self._gate is not None:
            self._gate.set()

    async def __call__(self, window) -> dict:
        self.calls += 1
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        self.windows.append(np.array(window, copy=True))
        try:
            if self._gate is not None:
                await self._gate.wait()
            outcome = self._results.pop(0) if self._results else _success()
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        finally:
            self._in_flight -= 1


async def _drain(times: int = 3) -> None:
    """Let scheduled tasks run to completion."""
    for _ in range(times):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# 1. Only one inference in flight; nothing piles up
# ---------------------------------------------------------------------------

def test_at_most_one_inference_in_flight_per_session() -> None:
    """20 windows arriving during one slow call must start exactly one request."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        infer.block()  # the remote call never finishes during this phase
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=0.0, max_stale_seconds=30.0, clock=clock
        )

        for _ in range(20):
            scheduler.resolve(WINDOW)
            await asyncio.sleep(0)

        assert infer.calls == 1, "requests piled up instead of staying single-flight"
        assert infer.peak_in_flight == 1
        assert scheduler.inferences_started == 1

        # Once it completes, the next window may start a new one.
        infer.release()
        await _drain()
        assert scheduler.inferences_completed == 1
        scheduler.resolve(WINDOW)
        await asyncio.sleep(0)
        assert infer.calls == 2

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_windows_keep_resolving_while_inference_runs() -> None:
    """The 0.5 s decision cadence is preserved: resolve() never blocks.

    The inference is held open for the whole scenario, so a blocking
    implementation would hang here rather than pass.
    """

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        infer.block()
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=0.0, max_stale_seconds=30.0, clock=clock
        )

        scheduler.resolve(WINDOW)
        await asyncio.sleep(0)

        # 100 further windows == 50 s of audio at the 0.5 s hop, all while the
        # first request is still running.
        for _ in range(100):
            before = scheduler.windows_resolved
            evidence = scheduler.resolve(WINDOW)
            assert scheduler.windows_resolved == before + 1
            assert evidence.status in (STATUS_UNAVAILABLE, STATUS_STALE, STATUS_FRESH)
            clock.advance(0.5)

        assert scheduler.windows_resolved == 101
        assert infer.calls == 1  # and still only one request

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


# ---------------------------------------------------------------------------
# 2. Evidence provenance, stale reuse and bounded expiry
# ---------------------------------------------------------------------------

def test_fresh_evidence_exposes_full_provenance() -> None:
    """A successful inference must carry score, timestamp, latency and age."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=60.0, max_stale_seconds=60.0, clock=clock
        )

        first = scheduler.resolve(WINDOW)
        assert first.status == STATUS_UNAVAILABLE  # nothing completed yet
        assert first.acoustic_score is None
        await _drain()

        fresh = scheduler.current_evidence()
        assert fresh.status == STATUS_FRESH
        assert fresh.acoustic_score == pytest.approx(0.42)
        assert fresh.inference_timestamp is not None and fresh.inference_timestamp > 0
        assert fresh.inference_latency_ms == pytest.approx(8000.0)  # provider-reported
        assert fresh.evidence_age_ms == pytest.approx(0.0)

        rendered = fresh.to_acoustic_result()["details"]
        for key in (
            "evidence_status",
            "evidence_age_ms",
            "inference_latency_ms",
            "inference_timestamp",
        ):
            assert key in rendered, f"{key} missing from the acoustic result"

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_previous_result_is_reused_as_stale_while_newer_inference_pending() -> None:
    """A retained result stays usable -- as explicitly stale -- during refresh."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=10.0, max_stale_seconds=60.0, clock=clock
        )

        scheduler.resolve(WINDOW)
        await _drain()
        assert scheduler.current_evidence().status == STATUS_FRESH

        # Past the cadence interval the next window starts a refresh (held open).
        clock.advance(11.0)
        infer.block()
        stale = scheduler.resolve(WINDOW)

        assert stale.status == STATUS_STALE
        assert stale.acoustic_score == pytest.approx(0.42)  # real evidence, reused
        assert stale.evidence_age_ms == pytest.approx(11000.0)  # explicit bounded age
        assert scheduler.inference_in_flight is True
        assert scheduler.inferences_started == 2

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_stale_evidence_expires_to_unavailable() -> None:
    """Past the bounded age the evidence is withdrawn, never silently reused."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=1000.0, max_stale_seconds=30.0, clock=clock
        )

        scheduler.resolve(WINDOW)
        await _drain()
        assert scheduler.current_evidence().status == STATUS_FRESH

        clock.advance(31.0)
        expired = scheduler.resolve(WINDOW)

        assert expired.status == STATUS_UNAVAILABLE
        assert expired.acoustic_score is None
        assert "expired" in (expired.reason or "")

        rendered = expired.to_acoustic_result()
        assert rendered["acoustic_score"] is None
        assert rendered["success"] is False
        assert rendered["error_message"]

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_cadence_interval_limits_remote_starts() -> None:
    """20 s of audio at a 15 s interval must not mean 40 remote requests."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=15.0, max_stale_seconds=60.0, clock=clock
        )

        for _ in range(40):  # 40 hops x 0.5 s = 20 s of audio
            scheduler.resolve(WINDOW)
            await asyncio.sleep(0)
            clock.advance(0.5)

        assert infer.calls == 2, f"expected 2 starts (t=0, t=15) but saw {infer.calls}"
        assert infer.calls < 40  # the pre-fix behaviour was one per window

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


# ---------------------------------------------------------------------------
# 3. Failure honesty: never convert missing evidence into a genuine score
# ---------------------------------------------------------------------------

def test_provider_failure_yields_unavailable_and_no_fake_score() -> None:
    """A failed provider must produce None + reason, never a numeric score."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference(results=[_provider_failure()])
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=0.0, max_stale_seconds=30.0, clock=clock
        )

        scheduler.resolve(WINDOW)
        await _drain()

        evidence = scheduler.current_evidence()
        assert evidence.status == STATUS_UNAVAILABLE
        assert evidence.acoustic_score is None
        assert scheduler.inferences_failed == 1
        assert scheduler.inferences_completed == 0

        # The mapping onto the fan-out path produces the EXISTING degraded
        # semantics -- and specifically not the uninformative 0.5 placeholder.
        acoustic, _, _, degraded = await run_window_inference(
            WINDOW, run_anti_spoof=lambda _w: evidence.to_acoustic_result()
        )
        assert acoustic["acoustic_score"] is None
        assert acoustic["acoustic_score"] != 0.5
        assert acoustic["inference_available"] is False
        assert degraded.get("anti_spoof"), "unavailable evidence must flag degradation"

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_inference_exception_is_reported_not_scored() -> None:
    """A raised inference error degrades the evidence rather than faking a score."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference(results=[RuntimeError("lane timeout")])
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=0.0, max_stale_seconds=30.0, clock=clock
        )

        scheduler.resolve(WINDOW)
        await _drain()

        evidence = scheduler.current_evidence()
        assert evidence.status == STATUS_UNAVAILABLE
        assert evidence.acoustic_score is None
        assert "lane timeout" in (evidence.reason or "")
        assert scheduler.inferences_failed == 1

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_unusable_payload_score_is_rejected() -> None:
    """Out-of-range / non-finite scores must not be cached as evidence."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference(
            results=[{"acoustic_score": float("nan"), "success": True, "details": {}}]
        )
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=0.0, max_stale_seconds=30.0, clock=clock
        )

        scheduler.resolve(WINDOW)
        await _drain()

        assert scheduler.current_evidence().status == STATUS_UNAVAILABLE
        assert scheduler.inferences_failed == 1

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


# ---------------------------------------------------------------------------
# 4. Circuit breaker and session shutdown
# ---------------------------------------------------------------------------

def test_open_circuit_breaker_prevents_new_gpu_requests() -> None:
    """A latched quota breaker must stop requests immediately, not per window."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        breaker = {"open": True}
        scheduler = AcousticEvidenceScheduler(
            infer,
            interval_seconds=0.0,
            max_stale_seconds=30.0,
            is_available=lambda: not breaker["open"],
            clock=clock,
        )

        for _ in range(10):  # 5 s of audio while the breaker is open
            evidence = scheduler.resolve(WINDOW)
            await asyncio.sleep(0)

        assert infer.calls == 0, "GPU work was attempted while the breaker was open"
        assert evidence.status == STATUS_UNAVAILABLE
        assert evidence.acoustic_score is None

        # Breaker clears -> scheduling resumes and real evidence supersedes it.
        breaker["open"] = False
        scheduler.resolve(WINDOW)
        await _drain()
        assert infer.calls == 1
        assert scheduler.current_evidence().status == STATUS_FRESH

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


def test_session_shutdown_with_inference_in_flight_stops_scheduling() -> None:
    """Closing the session unwinds the in-flight call and schedules nothing more."""

    async def scenario() -> None:
        clock = _Clock()
        infer = _Inference()
        infer.block()
        scheduler = AcousticEvidenceScheduler(
            infer, interval_seconds=0.0, max_stale_seconds=30.0, clock=clock
        )

        scheduler.resolve(WINDOW)
        await asyncio.sleep(0)
        assert scheduler.inference_in_flight is True

        await scheduler.aclose(timeout=0.5)

        assert scheduler.enabled is False
        assert scheduler.inference_in_flight is False  # cancelled and awaited
        assert scheduler.current_evidence().status == STATUS_UNAVAILABLE

        started = infer.calls
        for _ in range(5):
            scheduler.resolve(WINDOW)
            await asyncio.sleep(0)
        assert infer.calls == started, "a closed session scheduled more GPU work"

        # Idempotent: teardown may run more than once.
        await scheduler.aclose(timeout=0.5)

    asyncio.run(asyncio.wait_for(scenario(), timeout=10))


# ---------------------------------------------------------------------------
# 5. Configuration and the scope of the cadence gate
# ---------------------------------------------------------------------------

def _config_probe(env_overrides: dict) -> str:
    """Read the cadence settings in a fresh interpreter (import-time values)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("VOICETRUST_ACOUSTIC")}
    env.update(env_overrides)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.config as c;"
            "print(c.ACOUSTIC_INFERENCE_INTERVAL_SECONDS,"
            " c.ACOUSTIC_EVIDENCE_MAX_STALE_SECONDS)",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_cadence_is_configurable_by_environment_variable() -> None:
    """The cadence must be tunable from the environment, never hardcoded."""
    assert (
        _config_probe(
            {
                "VOICETRUST_ACOUSTIC_INTERVAL_SECONDS": "7.5",
                "VOICETRUST_ACOUSTIC_MAX_STALE_SECONDS": "12.5",
            }
        )
        == "7.5 12.5"
    )


def test_conservative_diagnostic_defaults_without_environment() -> None:
    """Unset variables fall back to the conservative diagnostic defaults."""
    assert _config_probe({}) == "15.0 30.0"


def test_cadence_gate_applies_only_to_remote_providers() -> None:
    """Mock mode keeps per-window scoring so the deterministic demo still works."""
    from app.api.v1 import stream as stream_mod
    from app.services.ml_detector import MockVoiceDetector

    expected = not isinstance(stream_mod.detector, MockVoiceDetector)
    assert stream_mod._ACOUSTIC_CADENCE_ENABLED is expected
    if isinstance(stream_mod.detector, MockVoiceDetector):
        assert stream_mod._ACOUSTIC_CADENCE_ENABLED is False

