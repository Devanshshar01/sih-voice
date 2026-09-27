"""F2 — lazy detector construction: import-time boot safety (Phase 1 blocker).

Importing ``app.main`` (and therefore ``uvicorn app.main:app``) must succeed
without a configured inference provider. Detector construction moved from
module import time to first use; a missing production configuration surfaces
as:

  * a structured WebSocket error frame + close 4403 (live stream), or
  * HTTP 503 DETECTOR_CONFIGURATION_UNAVAILABLE (batch /audio/analyze),

while ``config.validate_detector_config()`` (used by GET /ready) keeps
refusing an actually invalid production configuration — that gate is
unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-detector-boot-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

# Environment keys that force a specific inference provider configuration.
_DETECTOR_KEYS = (
    "HF_ZERO_GPU_SPACE",
    "HF_TOKEN",
    "VOICETRUST_DETECTOR_MODE",
    "INFERENCE_PROVIDER",
    "ENVIRONMENT",
    "VOICETRUST_ENVIRONMENT",
)


# ---------------------------------------------------------------------------
# 1. Import-time boot safety (subprocess: fresh interpreter, stripped env)
# ---------------------------------------------------------------------------


def test_import_app_main_without_detector_configuration():
    """``python -c 'import app.main'`` succeeds with no provider configured.

    Before F2 this crashed at import with:
      RuntimeError: ZeroGPU configuration missing: HF_ZERO_GPU_SPACE
    raised from the module-level ``detector = get_detector(...)`` in
    stream.py / analyze.py.
    """
    env = {k: v for k, v in os.environ.items() if k not in _DETECTOR_KEYS}
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main; print('IMPORT_OK')"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "IMPORT_OK" in proc.stdout


# ---------------------------------------------------------------------------
# 2. Request-path structured errors (in-process, monkeypatched constructor)
# ---------------------------------------------------------------------------


def _boom(*_args, **_kwargs):
    raise RuntimeError(
        "ZeroGPU configuration missing: HF_ZERO_GPU_SPACE is required"
    )


@pytest.fixture()
def broken_stream_detector(monkeypatch):
    from app.api.v1 import stream as stream_mod

    monkeypatch.setattr(stream_mod, "get_detector", _boom)
    monkeypatch.setattr(stream_mod, "_detector", None)
    yield stream_mod
    monkeypatch.setattr(stream_mod, "_detector", None)


def test_stream_reports_structured_config_error(broken_stream_detector):
    """Live stream: missing config -> error frame + close 4403, no crash."""
    from starlette.websockets import WebSocketDisconnect

    from app.core.ws_auth import create_access_token

    from app.main import app

    with TestClient(app) as client:
        caller = "boot-test-caller"
        start = client.post(
            "/api/v1/call/start",
            json={"caller_id": caller, "recipient_id": "bank"},
        )
        assert start.status_code == 200, start.text
        call_id = start.json()["call_id"]
        token = create_access_token(caller)

        with client.websocket_connect(
            f"/api/v1/call/{call_id}/stream?token={token}"
        ) as ws:
            frame = ws.receive_json()
            assert frame.get("error_code") == "DETECTOR_CONFIGURATION_UNAVAILABLE"
            assert "HF_ZERO_GPU_SPACE" in frame.get("error", "")
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 4403


def test_analyze_returns_structured_503(monkeypatch):
    """/audio/analyze: missing config -> 503 with a structured error body."""
    from app.api.v1 import analyze as analyze_mod

    monkeypatch.setattr(analyze_mod, "get_detector", _boom)
    monkeypatch.setattr(analyze_mod, "_detector", None)
    try:
        from app.main import app

        with TestClient(app) as client:
            raw = b"\x00\x00\x80\x3f" * 4000  # valid float32 mono buffer
            resp = client.post(
                "/api/v1/audio/analyze",
                files={"audio_file": ("sample.pcm", raw, "application/octet-stream")},
                data={"language": "en-IN"},
            )
            assert resp.status_code == 503, resp.text
            detail = resp.json()["detail"]
            assert detail["error_code"] == "DETECTOR_CONFIGURATION_UNAVAILABLE"
            assert "HF_ZERO_GPU_SPACE" in detail["error_message"]
            # No internal stack details leak.
            assert "Traceback" not in resp.text
    finally:
        analyze_mod._detector = None


# ---------------------------------------------------------------------------
# 3. Lazy construction semantics + historical module-attribute surface
# ---------------------------------------------------------------------------


def test_get_stream_detector_constructs_once(monkeypatch):
    from app.api.v1 import stream as stream_mod

    calls = {"n": 0}

    class _Stub:
        pass

    def _fake_get_detector(*_a, **_k):
        calls["n"] += 1
        return _Stub()

    monkeypatch.setattr(stream_mod, "get_detector", _fake_get_detector)
    monkeypatch.setattr(stream_mod, "_detector", None)
    try:
        first = stream_mod.get_stream_detector()
        second = stream_mod.get_stream_detector()
        assert first is second
        assert calls["n"] == 1
    finally:
        stream_mod._detector = None


def test_stream_module_attribute_surface_preserved():
    """stream.detector / _ACOUSTIC_CADENCE_ENABLED / _VAD_GATES_INFERENCE
    still resolve through PEP 562 __getattr__ (mock mode in tests)."""
    from app.api.v1 import stream as stream_mod
    from app.services.ml_detector import MockVoiceDetector

    assert isinstance(stream_mod.detector, MockVoiceDetector)
    assert stream_mod._ACOUSTIC_CADENCE_ENABLED is False  # mock -> per-window
    assert stream_mod._VAD_GATES_INFERENCE is False       # mock -> VAD bypassed


def test_analyze_module_attribute_surface_preserved():
    from app.api.v1 import analyze as analyze_mod
    from app.services.ml_detector import MockVoiceDetector

    assert isinstance(analyze_mod.detector, MockVoiceDetector)


def test_production_config_validation_still_refuses_invalid_config():
    """F2 must NOT weaken the production validation gate."""
    from app import config

    with pytest.raises(RuntimeError, match="MOCK|Mock"):
        config.validate_detector_config(
            {"ENVIRONMENT": "production", "VOICETRUST_DETECTOR_MODE": "mock"}
        )
    with pytest.raises(RuntimeError, match="HF_ZERO_GPU_SPACE"):
        config.validate_detector_config(
            {
                "ENVIRONMENT": "production",
                "VOICETRUST_DETECTOR_MODE": "zerogpu",
                # Explicit empty value: probes the gate, not the ambient env.
                "HF_ZERO_GPU_SPACE": "",
            }
        )
    # Valid production config still passes.
    assert (
        config.validate_detector_config(
            {
                "ENVIRONMENT": "production",
                "VOICETRUST_DETECTOR_MODE": "zerogpu",
                "HF_ZERO_GPU_SPACE": "spaces/me",
            }
        )
        == "zerogpu"
    )
