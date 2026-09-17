"""Production database resilience (Task A).

Reproduces the Render failure mode where managed PostgreSQL closes an idle
connection server-side, so the next use raises:

    OperationalError: SSL connection has been closed unexpectedly

Guarantees asserted here:
  - a transient closed connection is recognised and retried ONCE
  - every failed commit is rolled back and the pool is disposed (the failed
    session is never reused)
  - the retry is bounded (no infinite loop, no per-event retry storm)
  - non-transient errors (constraint/FK violations) are never retried
  - failure is reported as False, never silently converted into success
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError

from app.db import database


def _operational(message: str) -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(message))


class _FakeSession:
    """Minimal session stand-in recording commit/rollback ordering."""

    def __init__(self, failures: int = 0, exc: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.commit_attempts = 0
        self._failures = failures
        self._exc = exc

    def commit(self) -> None:
        self.calls.append("commit")
        self.commit_attempts += 1
        if self.commit_attempts <= self._failures:
            raise self._exc or _operational("SSL connection has been closed unexpectedly")

    def rollback(self) -> None:
        self.calls.append("rollback")


def test_engine_is_configured_with_pre_ping_and_bounded_recycle() -> None:
    assert database.engine.pool._pre_ping is True
    assert database.engine.pool._recycle == 300


def test_is_transient_disconnect_recognises_render_ssl_closure() -> None:
    assert database.is_transient_disconnect(
        _operational("SSL connection has been closed unexpectedly")
    )


def test_is_transient_disconnect_recognises_interface_and_reset_errors() -> None:
    assert database.is_transient_disconnect(
        InterfaceError("SELECT 1", {}, Exception("connection already closed"))
    )
    assert database.is_transient_disconnect(
        _operational("connection reset by peer")
    )
    assert database.is_transient_disconnect(_operational("server closed the connection"))


def test_is_transient_disconnect_rejects_constraint_violations() -> None:
    exc = IntegrityError(
        "INSERT", {}, Exception("duplicate key value violates unique constraint")
    )
    assert database.is_transient_disconnect(exc) is False


def test_transient_failure_is_retried_once_then_recovers(monkeypatch) -> None:
    dispose = mock.Mock()
    monkeypatch.setattr(database, "dispose_engine_pool", dispose)
    restage = mock.Mock()
    db = _FakeSession(failures=1)

    assert database.commit_with_retry(db, restage, context="test") is True
    assert db.commit_attempts == 2
    assert "rollback" in db.calls  # failed session was rolled back first
    dispose.assert_called_once()  # dead connection discarded before retry
    restage.assert_called_once()  # work re-staged for the fresh connection


def test_retry_is_bounded_and_surfaces_failure(monkeypatch) -> None:
    monkeypatch.setattr(database, "dispose_engine_pool", mock.Mock())
    db = _FakeSession(failures=99)

    assert database.commit_with_retry(db, mock.Mock(), attempts=2, context="test") is False
    assert db.commit_attempts == 2  # exactly the configured bound, never more


def test_non_transient_error_is_never_retried(monkeypatch) -> None:
    monkeypatch.setattr(database, "dispose_engine_pool", mock.Mock())
    restage = mock.Mock()
    db = _FakeSession(
        failures=99, exc=IntegrityError("INSERT", {}, Exception("fk violation"))
    )

    assert database.commit_with_retry(db, restage, context="test") is False
    assert db.commit_attempts == 1  # no retry for a permanent error
    assert "rollback" in db.calls
    restage.assert_not_called()


def test_missing_redo_performs_a_single_attempt(monkeypatch) -> None:
    monkeypatch.setattr(database, "dispose_engine_pool", mock.Mock())
    db = _FakeSession(failures=99)

    assert database.commit_with_retry(db, None, context="test") is False
    assert db.commit_attempts == 1


def test_rollback_failure_does_not_escape(monkeypatch) -> None:
    """A dead session can also fail to roll back; recovery must still proceed."""
    monkeypatch.setattr(database, "dispose_engine_pool", mock.Mock())

    class _RollbackBoom(_FakeSession):
        def rollback(self) -> None:
            raise RuntimeError("rollback on dead connection")

    assert database.commit_with_retry(_RollbackBoom(failures=99), None, context="t") is False
