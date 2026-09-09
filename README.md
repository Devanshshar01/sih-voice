# SatyaVoice — Backend Scaffold

Real-time voice-cloning detection and adaptive impersonation prevention.
Built for the SIH problem statement on AI-driven voice integrity verification.

This scaffold implements the architecture from the prototype blueprint:
a WebSocket audio ingestion pipeline, a dual acoustic + intent risk engine,
policy enforcement (ALLOW / WARN / LOCK_VERIFY), a step-up verification flow,
and a privacy-preserving audit log (metadata only — **no raw audio is ever
written to disk**).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

# Sanity-check the whole pipeline without a server or microphone:
python scripts/smoke_test.py

# Run the real API:
uvicorn app.main:app --reload

# Docs: http://localhost:8000/docs
# Health check: http://localhost:8000/health
```

With the server running, try the two demo scenarios from the prototype
blueprint against a real WebSocket:

```bash
python scripts/demo_client.py genuine   # Scenario A — Trust Index stays low
python scripts/demo_client.py cloned    # Scenario B — escalates to LOCK_VERIFY
```

Or with Docker:

```bash
docker compose up --build
```

## Project layout

```
app/
├── main.py                   # FastAPI instantiation, CORS, routing, lifespan (init_db)
├── config.py                 # Risk thresholds, fusion weights, audio windowing constants
├── api/v1/
│   ├── call.py                # Call lifecycle: start, risk snapshot, gated action, terminate
│   ├── stream.py               # WebSocket audio ingestion + real-time telemetry
│   ├── verification.py         # Out-of-band step-up challenge (simulated TOTP)
│   └── analyze.py              # Batch single-file analysis (judge/QA convenience)
├── core/
│   ├── risk_engine.py           # Weighted acoustic+intent fusion -> 0-100 score + policy
│   └── session_manager.py       # In-memory active-call state, ring buffers, TTL expiry
├── services/
│   ├── audio_processor.py       # PCM decode + sliding window (2.0s window / 0.5s hop)
│   ├── ml_detector.py            # BaseVoiceDetector / MockVoiceDetector / LightweightMLVoiceDetector
│   └── intent_analyzer.py        # Urgency/financial keyphrase scoring
├── models/schemas.py            # Pydantic request/response contracts
└── db/
    ├── database.py                # SQLite engine + session factory
    └── models.py                  # sessions / risk_events ORM tables
scripts/
├── smoke_test.py                 # In-process end-to-end test (no server needed)
└── demo_client.py                 # Real WebSocket client against a running server
```

## API surface

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/call/start` | Begin a call session, get a `call_id` + WS URL |
| WS | `/api/v1/call/{call_id}/stream` | Stream PCM audio; receive live risk telemetry |
| GET | `/api/v1/call/{call_id}/risk` | Current score + full risk timeline |
| POST | `/api/v1/call/action` | Attempt a sensitive action; **403 if locked** |
| POST | `/api/v1/call/{call_id}/terminate` | End the call, flush audit record |
| POST | `/api/v1/verification/request` | Issue a time-limited step-up challenge |
| POST | `/api/v1/verification/challenge` | Submit a step-up code to unlock a locked call |
| POST | `/api/v1/audio/analyze` | One-shot classification of an uploaded sample |

Full interactive docs at `/docs` once the server is running.

## How the risk score is computed

```
R_total = min(100, floor(0.55 * acoustic_score*100 + 0.45 * intent_score*100))
```

If a high-risk financial/urgency keyphrase is detected in the transcript,
`intent_score` is overridden to `1.0` — a genuinely urgent fraud attempt
can't be diluted by a calm-sounding voice. Thresholds: **0–39 ALLOW · 40–69
WARN · 70–100 LOCK_VERIFY** (configurable in `app/config.py`).

## Detector modes

`VOICETRUST_DETECTOR_MODE` env var controls which detector `get_detector()`
returns:

