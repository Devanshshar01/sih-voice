"""
Bounded parallel inference fan-out (SIH Phase 2).

The three per-window models are statistically independent of each other, so
they run CONCURRENTLY instead of serially:

    4-second window
        |
        +--> anti-spoof (Wav2Vec2 / mock)
        |
        +--> faster-whisper ASR          } asyncio.gather over a bounded
        |                                 } ThreadPoolExecutor (max workers
        +--> ECAPA speaker embedding      } from app.config)
             |
             v
        risk fusion

Safety properties:
  * ONE shared, bounded executor (INFERENCE_EXECUTOR_MAX_WORKERS) — a burst
    of concurrent calls can never spawn unbounded threads.
  * Per-stage timeout (INFERENCE_TIMEOUT_SECONDS): a hung model blocks one
    decision for at most that long, then the stage degrades (below).
  * No model is ever run concurrently with itself: PyTorch/CT2 inference is
    not guaranteed thread-safe, so each stage routes through a dedicated
    single-worker lane executor. GPU calls stay serialized within a stage.
  * Failures are captured per stage, never propagated into the WS loop.
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from app import config

logger = logging.getLogger(__name__)

# One bounded shared pool for CPU-bound fan-out work.
_SHARED_EXECUTOR: Optional[ThreadPoolExecutor] = None


def get_shared_executor() -> ThreadPoolExecutor:
    global _SHARED_EXECUTOR
    if _SHARED_EXECUTOR is None:
        _SHARED_EXECUTOR = ThreadPoolExecutor(
            max_workers=config.INFERENCE_EXECUTOR_MAX_WORKERS,
            thread_name_prefix="satyavoice-inference",
        )
    return _SHARED_EXECUTOR


class _Lane:
    """Serializes inference for one model: a model never runs against itself."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"satyavoice-{name}"
        )

    async def run(self, fn: Callable[..., Any], *args, timeout: Optional[float] = None, **kwargs) -> Any:
        loop = asyncio.get_running_loop()
        coro = loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))
        return await asyncio.wait_for(coro, timeout=timeout)


# Dedicated lanes: anti-spoof, ASR, and speaker never overlap with themselves.
_ANTI_SPOOF_LANE: Optional[_Lane] = None
_ASR_LANE: Optional[_Lane] = None
_SPEAKER_LANE: Optional[_Lane] = None


def _anti_spoof_lane() -> _Lane:
    global _ANTI_SPOOF_LANE
    if _ANTI_SPOOF_LANE is None:
        _ANTI_SPOOF_LANE = _Lane("anti-spoof")
    return _ANTI_SPOOF_LANE


def _asr_lane() -> _Lane:
    global _ASR_LANE
    if _ASR_LANE is None:
        _ASR_LANE = _Lane("asr")
    return _ASR_LANE


def _speaker_lane() -> _Lane:
    global _SPEAKER_LANE
    if _SPEAKER_LANE is None:
        _SPEAKER_LANE = _Lane("speaker")
    return _SPEAKER_LANE


_EMPTY_SPEAKER = {
    "speaker_id": None,
    "speaker_match_score": None,  # None = identity evidence unavailable/neutral
    "matched": False,
    "vault_size": 0,
    "method": "disabled",
    "checkpoint_status": "Speaker vault disabled by configuration.",
}


async def run_window_inference(
    window,
    *,
    run_anti_spoof: Callable[[Any], Dict[str, Any]],
    run_asr: Optional[Callable[[Any], str]] = None,
    run_speaker: Optional[Callable[[Any], Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Any], Optional[str], Dict[str, Any], Dict[str, str]]:
    """Run the three inference stages concurrently for one window.

    Returns:
        (acoustic_result, transcript, speaker_match, degraded)

    `degraded` maps stage name -> failure reason for any stage that threw or
    timed out. Acoustic failure yields the uninformative 0.5 placeholder;
    ASR failure yields None (fusion treats missing ASR as neutral); speaker
    failure yields similarity None (identity evidence neutral, not fraud).
    """
    degraded: Dict[str, str] = {}
    timeout = config.INFERENCE_TIMEOUT_SECONDS

    async def _anti_spoof() -> Tuple[Dict[str, Any], Optional[str]]:
        try:
            return await _anti_spoof_lane().run(run_anti_spoof, window, timeout=timeout), None
        except asyncio.TimeoutError:
            return _degraded_acoustic(), f"timeout after {timeout:.1f}s"
        except Exception as exc:
            return _degraded_acoustic(), f"{exc.__class__.__name__}: {exc}"

    async def _asr() -> Tuple[Optional[str], Optional[str]]:
        if run_asr is None:
            return None, None
        try:
            return await _asr_lane().run(run_asr, window, timeout=timeout), None
        except asyncio.TimeoutError:
            return None, f"timeout after {timeout:.1f}s"
        except Exception as exc:
            return None, f"{exc.__class__.__name__}: {exc}"

    async def _speaker() -> Tuple[Dict[str, Any], Optional[str]]:
        if run_speaker is None:
            return dict(_EMPTY_SPEAKER), None
        try:
            return await _speaker_lane().run(run_speaker, window, timeout=timeout), None
        except asyncio.TimeoutError:
            return dict(_EMPTY_SPEAKER), f"timeout after {timeout:.1f}s"
        except Exception as exc:
            return dict(_EMPTY_SPEAKER), f"{exc.__class__.__name__}: {exc}"

    (acoustic_result, acoustic_err), (transcript, asr_err), (speaker_match, speaker_err) = await asyncio.gather(
        _anti_spoof(), _asr(), _speaker()
    )

    if acoustic_err:
        degraded["anti_spoof"] = acoustic_err
    if asr_err:
        degraded["asr"] = asr_err
    if speaker_err:
        degraded["speaker"] = speaker_err

    return acoustic_result, transcript, speaker_match, degraded


def _degraded_acoustic() -> Dict[str, Any]:
    return {
        "acoustic_score": 0.5,  # uninformative prior; fusion adds a penalty
        "details": {"mode": "degraded", "warning": "anti_spoof_unavailable"},
    }
