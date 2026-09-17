"""Live-stream persistence resilience and anti-spoof tracing (Tasks A/D/E).

Production symptoms this file guards against:
  - hundreds of "DB persist error ... IntegrityError" lines per call
  - an opaque "Degraded evidence (model failure): anti_spoof" with no
    indication of which stage, provider, model, or error caused it
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest import mock

import numpy as np

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-stream-abc123")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.api.v1 import analyze, stream

WINDOW = np.zeros(64000, dtype=np.float32)  # 4 s @ 16 kHz


class _LogCollector(logging.Handler):
    """Collects records directly from the target logger.

    ``caplog`` depends on root-logger propagation and on no other test module
    mutating global logging state. Assertions about this module's structured
    logging must hold no matter what the rest of the suite does, so the handler
    is attached to the specific logger instead.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


@contextmanager
def _capture(logger: logging.Logger) -> Iterator[_LogCollector]:
    """Capture ``logger``'s records hermetically.

    Two pieces of global logging state can silently swallow records regardless
    of the target logger's own level:
      - ``logger.propagate`` (root handlers never see the record)
      - ``logging.Logger.manager.disable`` (set by ``logging.disable()``, which
        filters every record below the given level process-wide)
    Both are neutralised for the duration of the block and restored on exit, so
    these assertions cannot be broken by another module's logging setup.
    """
    collector = _LogCollector()
    previous_level, previous_propagate = logger.level, logger.propagate
    previous_disable = logging.root.manager.disable
    previous_disabled = logger.disabled

    logger.addHandler(collector)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logging.disable(logging.NOTSET)
    # ``logging.config.dictConfig(disable_existing_loggers=True)`` — run by some
    # third-party import in the wider suite — sets ``Logger.disabled = True`` on
    # every already-created logger, which makes ``isEnabledFor`` return False and
    # silently drops every record. Neutralise it for the duration of the block.
    logger.disabled = False
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        logging.disable(previous_disable)
        logger.disabled = previous_disabled


class _FakeQuery:
    def __init__(self, row=None) -> None:
        self._row = row

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._row


class _FakeDB:
    def __init__(self, row=None) -> None:
        self.added: list = []
        self._row = row

    def add(self, obj) -> None:
        self.added.append(obj)

    def query(self, _model):
        return _FakeQuery(self._row)


def _risk_result(score: int = 42) -> dict:
    return {
        "acoustic_score": 0.5,
        "intent_score": 0.1,
        "risk_score": score,
        "status": "WARN",
    }


def test_persist_recovers_from_a_transient_failure(monkeypatch) -> None:
    """A transiently closed connection must not permanently break persistence."""
    monkeypatch.setattr(stream, "commit_with_retry", lambda *a, **k: True)
    db = _FakeDB()
    state = stream._PersistState("call-recover")

    stream._persist_risk_event(db, "call-recover", _risk_result(), state)

    assert len(db.added) == 1  # the RiskEvent was staged
    assert state.enabled is True
    assert state.failures == 0


def test_permanent_failure_disables_persistence_and_logs_only_once(monkeypatch) -> None:
    """The core Task E guarantee: no identical error per incoming audio event."""
    monkeypatch.setattr(stream, "commit_with_retry", lambda *a, **k: False)
    db = _FakeDB()
    state = stream._PersistState("call-fail")

    with _capture(stream._logger) as logs:
        for _ in range(25):  # 25 audio events, as in the production log
            stream._persist_risk_event(db, "call-fail", _risk_result(), state)

    assert state.enabled is False
    assert len(db.added) == 1  # no further writes were even attempted
    disable_logs = [m for m in logs.messages() if "DB persistence disabled" in m]
    assert len(disable_logs) == 1


def test_disabled_state_performs_no_database_work(monkeypatch) -> None:
    """best_effort mode established at /call/start skips DB writes entirely."""
    commit = mock.Mock()
    monkeypatch.setattr(stream, "commit_with_retry", commit)
    db = _FakeDB()
    state = stream._PersistState("call-degraded", enabled=False)

    stream._persist_risk_event(db, "call-degraded", _risk_result(), state)

    assert db.added == []
    commit.assert_not_called()


def test_persist_without_state_keeps_the_legacy_call_site_working(monkeypatch) -> None:
    monkeypatch.setattr(stream, "commit_with_retry", lambda *a, **k: True)
    db = _FakeDB()
    stream._persist_risk_event(db, "call-legacy", _risk_result())
    assert len(db.added) == 1


def test_max_risk_score_is_lifted_on_the_session_row(monkeypatch) -> None:
    monkeypatch.setattr(stream, "commit_with_retry", lambda *a, **k: True)

    class _Row:
        max_risk_score = 10

    db = _FakeDB(row=_Row())
    stream._persist_risk_event(db, "call-score", _risk_result(score=77))
    assert db._row.max_risk_score == 77


# ---------------------------------------------------------------------------
# Task D: structured anti-spoof tracing
# ---------------------------------------------------------------------------

def test_healthy_window_logs_once_with_structured_provider_details() -> None:
    trace = stream._AcousticTrace("call-ok")
    result = {
        "acoustic_score": 0.91,
        "success": True,
        "detector_status": "ok",
        "details": {"mode": "zerogpu", "model_version_antispoof": "mms-anti-deepfake"},
    }

    with _capture(stream._logger) as logs:
        for _ in range(8):  # steady state must not log per window
            trace.record(
                acoustic_result=result,
                degraded={},
                window=WINDOW,
                elapsed_ms=123.4,
            )

    records = [r for r in logs.records if "anti_spoof_provider" in r.getMessage()]
    assert len(records) == 1
    payload = records[0].args[0]
    assert '"status": "ok"' in payload
    assert '"provider_ms": 123.4' in payload
    assert '"sample_rate": 16000' in payload
    assert '"model_id": "mms-anti-deepfake"' in payload
    assert '"score_normalized": true' in payload
    assert '"window_ms": 4000.0' in payload


def test_degraded_window_reports_error_type_and_message() -> None:
    """Makes 'anti_spoof is degraded' attributable without guessing."""
    trace = stream._AcousticTrace("call-degraded-trace")
    result = {
        "acoustic_score": None,
        "success": False,
        "detector_status": "unavailable",
        "details": {"mode": "degraded"},
    }

    with _capture(stream._logger) as logs:
        trace.record(
            acoustic_result=result,
            degraded={"anti_spoof": "ConnectionError: Could not reach ZeroGPU Space"},
            window=WINDOW,
            elapsed_ms=5000.0,
        )

    records = [r for r in logs.records if "anti_spoof_provider" in r.getMessage()]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    payload = records[0].args[0]
    assert '"status": "degraded"' in payload
    assert '"error_type": "ConnectionError"' in payload
    assert "Could not reach ZeroGPU Space" in payload
    assert '"score_normalized": false' in payload
    assert '"degraded_stage": "anti_spoof"' in (trace.summary() or "")


def test_healthy_call_has_no_end_of_call_degradation_summary() -> None:
    trace = stream._AcousticTrace("call-clean")
    trace.record(
        acoustic_result={"acoustic_score": 0.2, "details": {"mode": "zerogpu"}},
        degraded={},
        window=WINDOW,
        elapsed_ms=10.0,
    )
    assert trace.summary() is None


def test_live_stream_reuses_the_audio_analyze_detector_implementation() -> None:
    """No duplicated provider path: both routes resolve the same detector class.

    /api/v1/audio/analyze is the known-good pipeline; the live stream must route
    anti-spoof through the same provider implementation and configuration rather
    than its own copy.
    """
    assert type(stream.detector).__name__ == type(analyze.detector).__name__
