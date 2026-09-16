"""Regression tests for the batch audio analysis score boundary."""
from __future__ import annotations

import asyncio
from io import BytesIO
from unittest import mock

import numpy as np
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

# The endpoint creates its detector at module import time.  Keep these unit
# tests independent of production-only ZeroGPU configuration; individual tests
# replace the detector with the scenario under test.
import os
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")

from app.api.v1 import analyze


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