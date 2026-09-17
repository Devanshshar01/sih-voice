"""Regression tests for the batch audio analysis score boundary."""
from __future__ import annotations

import asyncio
from io import BytesIO
from unittest import mock

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

# The endpoint creates its detector at module import time.  Keep these unit
# tests independent of production-only ZeroGPU configuration; individual tests
# replace the detector with the scenario under test.
import os
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
import app.tasks as tasks
from app.api.v1 import analyze


_OK_DETECTOR = {
    "acoustic_score": 0.7482935,
    "success": True,
    "inference_available": True,
    "detector_status": "ok",
    "details": {
        "mode": "zerogpu",
        "model": "nii-yamagishilab/mms-300m-anti-deepfake",
        "model_version_antispoof": "nii-yamagishilab/mms-300m-anti-deepfake",
        "fake_probability": 0.7482935,
        "real_probability": 0.2517065,
    },
}


def _ok_detector():
    detector = mock.Mock()
    detector.predict.return_value = dict(_OK_DETECTOR)
    return detector


def _upload() -> UploadFile:
    return UploadFile(
        file=BytesIO(np.zeros(64000, dtype=np.float32).tobytes()),
        filename="sample.raw",
    )


def test_analyze_does_not_classify_missing_score() -> None:
    failed_detector = mock.Mock()
    failed_detector.predict.return_value = {
        "acoustic_score": None,
        "success": False,
        "inference_available": False,
        "detector_status": "unavailable",
        "error_code": "INFERENCE_UNAVAILABLE",
        "error_message": "HF Space unavailable",
        "details": {"mode": "zerogpu", "status": "unavailable"},
    }

    with mock.patch.object(analyze, "detector", failed_detector):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(analyze.analyze_audio(_upload()))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["error_code"] == "INFERENCE_UNAVAILABLE"
    assert "classification" not in exc_info.value.detail


def test_analyze_maps_live_mms_fake_probability_to_ai_generated() -> None:
    detector = mock.Mock()
    detector.predict.return_value = {
        "acoustic_score": 0.7482935,
        "success": True,
        "inference_available": True,
        "detector_status": "ok",
        "details": {
            "mode": "zerogpu",
            "model": "nii-yamagishilab/mms-300m-anti-deepfake",
            "model_version_antispoof": "nii-yamagishilab/mms-300m-anti-deepfake",
            "fake_probability": 0.7482935,
            "real_probability": 0.2517065,
        },
    }

    fake_task = mock.Mock()
    fake_task.id = "test-task"
    with (
        mock.patch.object(analyze, "detector", detector),
        mock.patch.object(analyze.generate_forensic_report, "delay", return_value=fake_task),
    ):
        response = asyncio.run(analyze.analyze_audio(_upload()))

    assert response.classification == "AI_GENERATED"
    assert response.confidence == pytest.approx(0.7483)
    assert "nii-yamagishilab/mms-300m-anti-deepfake" in response.explanation


@pytest.fixture
def audio_client():
    # Exercise the real HTTP router without unrelated DB/ML startup services.
    app = FastAPI()
    app.include_router(analyze.router, prefix="/api/v1")
    with mock.patch.object(analyze, "detector", _ok_detector()):
        with TestClient(app) as client:
            yield client


def _post_audio(client):
    return client.post(
        "/api/v1/audio/analyze",
        files={"audio_file": ("sample.raw", np.zeros(64000, dtype=np.float32).tobytes(), "application/octet-stream")},
    )


def _assert_analysis_ok(response):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["classification"] == "AI_GENERATED"
    assert body["confidence"] == pytest.approx(0.7483)
    assert body["spoof_probability"] == pytest.approx(0.7482935)
    assert body["fake_probability"] == pytest.approx(0.7482935)
    assert body["real_probability"] == pytest.approx(0.2517065)
    assert body["model_version_antispoof"] == _OK_DETECTOR["details"]["model"]
    return body


def test_celery_disabled_returns_200_without_queue(audio_client):
    with (
        mock.patch.object(analyze.config, "CELERY_ENABLED", False),
        mock.patch.object(analyze, "CELERY_AVAILABLE", True),
        mock.patch.object(analyze.generate_forensic_report, "delay") as delay,
    ):
        body = _assert_analysis_ok(_post_audio(audio_client))
    delay.assert_not_called()
    assert "generation disabled" in body["explanation"]
    assert "task queued" not in body["explanation"]


def test_celery_enabled_submits_background_task(audio_client):
    with (
        mock.patch.object(analyze.config, "CELERY_ENABLED", True),
        mock.patch.object(analyze, "CELERY_AVAILABLE", True),
        mock.patch.object(analyze.generate_forensic_report, "delay", return_value=mock.Mock(id="report-123")) as delay,
    ):
        body = _assert_analysis_ok(_post_audio(audio_client))
    delay.assert_called_once_with(
        call_id="batch-analysis",
        payload={"summary": "Batch analysis completed for sample.raw", "generated_at": None},
    )
    assert "Background task queued: report-123." in body["explanation"]


@pytest.mark.parametrize("error", [
    ConnectionRefusedError("Broker connection refused"),
    RuntimeError("Retry limit exceeded while trying to reconnect to the Celery result store backend"),
])
def test_celery_queue_failure_preserves_analysis_and_logs(audio_client, caplog, error):
    with (
        mock.patch.object(analyze.config, "CELERY_ENABLED", True),
        mock.patch.object(analyze, "CELERY_AVAILABLE", True),
        mock.patch.object(analyze.generate_forensic_report, "delay", side_effect=error) as delay,
        caplog.at_level("ERROR", logger=analyze.__name__),
    ):
        body = _assert_analysis_ok(_post_audio(audio_client))
    delay.assert_called_once()
    assert "generation unavailable" in body["explanation"]
    assert "task queued" not in body["explanation"]
    assert "Failed to queue optional forensic report" in caplog.text
    assert any(record.exc_info for record in caplog.records)


def test_celery_unavailable_skips_delay(audio_client, caplog):
    with (
        mock.patch.object(analyze.config, "CELERY_ENABLED", True),
        mock.patch.object(analyze, "CELERY_AVAILABLE", False),
        mock.patch.object(analyze.generate_forensic_report, "delay") as delay,
        caplog.at_level("WARNING", logger=analyze.__name__),
    ):
        body = _assert_analysis_ok(_post_audio(audio_client))
    delay.assert_not_called()
    assert "generation unavailable" in body["explanation"]
    assert "not configured or Celery is unavailable" in caplog.text


@pytest.mark.parametrize("enabled,broker,available", [
    (False, "redis://localhost:6379/0", False),
    (True, "", False),
    (True, "redis://queue:6379/0", True),
])
def test_celery_initialization_requires_opt_in_and_broker(enabled, broker, available):
    import runpy
    import sys

    celery_module = mock.Mock()
    with (
        mock.patch.object(analyze.config, "CELERY_ENABLED", enabled),
        mock.patch.object(analyze.config, "CELERY_BROKER_URL", broker),
        mock.patch.dict(sys.modules, {"celery": celery_module}),
    ):
        namespace = runpy.run_path(tasks.__file__)
    assert namespace["CELERY_AVAILABLE"] is available
    if available:
        celery_module.Celery.assert_called_once_with(
            "satyavoice", broker=broker, backend=analyze.config.CELERY_RESULT_BACKEND,
        )
    else:
        celery_module.Celery.assert_not_called()
