"""Remote anti-spoof evidence scheduling: cadence, single-flight, safe reuse.

THE PROBLEM THIS SOLVES
    The stream emits a 4-second window every 0.5 s (HOP_SAMPLES == 8000) and
    used to request a remote MMS inference for every one of those windows,
    awaiting it inline. Measured ZeroGPU latency is ~8 s per window, so the
    loop could advance only once per inference while windows kept becoming
    ready 16x faster. The result was an unbounded ring-buffer backlog, requests
    queued behind a single-worker lane, and decisions computed from audio that
    was already stale by the time it was scored.

    This module decouples the two cadences:
        - DECISION cadence (VAD, fusion, telemetry) stays at the 0.5 s hop.
        - REMOTE INFERENCE cadence becomes one request in flight per session,
          spaced by a measured, configurable interval.

EVIDENCE CONTRACT (never fabricate a score)
    fresh        the latest completed inference, with its timestamp and latency
    stale        a previously successful result while a NEWER inference is
                 pending -- still real evidence, reported with an explicit age
    unavailable  no usable evidence: nothing completed yet, it expired, or the
                 provider failed. `acoustic_score` is None so risk fusion
                 degrades honestly instead of assuming a genuine caller.

    A provider failure NEVER produces a numeric score (not 0.0, not 0.5): the
    uninformative placeholder is `None` plus a reason, matching the existing
    `degraded` semantics in app/core/risk_engine.py.

INTERACTION WITH THE QUOTA CIRCUIT BREAKER
    `is_available` is consulted before starting work, so a latched breaker
    (ZeroGPU quota exhausted) stops new GPU requests immediately rather than
    burning one refusal per window. The breaker itself is unchanged and still
    fail-fasts inside the provider.

SHUTDOWN
    `aclose()` stops scheduling immediately and cancels the in-flight task.
    Cancellation cannot interrupt a blocking HTTP call already executing on the
    inference lane: that thread finishes in the background, and the wait is
    bounded by `timeout` so session teardown can never hang indefinitely.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

import numpy as np

logger = logging.getLogger("satyavoice.acoustic")

STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_UNAVAILABLE = "unavailable"

# Default grace period for letting a cancelled in-flight inference unwind.
_SHUTDOWN_TIMEOUT_SECONDS = 5.0


@dataclass
class AcousticEvidence:
    """One window's acoustic evidence, carrying its own provenance.

    `status` is the semantic the rest of the pipeline keys off:
      fresh       -> latest completed result
      stale       -> real result, but a newer inference is pending (age bounded)
      unavailable -> no usable result; acoustic_score is None
    """

    status: str
    acoustic_score: Optional[float]
    inference_timestamp: Optional[float] = None  # wall clock (epoch seconds)
    inference_latency_ms: Optional[float] = None
    evidence_age_ms: Optional[float] = None
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.acoustic_score is not None

    def to_acoustic_result(self) -> Dict[str, Any]:
        """Render into the acoustic-result dict the existing pipeline consumes.

        The shape matches what `run_window_inference`, `_AcousticTrace` and
        `compute_risk` already expect, so risk-fusion semantics are preserved:
        a real score is fused normally, while an unavailable result surfaces as
        `acoustic_score=None, success=False` plus a reason -- the same condition
        that already produces `degraded["anti_spoof"]`.
        """
        details = dict(self.details or {})
        details.update(
            {
                "evidence_status": self.status,
                "evidence_age_ms": (
                    None if self.evidence_age_ms is None else round(self.evidence_age_ms, 1)
                ),
                "inference_latency_ms": (
                    None
                    if self.inference_latency_ms is None
                    else round(self.inference_latency_ms, 2)
                ),
                "inference_timestamp": self.inference_timestamp,
            }
        )

        if self.acoustic_score is None:
            return {
                "acoustic_score": None,
                "success": False,
                "inference_available": False,
                "detector_status": STATUS_UNAVAILABLE,
                "error_code": "INFERENCE_UNAVAILABLE",
                "error_message": self.reason or "anti-spoof evidence unavailable",
                "details": {
                    **details,
                    "status": STATUS_UNAVAILABLE,
                    "warning": self.reason,
                },
            }

        return {
            "acoustic_score": self.acoustic_score,
            "success": True,
            "inference_available": True,
            "detector_status": "ok",
            "details": {**details, "status": "ok"},
        }


class AcousticEvidenceScheduler:
    """One remote anti-spoof request at a time, per call/session.

    `infer` is an async callable `(window) -> acoustic-result dict` that performs
    the blocking provider call (the streaming path supplies one that runs on the
    shared anti-spoof lane). `resolve` never blocks and never awaits inference.
    """

    def __init__(
        self,
        infer: Callable[[np.ndarray], Awaitable[Dict[str, Any]]],
        *,
        interval_seconds: float,
        max_stale_seconds: float,
        is_available: Optional[Callable[[], bool]] = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._infer = infer
        self._interval_seconds = max(0.0, float(interval_seconds))
        self._max_stale_seconds = max(0.0, float(max_stale_seconds))
        self._is_available = is_available
        self._clock = clock
        self._wall_clock = wall_clock

        self._task: Optional[asyncio.Task] = None
        self._closed = False

        # Retained successful evidence (its status is computed per read).
        self._cached_score: Optional[float] = None
        self._cached_at: Optional[float] = None  # monotonic
        self._cached_wall: Optional[float] = None
        self._cached_latency_ms: Optional[float] = None
        self._cached_details: Dict[str, Any] = {}

        self._last_started_at: Optional[float] = None
        self._last_reason: Optional[str] = None

        # Telemetry counters (surfaced in risk telemetry by the caller).
        self.inferences_started = 0
        self.inferences_completed = 0
        self.inferences_failed = 0
        self.windows_resolved = 0
        self.evidence_reused = 0

    # ------------------------------------------------------------------ public

    @property
    def enabled(self) -> bool:
        return not self._closed

    @property
    def inference_in_flight(self) -> bool:
        return self._task is not None and not self._task.done()

    def resolve(self, window) -> AcousticEvidence:
        """Non-blocking: schedule if allowed, then report the current evidence.

        Called once per emitted window from the event loop. Incoming audio keeps
        flowing regardless -- no inference is ever awaited here.
        """
        self.windows_resolved += 1

        if not self.inference_in_flight:
            self._harvest()  # a finished task updates the retained evidence
            if self._should_start():
                self._start(window)

        return self.current_evidence()

    def current_evidence(self) -> AcousticEvidence:
        """The evidence to report right now, without scheduling anything."""
        if self._cached_score is None:
            return AcousticEvidence(
                status=STATUS_UNAVAILABLE,
                acoustic_score=None,
                reason=self._last_reason
                or "anti-spoof evidence not available yet (first inference pending)",
                details=dict(self._cached_details),
            )

        age_ms = self._age_ms()
        self.evidence_reused += 1

        if self._max_stale_seconds > 0 and age_ms > self._max_stale_seconds * 1000.0:
            return AcousticEvidence(
                status=STATUS_UNAVAILABLE,
                acoustic_score=None,
                inference_timestamp=self._cached_wall,
                inference_latency_ms=self._cached_latency_ms,
                evidence_age_ms=age_ms,
                reason=(
                    "anti-spoof evidence expired: age "
                    f"{age_ms:.0f} ms exceeds the bounded maximum of "
                    f"{self._max_stale_seconds * 1000.0:.0f} ms"
                ),
                details=dict(self._cached_details),
            )

        # A NEWER inference is pending -> the retained result is explicitly stale
        # (still real evidence, simply no longer the newest).
        status = STATUS_STALE if self.inference_in_flight else STATUS_FRESH
        return AcousticEvidence(
            status=status,
            acoustic_score=self._cached_score,
            inference_timestamp=self._cached_wall,
            inference_latency_ms=self._cached_latency_ms,
            evidence_age_ms=age_ms,
            details=dict(self._cached_details),
        )

    async def aclose(self, timeout: float = _SHUTDOWN_TIMEOUT_SECONDS) -> None:
        """Stop scheduling and unwind any in-flight inference.

        Safe to call from the WebSocket teardown path; idempotent.

        After this returns the task reference is cleared and no further
        GPU work will be scheduled.
        """
        self._closed = True
        task = self._task
        if task is None or task.done():
            return
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # The task did not finish in time; the reference will be cleared
            # below regardless so that subsequent resolve() calls do not
            # re‑queue work.
            pass
        finally:
            self._task = None

    # ----------------------------------------------------------------- private

    def _age_ms(self) -> float:
        if self._cached_at is None:
            return 0.0
        return max(0.0, (self._clock() - self._cached_at) * 1000.0)

    def _provider_available(self) -> bool:
        """Consult the provider's circuit breaker before spending GPU quota."""
        if self._is_available is None:
            return True
        try:
            return bool(self._is_available())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("availability probe failed: %s", type(exc).__name__)
            return True

    def _should_start(self) -> bool:
        if self._closed:
            return False
        if not self._provider_available():
            return False
        # First inference: start immediately so evidence exists as early as
        # possible rather than waiting a full interval for nothing.
        if self._cached_score is None and self._last_started_at is None:
            return True
        if self._interval_seconds <= 0:
            return True
        if self._last_started_at is None:
            return True
        return (self._clock() - self._last_started_at) >= self._interval_seconds

    def _start(self, window) -> None:
        self._last_started_at = self._clock()
        self.inferences_started += 1
        # Detach from the ring buffer: its storage may be reused while the
        # inference runs.
        try:
            snapshot = np.array(window, dtype=np.float32, copy=True)
        except Exception:  # pragma: no cover - defensive
            snapshot = window
        self._task = asyncio.ensure_future(self._run(snapshot))

    async def _run(self, window) -> None:
        started = self._clock()
        started_wall = self._wall_clock()
        try:
            result = await self._infer(window)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_failure(f"{type(exc).__name__}: {exc}")
            return
        latency_ms = (self._clock() - started) * 1000.0
        self._record_result(
            result if isinstance(result, dict) else {}, started_wall, latency_ms
        )

    def _record_result(
        self, result: Dict[str, Any], started_wall: float, latency_ms: float
    ) -> None:
        try:
            value = float(result.get("acoustic_score"))
        except (TypeError, ValueError):
            value = None

        if value is None or not math.isfinite(value) or not 0.0 <= value <= 1.0:
            # Never synthesize a score from an unusable payload.
            self._record_failure(
                result.get("error_message")
                or "anti-spoof inference returned no usable acoustic score"
            )
            return

        provider_latency = (result.get("details") or {}).get("inference_time_ms")
        self._cached_score = value
        self._cached_at = self._clock()
        self._cached_wall = started_wall
        self._cached_latency_ms = (
            float(provider_latency)
            if isinstance(provider_latency, (int, float)) and provider_latency
            else latency_ms
        )
        self._cached_details = dict(result.get("details") or {})
        self._last_reason = None
        self.inferences_completed += 1
        logger.info(
            "acoustic evidence refreshed: score=%.4f inference_latency_ms=%.0f "
            "cadence_interval_s=%.1f",
            value,
            self._cached_latency_ms,
            self._interval_seconds,
        )

    def _record_failure(self, reason: str) -> None:
        self.inferences_failed += 1
        self._last_reason = reason
        logger.warning(
            "acoustic evidence unavailable: error=%s (no synthetic score emitted)",
            reason[:300],
        )

    def _harvest(self) -> None:
        """Retrieve a finished task's outcome so exceptions are never lost."""
        task = self._task
        if task is None or not task.done():
            return
        self._task = None
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:  # pragma: no cover - defensive
            self._record_failure(f"{type(exception).__name__}: {exception}")

    def telemetry(self) -> Dict[str, Any]:
        """Small, token-free diagnostic snapshot for risk telemetry."""
        return {
            "cadence_interval_s": self._interval_seconds,
            "max_stale_s": self._max_stale_seconds,
            "inferences_started": self.inferences_started,
            "inferences_completed": self.inferences_completed,
            "inferences_failed": self.inferences_failed,
            "windows_resolved": self.windows_resolved,
            "evidence_reused": self.evidence_reused,
            "inference_in_flight": self.inference_in_flight,
        }
