"""Final-gate hardening tests: WS auth, tenant binding, transcript gating.

Covers the Phase-10 audit fixes:
  * REST tenant binding — a tenant cannot see/gate/terminate another tenant's
    call (BOLA), including 404 indistinguishability.
  * Stream single-connection lock — a second WS to the same call is refused
    (4408) while the first holds it, and the lock is released on disconnect.
  * Transcript gating — client transcripts are honored in demo/development
    (ASR_MODE != "real") and rejected in production-real-ASR mode, so a
    client cannot spoof the intent-evidence channel.
  * Risk-event persistence throttle — writes fire on material change and at
    most every RISK_EVENT_MIN_INTERVAL_SECONDS (bounded DB churn).
"""

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def authed(monkeypatch):
    """Auth required, two tenants keyed; returns headers per tenant."""
    from app import config as app_config
    from app.core import auth as auth_module

    monkeypatch.setattr(app_config, "AUTH_REQUIRED", True)
    monkeypatch.setattr(app_config, "AUTH_API_KEYS", "tenant-a:sk_aaa,tenant-b:sk_bbb")
    auth_module.api_key_auth._parse_keys()

    def headers(tenant: str):
        return {"X-API-Key": {"a": "sk_aaa", "b": "sk_bbb"}[tenant]}

    return headers


