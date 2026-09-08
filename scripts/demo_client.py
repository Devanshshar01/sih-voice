"""
Minimal CLI to exercise the running VoiceTrust backend without a frontend --
useful for a quick sanity check before wiring up the real dashboard.

Start the server first:
    uvicorn app.main:app --reload

Then run:
    python scripts/demo_client.py genuine   # Scenario A: routine call
    python scripts/demo_client.py cloned    # Scenario B: cloned-voice attack
"""
import asyncio
import json
import sys

import httpx
import numpy as np
import websockets

BASE_URL = "http://localhost:8000/api/v1"
WS_BASE = "ws://localhost:8000/api/v1"


async def run_scenario(scenario: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/call/start",
            json={
                "caller_id": "+91-9999900000" if scenario == "cloned" else "+91-9999911111",
                "recipient_id": "finance-desk-01",
            },
        )
        resp.raise_for_status()
        call_id = resp.json()["call_id"]
        print(f"Call started: {call_id}")

    uri = f"{WS_BASE}/call/{call_id}/stream"
    async with websockets.connect(uri) as ws:
        if scenario == "cloned":
            await ws.send(
                json.dumps(
                    {
                        "transcript": "This is urgent, please approve the wire transfer immediately.",
                        "force_acoustic_score": 0.9,
                    }
                )
            )
        else:
            await ws.send(json.dumps({"transcript": "Just checking on the quarterly budget report."}))

        chunk = np.zeros(8000, dtype=np.float32).tobytes()
        for _ in range(8):
            await ws.send(chunk)
            try:
                telemetry = await asyncio.wait_for(ws.recv(), timeout=2.0)
                print(telemetry)
            except asyncio.TimeoutError:
                continue


if __name__ == "__main__":
    scenario_arg = sys.argv[1] if len(sys.argv) > 1 else "genuine"
    asyncio.run(run_scenario(scenario_arg))
