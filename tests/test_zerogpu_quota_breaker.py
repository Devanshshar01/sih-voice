"""ZeroGPU quota circuit breaker + HF token passing + degraded persistence.

Regression coverage for the live-stream ZeroGPU failure where every call failed
with "You have exceeded your ZeroGPU runs limit" even though HF_TOKEN was
configured on Render:

1. gradio_client renamed its auth parameter between major versions (1.x:
   ``hf_token=``; 2.x+/Gradio 6 era: ``token=``). Passing the wrong name is
   silently dropped, leaving every Space call UNAUTHENTICATED — surfacing as a
   quota error. These tests prove the configured token reaches Client under the
   correct kwarg WITHOUT ever printing or logging the token value.
2. Quota exhaustion is per-account, not per-request: a live stream at ~3
   windows/second must NOT keep issuing GPU requests once the quota is spent.
   The circuit breaker latches and fail-fasts until the cooldown elapses.
3. Missing anti-spoof evidence must persist as an explicit NULL acoustic_score
   (never a fabricated number).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be set before app.config / app.api.v1.stream are imported: stream.py
# constructs a module-level detector at import time, which requires these.
os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-quota-breaker")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

from app.services import zerogpu_provider as zgp
from app.services.inference_provider import InferenceResult

SECRET_TOKEN = "hf_TEST_SECRET_do_not_print_0123456789"

# A valid remote payload (all validation in the provider must pass).
_GOOD_PAYLOAD = {
    "status": "ok",
    "fake_probability": 0.4,
    "real_probability": 0.6,
    "spoof_probability": 0.4,
    "speaker_embedding": [0.1] * 8,
    "inference_time_ms": 12.5,
    "model_version_antispoof": zgp.MMS_MODEL_ID,
    "model_version_speaker": "speechbrain/spkrec-ecapa-voxceleb",
    "sample_rate": 16000,
    "duration_ms": 4000.0,
}

QUOTA_MESSAGE = (
    "You have exceeded your ZeroGPU runs limit. "
    "Authenticate with a Hugging Face token for more quota."
)


def _window() -> np.ndarray:
    return np.zeros(16000, dtype=np.float32)


class _RecordingClient:
    """Stands in for gradio_client.Client; records constructor kwargs."""

    construct_kwargs: dict = {}
    predict_calls: int = 0
    predict_behavior: str = "ok"  # "ok" | "quota" | "transport"

    def __init__(self, *args, **kwargs):
        type(self).construct_kwargs = dict(kwargs)

    def predict(self, *args, **kwargs):
        type(self).predict_calls += 1
        if type(self).predict_behavior == "quota":
            raise RuntimeError(QUOTA_MESSAGE)
        if type(self).predict_behavior == "transport":
            raise ConnectionError("connection reset")
        return dict(_GOOD_PAYLOAD)


@pytest.fixture
def recording_client(monkeypatch):
    monkeypatch.setattr(zgp, "Client", _RecordingClient)
    monkeypatch.setattr(zgp, "handle_file", lambda path: mock.sentinel.HANDLE)
    _RecordingClient.construct_kwargs = {}
    _RecordingClient.predict_calls = 0
    _RecordingClient.predict_behavior = "ok"
    return _RecordingClient


def _make_provider() -> zgp.ZeroGPUInferenceProvider:
    return zgp.ZeroGPUInferenceProvider(
        space_url="https://example-space.hf.space",
        hf_token=SECRET_TOKEN,
    )


class _Handler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.messages: list[str] = []
        # Levels are captured alongside messages so tests can assert the
        # SEVERITY a diagnostic is emitted at. Severity decides visibility:
        # hosts without root-logger configuration only surface WARNING+.
        self.levels: list[int] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())
        self.levels.append(record.levelno)


# ---------------------------------------------------------------------------
# 1. The configured HF token must actually reach gradio_client.Client
# ---------------------------------------------------------------------------

def test_client_receives_configured_hf_token_without_leaking_it(recording_client) -> None:
    # The provider logs "token_configured=..." in __init__, so the capturing
    # handler must be attached BEFORE construction, not after. The suite-wide
    # dictConfig (disable_existing_loggers=True) can leave this logger disabled
    # or above INFO, so neutralize it explicitly and restore afterwards.
    handler = _Handler()
    zgp.logger.addHandler(handler)
    prev_level = zgp.logger.level
    prev_disabled = zgp.logger.disabled
    prev_propagate = zgp.logger.propagate
    zgp.logger.setLevel(logging.DEBUG)
    zgp.logger.disabled = False
    zgp.logger.propagate = False
    try:
        provider = _make_provider()
        result = provider.infer_audio_window_sync(_window())
    finally:
        zgp.logger.removeHandler(handler)
        zgp.logger.setLevel(prev_level)
        zgp.logger.disabled = prev_disabled
        zgp.logger.propagate = prev_propagate

    assert result.success is True
    # The token must arrive under the kwarg name THIS gradio_client accepts,
    # with the exact configured value, so the Space call is authenticated.
    kwarg = zgp._auth_token_kwarg()
    assert kwarg in ("token", "hf_token")
    assert _RecordingClient.construct_kwargs.get(kwarg) == SECRET_TOKEN
    # The token value must never appear in logs — only its presence flag.
    assert all(SECRET_TOKEN not in m for m in handler.messages)
    assert any("token_configured=True" in m for m in handler.messages)


class _LogCapture:
    """Capture this module's diagnostics, neutralizing logger state.

    Mirrors the pattern used above: a suite-wide
    ``dictConfig(disable_existing_loggers=True)`` can leave this logger disabled
    or above INFO, so level, ``disabled`` and ``propagate`` are forced for the
    duration and restored afterwards.
    """

    def __enter__(self) -> _Handler:
        self.handler = _Handler()
        zgp.logger.addHandler(self.handler)
        self.prev_level = zgp.logger.level
        self.prev_disabled = zgp.logger.disabled
        self.prev_propagate = zgp.logger.propagate
        zgp.logger.setLevel(logging.DEBUG)
        zgp.logger.disabled = False
        zgp.logger.propagate = False
        return self.handler

    def __exit__(self, *_exc) -> bool:
        zgp.logger.removeHandler(self.handler)
        zgp.logger.setLevel(self.prev_level)
        zgp.logger.disabled = self.prev_disabled
        zgp.logger.propagate = self.prev_propagate
        return False


def test_startup_diagnostic_reports_client_version_and_auth_kwarg(recording_client) -> None:
    """The startup diagnostic must be self-supporting from a production log.

    A Render log line alone has to distinguish "no token reached the process"
    from "wrong auth kwarg for the installed gradio_client". That requires the
    client version, the selected kwarg, the token presence flag and the timeout
    — all without ever printing the token value.
    """
    with _LogCapture() as capture:
        provider = zgp.ZeroGPUInferenceProvider(
            space_url="https://example-space.hf.space",
            hf_token=SECRET_TOKEN,
        )

    diagnostic = [m for m in capture.messages if "provider initialised" in m]
    assert len(diagnostic) == 1, capture.messages
    line = diagnostic[0]
    assert f"gradio_client={provider.gradio_client_version}" in line
    assert provider.gradio_client_version != "unknown"  # a real version, usable in ops
    assert f"auth_kwarg={zgp._auth_token_kwarg()}" in line
    assert "token_configured=True" in line
    assert "timeout_s=" in line
    # The token value must never appear in ANY captured record.
    assert all(SECRET_TOKEN not in m for m in capture.messages)


def test_startup_diagnostic_is_info_level_so_hosts_can_configure_it(recording_client) -> None:
    """The success diagnostic is INFO; the failure diagnostic is WARNING.

    Severity is load-bearing: hosts that never configure root logging (uvicorn
    does not) only surface WARNING and above, so a missing token MUST be WARNING
    to be visible, while the routine startup line stays INFO.
    """
    with _LogCapture() as capture_with_token:
        zgp.ZeroGPUInferenceProvider(
            space_url="https://example-space.hf.space",
            hf_token=SECRET_TOKEN,
        )
    levels = dict(zip(capture_with_token.messages, capture_with_token.levels))
    assert levels[
        next(m for m in capture_with_token.messages if "provider initialised" in m)
    ] == logging.INFO


def test_startup_diagnostic_warns_when_token_missing(recording_client) -> None:
    """A missing token must be loudly attributable, never silent.

    An unauthenticated Space call is the most common cause of the ZeroGPU
    quota-exhaustion error, so the absence of the token has to be recorded at a
    severity that survives hosts filtering application logs to WARNING+.
    """
    with _LogCapture() as capture:
        zgp.ZeroGPUInferenceProvider(space_url="https://example-space.hf.space")

    warnings = [
        m
        for m, level in zip(capture.messages, capture.levels)
        if "WITHOUT a Hugging Face token" in m and level == logging.WARNING
    ]
    assert len(warnings) == 1, capture.messages
    assert "HF_TOKEN" in warnings[0]  # names the fix, not the value
    assert SECRET_TOKEN not in warnings[0]


def test_app_logging_bootstrap_enables_info_diagnostics() -> None:
    """app.configure_app_logging() must make INFO diagnostics emittable.

    Regression guard for the production symptom where the provider had
    initialised but its diagnostics never appeared: uvicorn's default config
    supplies no root handlers, so application INFO records were dropped by
    ``logging.lastResort`` (WARNING+ only).
    """
    import app as app_pkg

    app_pkg.configure_app_logging()
    app_logger = logging.getLogger("satyavoice")
    assert app_logger.level <= logging.INFO  # an int level, INFO or more verbose
    assert app_logger.disabled is False
    # Must be idempotent — ``app`` is imported many times per process.
    app_pkg.configure_app_logging()
    assert app_logger.level <= logging.INFO


def test_provider_without_token_omits_auth_kwarg(recording_client) -> None:
    provider = zgp.ZeroGPUInferenceProvider(space_url="https://example-space.hf.space")
    provider.infer_audio_window_sync(_window())
    kwarg = zgp._auth_token_kwarg()
    assert kwarg not in _RecordingClient.construct_kwargs


# ---------------------------------------------------------------------------
# 2. Quota exhaustion opens the circuit breaker and stops GPU requests
# ---------------------------------------------------------------------------

def test_quota_error_latches_breaker_and_stops_gpu_requests(recording_client) -> None:
    provider = _make_provider()
    _RecordingClient.predict_behavior = "quota"

    first = provider.infer_audio_window_sync(_window())
    assert first.success is False
    assert first.error_code == "QUOTA_EXHAUSTED"
    assert _RecordingClient.predict_calls == 1

    # Every subsequent window must fail fast WITHOUT another GPU request.
    for _ in range(5):
        repeat = provider.infer_audio_window_sync(_window())
        assert repeat.success is False
        assert repeat.error_code == "QUOTA_EXHAUSTED"
    assert _RecordingClient.predict_calls == 1  # latched: no further calls

    assert provider.quota_exhausted() is True
    assert provider.is_available() is False


def test_breaker_half_opens_after_cooldown_and_recovers(recording_client) -> None:
    provider = _make_provider()
    provider._quota_exhausted_at = time.monotonic() - (provider.QUOTA_COOLDOWN_SECONDS + 1.0)
    _RecordingClient.predict_behavior = "ok"

    assert provider.quota_exhausted() is False  # cooldown elapsed -> half-open
    result = provider.infer_audio_window_sync(_window())
    assert result.success is True
    assert _RecordingClient.predict_calls == 1
    assert provider.is_available() is True


def test_non_quota_error_does_not_open_breaker(recording_client) -> None:
    provider = _make_provider()
    _RecordingClient.predict_behavior = "transport"

    for _ in range(2):
        result = provider.infer_audio_window_sync(_window())
        assert result.success is False
        assert result.error_code == "INFERENCE_UNAVAILABLE"

    assert _RecordingClient.predict_calls == 2  # retried, not latched
    assert provider.quota_exhausted() is False


def test_quota_error_message_from_production_is_recognized(recording_client) -> None:
    """The exact production log string must map onto the breaker."""
    provider = _make_provider()
    assert provider._is_quota_error(RuntimeError(QUOTA_MESSAGE)) is True
    assert provider._is_quota_error(ConnectionError("connection reset")) is False


# ---------------------------------------------------------------------------
# 3. Missing anti-spoof evidence persists as explicit NULL — never a number
# ---------------------------------------------------------------------------

class _FakeQuery:
    """Chainable stand-in for db.query(Session).filter_by(...).first()."""

    def __init__(self, row) -> None:
        self._row = row

    def filter_by(self, **_kwargs):
        return self

    def first(self):
        return self._row


class _FakeDB:
    """Records added ORM objects; supports the query chain _stage() uses."""

    def __init__(self, row) -> None:
        self.added: list = []
        self._row = row

    def add(self, obj) -> None:
        self.added.append(obj)

    def query(self, _model) -> _FakeQuery:
        return _FakeQuery(self._row)


def _risk_result(score: int) -> dict:
    """Minimal risk-result dict with the exact keys _stage() reads."""
    return {
        "acoustic_score": 0.42,
        "intent_score": 0.1,
        "risk_score": score,
        "status": "ok",
    }


def test_degraded_window_persists_null_acoustic_score(monkeypatch) -> None:
    """When anti-spoof is unavailable, risk_events.acoustic_score must be NULL.

    Faking 0.0/0.5 would corrupt the forensic audit trail (NULL means "no
    evidence"; a number means "measured"). The risk fusion already handles
    None by flagging degraded evidence and raising the risk score.
    """
    from app.api.v1 import stream as stream_mod

    class _Row:
        max_risk_score = 0

    db = _FakeDB(row=_Row())
    monkeypatch.setattr(
        stream_mod,
        "commit_with_retry",
        # _persist_risk_event stages the insert itself; the real
        # commit_with_retry never calls redo() on the success path, so the
        # fake must not either (calling it here would double-count the add).
        lambda _db, stage, context=None: True,
    )

    result = _risk_result(score=77)
    result["acoustic_score"] = None  # anti-spoof unavailable (quota/degraded)

    stream_mod._persist_risk_event(db, "call-degraded", result)

    assert len(db.added) == 1
    event = db.added[0]
    assert event.acoustic_score is None          # explicit absence, not 0.0
    assert event.combined_risk_score == 77       # degraded risk still recorded
    assert event.call_id == "call-degraded"