- `mock` (default) — deterministic scores. Safe for the
  live demo; supports a `force_acoustic_score` hook over the WebSocket so
  the judge-demo "backup audio injection" toggle can trigger the cloned-
  voice scenario without depending on a live microphone.
- `real` — a pretrained Wav2Vec2 audio-classification checkpoint loaded lazily
  from Hugging Face (`Hemgg/Deepfake-audio-detection`). Set
  `VOICETRUST_MODEL_ID`, `VOICETRUST_MODEL_DEVICE`, and optionally
  `VOICETRUST_MODEL_REVISION`. The checkpoint is Apache-2.0 and its model card
  reports 95.45% accuracy on its own audiofolder evaluation; this is not an
  independent SatyaVoice benchmark and is not IndicSynth-trained.
- `ml` — legacy classical feature extraction + a trained scikit-learn
  classifier, retained for compatibility but not used by the main Phase 1
  path.

All detector implementations use the same `BaseVoiceDetector.predict()`
contract, so the risk engine and streaming path do not change when modes are
swapped.

## Automatic transcription

Set `VOICETRUST_ASR_MODE=real` to enable lazy faster-whisper transcription in
the WebSocket pipeline. The default remains `manual`, which preserves the
deterministic demo and accepts transcript text from the client. Configure:

```text
VOICETRUST_ASR_MODE=real
VOICETRUST_ASR_MODEL_SIZE=base
VOICETRUST_ASR_DEVICE=cpu
VOICETRUST_ASR_COMPUTE_TYPE=int8
VOICETRUST_ASR_LANGUAGE=hi
```

Supported language codes are passed through to Whisper, including `hi`, `bn`,
`mr`, `ta`, `te`, and `en`. A client can also send a WebSocket text payload
such as `{"language":"hi"}`. Explicit `transcript` text takes precedence over
ASR for the current window. On the development CPU, `base` measured 1.69
seconds and `small` measured 2.89 seconds for two seconds of silent audio, so
`base` is the current default. These are local observations, not a sub-500 ms
production benchmark.

## What's intentionally stubbed for later phases

- **ASR/transcription**: real mode uses faster-whisper; manual mode remains
  available for deterministic demos and explicit transcript overrides.
- **Real TOTP/SMS delivery**: `verification.py` simulates the challenge
  in-process. Swap in Twilio Verify or an authenticator-app secret for
  anything beyond a demo.
- **WAV/MP3 decoding** in `/api/v1/audio/analyze`: currently assumes raw
  float32 PCM bytes for simplicity — add `soundfile`/`pydub` decoding before
  accepting arbitrary judge-supplied files.
- **Horizontal scaling**: `SessionManager` is an in-memory, single-process
  store — fine for the hackathon demo; move to Redis before running more
  than one worker.

The real detector downloads its checkpoint on first use unless
`VOICETRUST_MODEL_PATH` points to a local copy. The 378 MB checkpoint is not
committed to this repository.

## Phase 9 — On-device inference (scoped proof-of-concept)

This repository now includes a browser-side proof-of-concept for the anti-spoof
model:

1. Run `python scripts/export_anti_spoof_onnx.py` to export the real
   `Hemgg/Deepfake-audio-detection` checkpoint to ONNX and save the browser
   metadata bundle under `public/models/`.
2. The frontend loads `anti_spoof.onnx` through `onnxruntime-web` and runs a
   local inference pass over microphone frames in the browser.
3. Use the new `Browser-only ONNX inference (Phase 9 proof-of-concept)` mode
   in the UI to demonstrate detection in an airplane-mode-style offline flow.

Android SDK scaffolding is explicitly deferred as roadmap work. We are not
attempting to build the Android wrapper or native SDK layer in this repository
unless you ask for that separately.

## Privacy by design

Raw audio only ever exists in a volatile in-memory ring buffer
(`services/audio_processor.py`) and is discarded once a window is processed.
Only derived metadata — scores, timestamps, triggered rules — reaches
SQLite (`db/models.py`), matching the Privacy and Compliance requirements in
the problem statement.
