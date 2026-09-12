"""Redis-backed session store race check: terminated calls cannot be unlocked.

Uses fakeredis to exercise the Redis code path of SessionManager where ended
sessions remain readable within TTL — the exact condition under which a stale
verification challenge could otherwise unlock a terminated call.
"""
import time

import pytest

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture()
def redis_mgr(monkeypatch):
    import app.core.session_manager as sm

    monkeypatch.setattr(sm, "SESSION_STORE_BACKEND", "redis")
    monkeypatch.setattr(sm, "REDIS_URL", "redis://fakeredis")
    mgr = sm.SessionManager.__new__(sm.SessionManager)
    mgr._sessions = {}
    mgr._active_streams = {}
    mgr._last_sync = {}
    mgr._ended = {}
    mgr._redis_available = True
    mgr._redis_client = fakeredis.FakeRedis(decode_responses=True)
    return mgr


class TestRedisTerminatedCallRace:
    def test_ended_session_readable_but_marked_ended(self, redis_mgr):
        s = redis_mgr.create_session("a", "b", tenant_id="t1")
        s.current_risk_score = 90
        redis_mgr.sync_session(s, force=True)
        redis_mgr.end_session(s.call_id, status="COMPLETED")

        # In Redis mode the payload survives within TTL...
        raw = redis_mgr._redis_client.get(f"call:{s.call_id}")
        assert raw is not None
        loaded = redis_mgr.get(s.call_id)
        # ...but the store marks it ended so authorization treats it as gone.
        assert loaded is None, "ended sessions must be treated as absent"
        assert s.call_id in redis_mgr._ended

    def test_challenge_endpoint_guards_on_status(self, redis_mgr, monkeypatch):
        """Direct guard check: a COMPLETED session must never reach verified=True."""
        import app.api.v1.verification as vmod

        s = redis_mgr.create_session("a", "b", tenant_id="t1")
        s.current_risk_score = 90
        redis_mgr.sync_session(s, force=True)
        # Manually write a COMPLETED payload (simulating terminate + TTL).
        s.status = "COMPLETED"
        redis_mgr.sync_session(s, force=True)

        monkeypatch.setattr(vmod, "session_manager", redis_mgr)

        vmod._active_challenges.clear()
        vmod._active_challenges[s.call_id] = {"code": "123456", "expires": time.time() + 300, "attempts": 0}
        # Submit the CORRECT code — without the status guard this would flip
        # the terminated session to verified=True in the store.

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            vmod.submit_challenge(
                type("P", (), {"call_id": s.call_id, "code": "123456"})(),
                auth=type("A", (), {"tenant_id": "t1"})(),
            )
        assert exc.value.status_code == 404
        # And the stored session was never flipped to verified.
        stored = redis_mgr._redis_client.get(f"call:{s.call_id}")
        assert '"verified": true' not in stored
