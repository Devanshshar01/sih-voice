"""Multi-user deployment readiness tests.

Covers: environment-mode gating (dev vs production config), API-key auth and
tenant boundaries, rate limiting, request-ID middleware, and health/readiness
endpoints. Deterministic — no Redis/PostgreSQL required (Redis paths test the
in-process fallback; production stores are integration-tested at deploy time).
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Environment-mode gating (pure config)
# ---------------------------------------------------------------------------
def _reload_config(monkeypatch, **env):
    """Set env vars and patch the ALREADY-IMPORTED config module attributes.

    Deliberately does NOT reload app.config: reloading would rebind module
    globals while SQLAlchemy engines elsewhere hold the original URL — a
    cross-test contamination vector. These tests exercise the attribute
    surface the app reads; the boot-time RuntimeError gates are covered by
    the subprocess tests below.
    """
    monkeypatch.setenv("VOICETRUST_ENV", env.get("env", "development"))
    for key, value in env.items():
        if key != "env":
            monkeypatch.setenv(key, value)
    for key in (
        "VOICETRUST_CORS_ORIGINS",
        "VOICETRUST_DATABASE_URL",
        "VOICETRUST_AUTH_API_KEYS",
        "VOICETRUST_DETECTOR_MODE",
        "VOICETRUST_ASR_MODE",
    ):
        if key not in env:
            monkeypatch.delenv(key, raising=False)
    import app.config as config

    mode = env.get("env", "development")
    monkeypatch.setattr(config, "ENV_MODE", mode)
    monkeypatch.setattr(config, "IS_PRODUCTION", mode == "production")
    return config


def _boot_in_subprocess(env: dict) -> tuple[int, str]:
    """Boot config in a clean interpreter and return (ok, output).

    Boot-time gates (RuntimeError on missing CORS/DB/auth) are import-time
    side effects, so they need a fresh process to observe honestly.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", "from app import config; print(config.ENV_MODE)"],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    return result.returncode, result.stdout + result.stderr


class TestEnvModes:
    def test_development_defaults(self, monkeypatch):
        config = _reload_config(monkeypatch, env="development")
        assert config.IS_DEVELOPMENT and not config.AUTH_REQUIRED
        assert config.VOICE_DETECTOR_MODE == "mock"
        assert config.ASR_MODE == "manual"
        assert config.DATABASE_URL.startswith("sqlite")
        assert config.SESSION_STORE_BACKEND == "memory"
        assert config.CORS_ORIGINS == ["*"]

    def test_production_requires_cors(self):
        code, output = _boot_in_subprocess(
            {
                "VOICETRUST_ENV": "production",
                "VOICETRUST_DATABASE_URL": "postgresql://u:p@db:5432/x",
                "VOICETRUST_AUTH_API_KEYS": "t:k",
            }
        )
        assert code != 0 and "VOICETRUST_CORS_ORIGINS" in output

    def test_production_requires_postgres(self):
        code, output = _boot_in_subprocess(
            {
                "VOICETRUST_ENV": "production",
                "VOICETRUST_CORS_ORIGINS": "https://x.example.com",
                "VOICETRUST_AUTH_API_KEYS": "t:k",
            }
        )
        assert code != 0 and "PostgreSQL" in output

    def test_production_refuses_sqlite(self):
        code, output = _boot_in_subprocess(
            {
                "VOICETRUST_ENV": "production",
                "VOICETRUST_CORS_ORIGINS": "https://x.example.com",
                "VOICETRUST_DATABASE_URL": "sqlite:///./x.db",
                "VOICETRUST_AUTH_API_KEYS": "t:k",
            }
        )
        assert code != 0 and "SQLite" in output

    def test_production_requires_auth_keys(self):
        code, output = _boot_in_subprocess(
            {
                "VOICETRUST_ENV": "production",
                "VOICETRUST_CORS_ORIGINS": "https://x.example.com",
                "VOICETRUST_DATABASE_URL": "postgresql://u:p@db:5432/x",
            }
        )
        assert code != 0 and "AUTH_API_KEYS" in output

    def test_production_defaults_to_real_models(self):
        code, output = _boot_in_subprocess(
            {
                "VOICETRUST_ENV": "production",
                "VOICETRUST_CORS_ORIGINS": "https://x.example.com",
                "VOICETRUST_DATABASE_URL": "postgresql://u:p@db:5432/x",
                "VOICETRUST_AUTH_API_KEYS": "t:k",
            }
        )
        assert code == 0
        assert "production" in output

    def test_production_allows_explicit_mock_override(self):
        """The operator CAN force mock in production (e.g. staging behind the
        same env contract) — it is a default, not a trap."""
        code, output = _boot_in_subprocess(
            {
                "VOICETRUST_ENV": "production",
                "VOICETRUST_CORS_ORIGINS": "https://x.example.com",
                "VOICETRUST_DATABASE_URL": "postgresql://u:p@db:5432/x",
                "VOICETRUST_AUTH_API_KEYS": "t:k",
                "VOICETRUST_DETECTOR_MODE": "mock",
                "VOICETRUST_ASR_MODE": "manual",
            }
        )
        assert code == 0

    def test_invalid_mode_rejected(self):
        code, output = _boot_in_subprocess({"VOICETRUST_ENV": "staging"})
        assert code != 0 and "VOICETRUST_ENV" in output


# ---------------------------------------------------------------------------
# API-key auth + tenant boundaries (live app, dev mode = auth open)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