def _start_call(client, headers):
    r = client.post("/api/v1/call/start", json={"caller_id": "x", "recipient_id": "y"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


# ---------------------------------------------------------------------------
# BOLA: calls are tenant-bound
# ---------------------------------------------------------------------------


class TestTenantBinding:
    def test_foreign_tenant_cannot_read_risk(self, client, authed):
        call_id = _start_call(client, authed("a"))
        r = client.get(f"/api/v1/call/{call_id}/risk", headers=authed("b"))
        assert r.status_code == 404  # indistinguishable from missing

    def test_owner_can_read_risk(self, client, authed):
        call_id = _start_call(client, authed("a"))
        r = client.get(f"/api/v1/call/{call_id}/risk", headers=authed("a"))
        assert r.status_code == 200

    def test_foreign_tenant_cannot_terminate(self, client, authed):
        call_id = _start_call(client, authed("a"))
        r = client.post(f"/api/v1/call/{call_id}/terminate", headers=authed("b"))
        assert r.status_code == 404
        # Owner still can.
        r = client.post(f"/api/v1/call/{call_id}/terminate", headers=authed("a"))
        assert r.status_code == 200

    def test_foreign_tenant_cannot_gate_action(self, client, authed):
        call_id = _start_call(client, authed("a"))
        r = client.post(
            "/api/v1/call/action", json={"call_id": call_id, "action": "WIRE_TRANSFER"}, headers=authed("b")
        )
        assert r.status_code == 404

    def test_call_persisted_with_tenant(self, client, authed, tmp_path):
        from app.core.session_manager import session_manager

        call_id = _start_call(client, authed("a"))
        assert session_manager.get(call_id).tenant_id == "tenant-a"


# ---------------------------------------------------------------------------
# WebSocket: auth + single connection per call
# ---------------------------------------------------------------------------


class TestStreamGuards:
    def test_second_connection_refused_while_first_active(self, client, authed):
        call_id = _start_call(client, authed("a"))
        base = f"/api/v1/call/{call_id}/stream"

        with client.websocket_connect(f"{base}?token=sk_aaa") as ws1:
            ws1.send_json({"codec": "pcm", "sample_rate": 16000, "channels": 1})
            # A second connection to the same call must be refused with 4408
            # (the connection is closed before accept, surfaced on enter).
            try:
                with client.websocket_connect(f"{base}?token=sk_aaa"):
                    pass
                second_opened = True
            except Exception:
                second_opened = False
            assert not second_opened, "second stream connection should be refused"

    def test_lock_released_after_disconnect(self, client, authed):
        call_id = _start_call(client, authed("a"))
        base = f"/api/v1/call/{call_id}/stream"
        with client.websocket_connect(f"{base}?token=sk_aaa") as ws1:
            ws1.send_json({"codec": "pcm"})
        # After the first client disconnects, a new connection must succeed.
        with client.websocket_connect(f"{base}?token=sk_aaa") as ws2:
            ws2.send_json({"codec": "pcm"})

    def test_missing_token_rejected_when_auth_required(self, client, authed):
        call_id = _start_call(client, authed("a"))
        try:
            with client.websocket_connect(f"/api/v1/call/{call_id}/stream"):
                pass
            opened = True
        except Exception:
            opened = False
        assert not opened, "unauthenticated stream must be refused"

    def test_wrong_tenant_token_rejected(self, client, authed):
        call_id = _start_call(client, authed("a"))
        try:
            with client.websocket_connect(f"/api/v1/call/{call_id}/stream?token=sk_bbb"):
                pass
            opened = True
        except Exception:
            opened = False
        assert not opened, "cross-tenant stream must be refused (BOLA)"

    def test_open_in_development_mode(self, client):
        # Development (auth disabled): stream connects without a token.
        call_id = _start_call(client, {})
        with client.websocket_connect(f"/api/v1/call/{call_id}/stream") as ws:
            ws.send_json({"codec": "pcm"})


# ---------------------------------------------------------------------------
# Transcript gating (client cannot spoof intent evidence in production)
# ---------------------------------------------------------------------------


class TestTranscriptGating:
    def test_demo_mode_accepts_client_transcript(self, monkeypatch):
        from app import config as cfg
        from app.api.v1.stream import _accept_client_transcript

        monkeypatch.setattr(cfg, "ASR_MODE", "manual")
        assert _accept_client_transcript() is True

    def test_real_asr_rejects_client_transcript(self, monkeypatch):
        from app import config as cfg
        from app.api.v1.stream import _accept_client_transcript

        monkeypatch.setattr(cfg, "ASR_MODE", "real")
        assert _accept_client_transcript() is False


# ---------------------------------------------------------------------------
# Risk-event persistence throttle (hot-path DB churn bound)
# ---------------------------------------------------------------------------


class TestRiskEventThrottle:
    def _db_and_state(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.db import models as db_models
        from app.db.database import Base

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        db.add(db_models.Session(call_id="c1", caller_id="a", recipient_id="b", tenant_id="t"))
        db.commit()
        return db, {"status": None, "score": -1, "t": 0.0}

    def _result(self, score, status):
        return {
            "risk_score": score,
            "status": status,
            "acoustic_score": 0.1,
            "intent_score": 0.2,
            "tenant_id": "t",
        }

    def test_writes_only_on_material_change(self, monkeypatch):
        from app.api.v1 import stream as stream_module

        monkeypatch.setattr(stream_module.time, "time", lambda: 1000.0)
        db, state = self._db_and_state()
        base = self._result(10, "SAFE")
        for _ in range(20):
            stream_module._persist_risk_event(db, "c1", base, state)
        assert db.query(stream_module.db_models.RiskEvent).count() == 1

    def test_status_flip_always_written(self, monkeypatch):
        from app.api.v1 import stream as stream_module

        monkeypatch.setattr(stream_module.time, "time", lambda: 1000.0)
        db, state = self._db_and_state()
        stream_module._persist_risk_event(db, "c1", self._result(10, "SAFE"), state)
        stream_module._persist_risk_event(db, "c1", self._result(20, "WARN"), state)
        stream_module._persist_risk_event(db, "c1", self._result(20, "WARN"), state)
        assert db.query(stream_module.db_models.RiskEvent).count() == 2

    def test_interval_elapsed_writes_even_without_change(self, monkeypatch):
        from app.api.v1 import stream as stream_module

        clock = {"t": 1000.0}
        monkeypatch.setattr(stream_module.time, "time", lambda: clock["t"])
        db, state = self._db_and_state()
        stream_module._persist_risk_event(db, "c1", self._result(10, "SAFE"), state)
        assert db.query(stream_module.db_models.RiskEvent).count() == 1
        clock["t"] += stream_module.RISK_EVENT_MIN_INTERVAL_SECONDS + 0.1
        stream_module._persist_risk_event(db, "c1", self._result(11, "SAFE"), state)
        assert db.query(stream_module.db_models.RiskEvent).count() == 2

    def test_updates_max_risk_and_tenant(self, monkeypatch):
        from app.api.v1 import stream as stream_module

        monkeypatch.setattr(stream_module.time, "time", lambda: 1000.0)
        db, state = self._db_and_state()
        stream_module._persist_risk_event(db, "c1", self._result(90, "LOCK_VERIFY"), state)
        row = db.query(stream_module.db_models.Session).filter_by(call_id="c1").first()
        assert row.max_risk_score == 90
        assert row.tenant_id == "t"


# ---------------------------------------------------------------------------
# Race-condition guard: terminated calls cannot be unlocked or act
# ---------------------------------------------------------------------------


class TestTerminatedCallRace:
    def _client(self):
        from app.main import app

        with TestClient(app) as c:
            yield c

    def test_challenge_cannot_unlock_terminated_call(self, client):
        from app import config as cfg
        from app.core.session_manager import session_manager

        r = client.post("/api/v1/call/start", json={"caller_id": "a", "recipient_id": "b"})
        call_id = r.json()["call_id"]
        session = session_manager.get(call_id)
        session.current_risk_score = 90  # high risk -> challenge permitted
        r = client.post("/api/v1/verification/request", json={"call_id": call_id})
        assert r.status_code == 200
        code = r.json()["code"]
        # Terminate, THEN submit the challenge response (the race).
        client.post(f"/api/v1/call/{call_id}/terminate")
        r = client.post("/api/v1/verification/challenge", json={"call_id": call_id, "code": code})
        assert r.status_code == 404
        assert session_manager.get(call_id) is None

    def test_terminated_call_cannot_execute_action(self, client):
        from app.core.session_manager import session_manager

        r = client.post("/api/v1/call/start", json={"caller_id": "a", "recipient_id": "b"})
        call_id = r.json()["call_id"]
        s = session_manager.get(call_id)
        s.verified = True  # was legitimately verified before termination
        client.post(f"/api/v1/call/{call_id}/terminate")
        r = client.post("/api/v1/call/action", json={"call_id": call_id, "action": "WIRE_TRANSFER"})
        # Memory store purges the session (404); Redis-backed store keeps it
        # read-only within TTL and hits the status guard (409). Either way the
        # action must NOT be executed.
        assert r.status_code in (404, 409)
