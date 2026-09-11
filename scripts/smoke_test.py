"""
Fast, dependency-light smoke test using FastAPI's TestClient -- no real
network, microphone, or running server required.

Run from the repo root with:
    python scripts/smoke_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.config import HOP_SAMPLES, WINDOW_SAMPLES

# With an 8,000-sample push exactly matching the hop size, the first window
# only becomes ready once the ring buffer reaches WINDOW_SAMPLES (4.0 s per
# the SIH spec) -- pushes before that produce no telemetry message, so we
# must not block on a receive_json() until we know a message is coming.
_FIRST_WINDOW_AT_PUSH = WINDOW_SAMPLES // HOP_SAMPLES  # 64000/8000 = 8


def _stream_silence_and_collect(ws, num_pushes: int, chunk_samples: int = HOP_SAMPLES) -> list:
    silence = np.zeros(chunk_samples, dtype=np.float32).tobytes()
    telemetry = []
    for i in range(1, num_pushes + 1):
        ws.send_bytes(silence)
        if i >= _FIRST_WINDOW_AT_PUSH:
            telemetry.append(ws.receive_json())
    return telemetry


def test_window_geometry_is_sih_canonical() -> None:
    """The backend must expose exactly the SIH windowing contract."""
    assert WINDOW_SAMPLES == 64000, "Window must be 4.0 s at 16 kHz"
    assert HOP_SAMPLES == 8000, "Hop must be 0.5 s at 16 kHz"


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200, r.text
    print("[ok] /health ->", r.json())


def test_genuine_call_stays_low_risk(client: TestClient) -> None:
    r = client.post(
        "/api/v1/call/start",
        json={"caller_id": "+91-9000000001", "recipient_id": "finance-desk-01"},
    )
    assert r.status_code == 200, r.text
    call_id = r.json()["call_id"]
    print(f"[ok] call started -> {call_id}")

    with client.websocket_connect(f"/api/v1/call/{call_id}/stream") as ws:
        ws.send_text('{"transcript": "Just checking on the quarterly budget report."}')
        telemetry = _stream_silence_and_collect(ws, num_pushes=10)[-1]
        print("[ok] final telemetry (genuine):", telemetry)
        assert telemetry["status"] == "ALLOW", "Genuine call should stay ALLOW"

    r = client.get(f"/api/v1/call/{call_id}/risk")
    assert r.status_code == 200, r.text
    print("[ok] risk snapshot:", r.json())


def test_cloned_voice_locks_action(client: TestClient) -> None:
    r = client.post(
        "/api/v1/call/start",
        json={"caller_id": "+91-9000000002", "recipient_id": "finance-desk-01"},
    )
    call_id = r.json()["call_id"]
    print(f"[ok] call started -> {call_id}")

    with client.websocket_connect(f"/api/v1/call/{call_id}/stream") as ws:
        ws.send_text(
            '{"transcript": "This is urgent, please approve the wire transfer immediately.", '
            '"force_acoustic_score": 0.9}'
        )
        telemetry = _stream_silence_and_collect(ws, num_pushes=10)[-1]
        print("[ok] final telemetry (cloned):", telemetry)
        assert telemetry["status"] == "LOCK_VERIFY", "Cloned-voice scenario should escalate to LOCK_VERIFY"
        assert telemetry["risk_score"] >= 70

    # Action should now be blocked with HTTP 403
    r = client.post(
        "/api/v1/call/action",
        json={"call_id": call_id, "action": "WIRE_TRANSFER", "amount": 50000},
    )
    assert r.status_code == 403, r.text
    print("[ok] action correctly blocked:", r.json())

    # Request + submit a verification challenge, then confirm the action unlocks.
    r = client.post("/api/v1/verification/request", json={"call_id": call_id})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    assert r.json()["expires_in_seconds"] == 60
    r = client.post("/api/v1/verification/challenge", json={"call_id": call_id, "code": code})
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    print("[ok] verification succeeded:", r.json())

    r = client.post(
        "/api/v1/call/action",
        json={"call_id": call_id, "action": "WIRE_TRANSFER", "amount": 50000},
    )
    assert r.status_code == 200 and r.json()["executed"] is True, r.text
    print("[ok] action unlocked after verification:", r.json())


if __name__ == "__main__":
    with TestClient(app) as client:  # triggers FastAPI lifespan -> init_db()
        test_health(client)
        test_window_geometry_is_sih_canonical()
        test_genuine_call_stays_low_risk(client)
        test_cloned_voice_locks_action(client)
    print("\nAll smoke tests passed.")