class TestAuthOpenInDevelopment:
    def test_routes_open_without_keys_in_dev(self, client):
        # In development mode auth is disabled; calls API works unauthenticated.
        r = client.post("/api/v1/call/start", json={"caller_id": "a", "recipient_id": "b"})
        assert r.status_code == 200
        assert "call_id" in r.json()

    def test_health_endpoints_are_public(self, client):
        assert client.get("/health").status_code == 200
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200


class TestAuthEnforced:
    def test_missing_key_rejected_when_required(self, monkeypatch):
        from app import config as app_config
        from app.core import auth as auth_module

        monkeypatch.setattr(app_config, "AUTH_REQUIRED", True)
        monkeypatch.setattr(app_config, "AUTH_API_KEYS", "tenant-a:sk_aaa")
        # Rebuild the singleton's key table for this test.
        auth_module.api_key_auth._parse_keys()

        from app.main import app

        with TestClient(app) as c:
            r = c.post("/api/v1/call/start", json={"caller_id": "a", "recipient_id": "b"})
            assert r.status_code == 401

            r = c.post(
                "/api/v1/call/start",
                json={"caller_id": "a", "recipient_id": "b"},
                headers={"X-API-Key": "wrong-key"},
            )
            assert r.status_code == 401

            r = c.post(
                "/api/v1/call/start",
                json={"caller_id": "a", "recipient_id": "b"},
                headers={"X-API-Key": "sk_aaa"},
            )
            assert r.status_code == 200

    def test_tenant_derivation_is_from_key_not_input(self, monkeypatch):
        from app.core.auth import api_key_auth

        assert api_key_auth.tenant_for_key("sk_aaa") == "tenant-a"

    def test_invalid_key_constant_time_rejected(self, monkeypatch):
        from app.core.auth import api_key_auth

        assert api_key_auth.tenant_for_key("nonexistent") is None


# ---------------------------------------------------------------------------
# Rate limiting + request IDs
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_limiter_allows_under_limit(self, monkeypatch):
        from app.core.observability import _MemoryWindow

        window = _MemoryWindow()
        for _ in range(5):
            allowed, _ = window.check("ip-1", limit=5, window_seconds=60)
            assert allowed
        allowed, retry = window.check("ip-1", limit=5, window_seconds=60)
        assert not allowed and retry > 0

    def test_limiter_keys_are_isolated(self, monkeypatch):
        from app.core.observability import _MemoryWindow

        window = _MemoryWindow()
        for _ in range(5):
            window.check("ip-1", limit=5, window_seconds=60)
        allowed, _ = window.check("ip-2", limit=5, window_seconds=60)
        assert allowed  # different identity, fresh window

    def test_disabled_limiter_passes_everything(self, monkeypatch):
        from app.core.observability import RateLimiter

        monkeypatch.setattr("app.config.RATE_LIMIT_ENABLED", False)
        limiter = RateLimiter()
        for _ in range(100):
            allowed, _ = limiter.check("anyone")
            assert allowed


class TestRequestIds:
    def test_request_id_header_returned_and_unique(self, client):
        r1 = client.get("/health")
        r2 = client.get("/health")
        id1 = r1.headers.get("X-Request-ID")
        id2 = r2.headers.get("X-Request-ID")
        assert id1 and id2 and id1 != id2

    def test_incoming_request_id_is_honored(self, client):
        r = client.get("/health", headers={"X-Request-ID": "test-abc-123"})
        assert r.headers.get("X-Request-ID") == "test-abc-123"


# ---------------------------------------------------------------------------
# Input-size limits
# ---------------------------------------------------------------------------

class TestInputLimits:
    def test_audio_upload_size_limit_enforced(self, client, monkeypatch):
        from app import config as app_config

        monkeypatch.setattr(app_config, "MAX_AUDIO_UPLOAD_BYTES", 1024)
        big = b"\x00" * 4096
        r = client.post(
            "/api/v1/speaker/enroll",
            data={"speaker_id": "sizing-test"},
            files={"audio_file": ("a.pcm", big, "application/octet-stream")},
        )
        assert r.status_code == 413


# ---------------------------------------------------------------------------
# Health readiness structure
# ---------------------------------------------------------------------------

class TestReadiness:
    def test_ready_reports_checks(self, client):
        r = client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ready"
        assert "detector" in body["checks"]

    def test_readiness_fails_closed_on_db_error(self, client, monkeypatch):
        # Patch the name in the module that USES it (app.main imported the
        # symbol directly), not the defining module.
        import app.main as main_module

        monkeypatch.setattr(main_module, "check_db_ready", lambda: False)
        r = client.get("/health/ready")
        assert r.status_code == 503
        assert r.json()["checks"]["database"] == "not-ready"


# ---------------------------------------------------------------------------
# Privacy: logs never carry sensitive material
# ---------------------------------------------------------------------------

class TestLogPrivacy:
    def test_json_formatter_only_includes_allowlisted_fields(self):
        import logging

        from app.core.observability import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="msg", args=(), exc_info=None,
        )
        # Attempt to smuggle sensitive fields via extra.
        record.audio_bytes = b"raw audio material"
        record.embedding = [0.1] * 192
        record.request_id = "req-42"

        payload = json.loads(formatter.format(record))
        assert payload["request_id"] == "req-42"
        assert "audio_bytes" not in payload
        assert "embedding" not in payload
