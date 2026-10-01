"""Regression tests for truthful production readiness semantics."""
from __future__ import annotations

import os

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "readiness-test-secret-abc123")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

from fastapi.testclient import TestClient

from app import config
from app import main


class _HealthySession:
    def execute(self, _query):
        return None

    def close(self):
        return None


class _UnavailableSession:
    def execute(self, _query):
        raise OSError("database unavailable; password=should-not-be-returned")

    def close(self):
        return None


def _patch_common(monkeypatch):
    monkeypatch.setattr(config, "validate_detector_config", lambda: None)
    monkeypatch.setattr(main, "validate_ws_auth_config", lambda: None, raising=False)


def test_ready_reports_healthy_required_production_dependencies(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(config, "PERSISTENCE_REQUIRED", True)
    monkeypatch.setattr(main, "SessionLocal", _HealthySession)

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database_status"] == "available"


def test_ready_returns_structured_503_when_required_database_is_unavailable(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(config, "PERSISTENCE_REQUIRED", True)
    monkeypatch.setattr(main, "SessionLocal", _UnavailableSession)

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 503
    body = response.json()["detail"]
    assert body == {
        "status": "not_ready",
        "error_code": "DATABASE_UNAVAILABLE",
        "dependency": "database",
        "required": True,
    }
    assert "password" not in response.text


def test_ready_marks_explicit_best_effort_database_failure_degraded(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(config, "PERSISTENCE_REQUIRED", False)
    monkeypatch.setattr(main, "SessionLocal", _UnavailableSession)

    response = TestClient(main.app).get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database_status"] == "unavailable"
    assert "password" not in response.text


def test_health_remains_liveness_check(monkeypatch):
    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
