# SatyaVoice — Backend Scaffold

Real-time voice-cloning detection and adaptive impersonation prevention.
Built for the SIH problem statement on AI-driven voice integrity verification.

This scaffold implements the architecture from the prototype blueprint:
a WebSocket audio ingestion pipeline, a dual acoustic + intent risk engine,
policy enforcement (ALLOW / WARN / LOCK_VERIFY), a step-up verification flow,
and a privacy-preserving audit log (metadata only — **no raw audio is ever
written to disk**).

For deployment, the frontend expects `VITE_API_BASE_URL` and `VITE_WS_BASE_URL`,
while the backend reads the `VOICETRUST_*` environment variables defined in
[.env.example](.env.example).

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
│   ├── risk_engine.py           # Documented risk fusion (acoustic+intent+identity) -> policy
│   ├── parallel_inference.py    # Bounded concurrent fan-out: anti-spoof ∥ ASR ∥ speaker
│   ├── latency.py               # Per-stage timing + rolling p50/p95 stats
│   └── session_manager.py       # In-memory active-call state, ring buffers, TTL expiry
├── services/
│   ├── audio_processor.py       # Numpy ring buffer: 4.0s windows / 0.5s hop + legacy aliases
│   ├── codec_normalizer.py       # Codec families -> canonical mono float32 16 kHz (G.711, PCM; Opus/AMR capability-gated)
│   ├── vad.py                    # Silero VAD preprocessing stage (energy fallback when unavailable)
│   ├── ml_detector.py            # BaseVoiceDetector / MockVoiceDetector / LightweightMLVoiceDetector
│   ├── intent_analyzer.py        # Urgency/financial keyphrase scoring
│   └── speaker_vault.py         # Persistent ECAPA speaker identity vault (DB-backed)
├── models/schemas.py            # Pydantic request/response contracts
└── db/
    ├── database.py                # SQLite/PostgreSQL engine + session factory
    ├── migrations.py              # Append-only versioned migration runner
    └── models.py                  # sessions / risk_events / speaker_identities ORM tables
scripts/
├── smoke_test.py                 # In-process end-to-end test (no server needed)
└── demo_client.py                 # Real WebSocket client against a running server
```

## API surface

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/call/start` | Begin a call session, get a `call_id` + WS URL |
| WS | `/api/v1/call/{call_id}/stream` | Stream audio; receive live risk telemetry |
| GET | `/api/v1/call/{call_id}/risk` | Current score + full risk timeline |
| POST | `/api/v1/call/action` | Attempt a sensitive action; **403 if locked** |
| POST | `/api/v1/call/{call_id}/terminate` | End the call, flush audit record |
| POST | `/api/v1/verification/request` | Issue a time-limited step-up challenge |
| POST | `/api/v1/verification/challenge` | Submit a step-up code to unlock a locked call |
| POST | `/api/v1/audio/analyze` | One-shot classification of an uploaded sample |

Full interactive docs at `/docs` once the server is running.

## Audio pipeline (SIH specification)

The ingestion path implements the presentation spec exactly:

```
wire bytes ──▶ codec normalization ──▶ rolling ring buffer ──▶ Silero VAD gate ──▶ detector / speaker / ASR
              (mono float32 16 kHz)    (4.0 s window,         (skip inference on
                                        0.5 s hop)             complete silence)
```

* **Canonical format**: mono · float32 · 16 kHz · normalized to [-1, 1].
* **Windowing**: 4.0-second windows (`WINDOW_SAMPLES = 64000`) advancing on an
  exact 0.5-second hop (`HOP_SAMPLES = 8000`). All constants live in
  `app/config.py` — the single source of truth.
* **Codecs**: PCM float32 (browser default), PCM s16le, G.711 μ-law and A-law
  decode natively. Opus requires `opuslib` + native libopus; AMR-NB/WB require
  a native AMR decoder binding. Unsupported codecs are reported honestly via
  `describe_capabilities()` and rejected with WS close code 4402 — never
  silently mis-decoded. Negotiate per connection by sending
  `{"codec": "g711_ulaw", "sample_rate": 8000}` as a text frame.
* **VAD**: Silero VAD is enabled by default (`VOICETRUST_VAD_ENABLED=true`)
  and evaluates every window. Windows with no speech skip detector/speaker/ASR
  inference but keep feeding the buffer, and telemetry carries
  `vad_active` / `vad_coverage` / `vad_backend`. If the `silero-vad` package
  or torch is unavailable, a documented energy-threshold fallback is used
  instead of silently disabling the stage.
* **Demo mode**: the mock detector bypasses the VAD gate so the deterministic
  `force_acoustic_score` scenarios keep working without a microphone.

## How the risk score is computed

Risk fusion is a documented convex combination (all weights in
`RiskFusionConfig`, `app/config.py`; weights sum to exactly 1.0):

```
R_total  = 100 * (Wa*A + Wi*I + Wm*M)
M        = max(0, 1 - s)        # identity mismatch
s        = speaker similarity vs the ENROLLED reference
A        = anti-spoof acoustic score (Wav2Vec2 / mock)
I        = intent score; forced to 1.0 when a transactional hard trigger
           (OTP/UPI/transfer phrase family) fires with max(A, I) >= 0.10

Defaults: Wa=0.60, Wi=0.30, Wm=0.10, WARN<=40, LOCK<=70
Policy:   ALLOW  if R <= 40
          WARN   if 40 < R <= 70
          LOCK_VERIFY if R > 70 (hard trigger forces LOCK_VERIFY)
```

**Directional contract**: speaker similarity measures how well the live
audio matches the *enrolled* caller. High similarity = identity CONSISTENT =
low risk. Only a LOW similarity WITH a reference enrolled (an identity
mismatch) raises risk. With no reference enrolled, identity evidence is
neutral (`M = 0`) — it is never treated as fraud. Tests enforce this
(`tests/test_risk_fusion.py`).

**Degradation**: a failed model never crashes the stream. The stage degrades
to uninformative evidence (anti-spoof 0.5 prior, identity neutral, ASR
skipped), the fusion adds a small documented penalty
(`DEGRADED_FUSION_PENALTY`), and telemetry flags `degraded: {stage: reason}`.

### Parallel inference and latency

The three per-window models run concurrently on a bounded executor (laned so
a model never races itself), with per-stage timeouts:

```
4-second window ──┬──▶ anti-spoof (Wav2Vec2 / mock)
                  ├──▶ faster-whisper ASR
                  └──▶ ECAPA speaker embedding
                        │
                        ▼ risk fusion
```

Every telemetry frame carries `latency_ms` (per-stage timings for codec,
VAD, anti-spoof, ASR, speaker, fusion, and total decision) and
`latency_stats` (rolling p50/p95 per stage). The sub-500 ms requirement is a
target to be *measured*, not claimed: in mock mode the observed decision
total p50 is ~5 ms; real-model latencies depend on the checkpoint and device
and must be benchmarked on target hardware.

## Target stack alignment

The presentation stack for SatyaVoice is:

- Anti-spoofing: fine-tuned Wav2Vec2-XLS-R (300M)
- ASR: faster-whisper small
- Speaker embedding: ECAPA-TDNN
- Voice activity: Silero VAD
- Dataset: IndicSpoof v0

The current codebase now reflects that target on the configuration and runtime
contract level, while keeping the tuned detector checkpoint itself as a future
handoff item.

## Detector modes

`VOICETRUST_DETECTOR_MODE` env var controls which detector `get_detector()`
returns:

- `mock` (default) — deterministic scores. Safe for local development and
  deployment preparation; supports a `force_acoustic_score` hook over the
  WebSocket so the demo can trigger cloned-voice scenarios without depending
  on a live microphone.
- `real` — the runtime is prepared to load a real audio anti-spoof checkpoint.
  The target production stack for the presentation is a fine-tuned
  Wav2Vec2-XLS-R (300M) classifier. Until that tuned checkpoint is available,
  the current code still uses the existing default public model value as a
  placeholder and should not be treated as the final production detector.
- `ml` — legacy classical feature extraction + a trained scikit-learn
  classifier, retained for compatibility but not part of the presentation
  target stack.

All detector implementations use the same `BaseVoiceDetector.predict()`
contract, so the risk engine and streaming path do not change when modes are
swapped.

## Automatic transcription (SIH multilingual target)

faster-whisper is loaded **once per process** via a singleton manager
(`app/services/asr.py`): thread-safe lazy initialization on first real use,
no per-request reloads, failures recorded and retried on the next call — a
missing checkpoint never crashes a WebSocket (the ASR lane degrades to an
evidence-neutral empty transcript).

Language policy (`VOICETRUST_ASR_LANGUAGE_POLICY`, default `auto`): no
language is forced globally — Whisper auto-detects per window, clients may
send `{"language": "hi"}` hints per call, and the detected/requested language
is exposed per window in telemetry (`detected_language`). The six SIH target
languages are registered in `config.SIH_TARGET_LANGUAGES`; "Indian English"
is represented as `en` (display name "English (Indian English)") — no
fabricated locale identifiers.

Tuning: `VOICETRUST_ASR_MODEL_SIZE` (default `small`), `VOICETRUST_ASR_COMPUTE_TYPE`
(int8), `VOICETRUST_ASR_DEVICE`, `VOICETRUST_ASR_BEAM_SIZE`, and
`VOICETRUST_ASR_VAD_FILTER`. ASR runs on its own lane in the parallel fan-out,
so its latency is measured separately in `latency_ms.asr` and never blocks
acoustic/speaker inference.

### Contextual intent evidence

Every matched risk signal becomes a structured `IntentRisk` object surfaced
in telemetry (`intent_risks`) and in the dashboard's conversation-context
panel:

```json
{
  "category": "otp",            // otp | upi | amount | urgency
  "confidence": 0.85,
  "evidence": "OTP phrase matched in a transaction context (en)...",
  "matched_phrase": "share the otp",
  "language": "en",
  "severity": "critical",       // info | elevated | critical
  "speech_act": "transaction",  // mention | request | instruction | transaction
  "window_index": 7,
  "timestamp": 1789160656.5
}
```

**False-positive control (mention vs request):** deterministically detected
request markers (send/share/give/tell-me equivalents across all six
languages) distinguish an actionable ask from a bare mention. Mentioning
"OTP" scores mildly (severity `info`, below the hard-trigger floor); an
OTP *request* is a `critical` transaction intent that locks the call.
Rupee amounts (`₹50,000`, "2 lakh", "5 crore rupees", plus Indic currency
words) are detected language-independently. Romanized/transliterated
variants ("otp bhejo", "paisa transfer karo", "taka pathao") are matched via
a dedicated transliteration layer. The deterministic rules are the safety
net; the structured `IntentRisk` contract is designed so a semantic intent
classifier can be added later as an additional evidence provider without
changing the fusion or the frontend.

## Automatic transcription

Set `VOICETRUST_ASR_MODE=real` to enable lazy faster-whisper transcription in
the WebSocket pipeline. The default remains `manual`, which preserves the
deterministic demo and accepts transcript text from the client. Configure:

```text
VOICETRUST_ASR_MODE=real
VOICETRUST_ASR_MODEL_SIZE=small
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

- **ASR/transcription**: real mode uses faster-whisper small; manual mode remains
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

## Phase 9 — On-device inference (Cloud / Hybrid / Edge modes)

The ONNX anti-spoof model can run fully in the browser across three explicit
modes, chosen at call start:

| Mode | Raw audio | Anti-spoof | ASR / speaker / policy |
|---|---|---|---|
| **Cloud** | streamed to backend | backend (Wav2Vec2/mock) | backend — full pipeline |
| **Hybrid** | streamed to backend | **browser (ONNX, worker)** | backend — full pipeline |
| **Edge/local** | **never leaves the device** | **browser (ONNX, worker)** | **explicitly degraded** (unavailable offline) |

Implementation:

1. `python scripts/export_anti_spoof_onnx.py` exports the
   `Hemgg/Deepfake-audio-detection` checkpoint to `public/models/`.
2. `public/onnx-worker.js` runs inference in a **Web Worker** — the model
   loads lazily once per session (idempotent; a failed load is retryable),
   never blocks the UI thread, and reports `loadMs` / per-inference latency.
3. `src/lib/localInference.ts` windows mic audio on the exact canonical
   contract (4.0 s window / 0.5 s hop @ 16 kHz) and exposes
   acoustic score + model id + inference duration + mode in the dashboard.
4. **Edge privacy guarantee:** in edge mode the frontend never opens the
   raw-audio WebSocket and never calls `ws.send()` with audio; only local
   results exist. Capabilities that require the backend (transcript,
   speaker identity, policy fusion) are labeled degraded in the UI rather
   than silently streaming audio.

Current offline limitations (explicit, not hidden): the edge mode covers the
anti-spoof model only — speaker verification needs an enrolled reference
vector (server-side vault), ASR needs the whisper checkpoint, and policy
fusion runs server-side. A fully offline mode would require shipping those
models/weights to the device.

Tests: `npm test` (Vitest) covers mode gating, WS send policy (edge can
never transmit audio), model load failure/retry, repeated inference,
telemetry metrics, teardown/reset, and mic-permission failure.

Android SDK scaffolding is explicitly deferred as roadmap work. We are not
attempting to build the Android wrapper or native SDK layer in this repository
unless you ask for that separately.

## Speaker identity vault (persistent, versioned, privacy-aware)

Enrollments are no longer process-memory only. `SpeakerVault` persists
ECAPA-TDNN speaker identities through SQLAlchemy, so a restart (or a second
worker) sees the same vault — the explicit SIH "cross-session vault"
requirement.

### Schema

| Table | Contents |
|---|---|
| `speaker_identities` | One row per enrolled speaker: `(tenant_id, speaker_id)` unique, `display_name`, model provenance (`model_identifier`, `model_version`, `normalization`, `embedding_dimension`), the aggregated `centroid_embedding`, `enrollment_sample_count`, `enrollment_version`, soft-delete state (`is_active`, `deleted_at`), timestamps |
| `speaker_enrollment_samples` | One DERIVED embedding per sample (float32 bytes), `embedding_dimension`, `model_version`, non-biometric quality metadata (RMS/peak), active flag |
| `schema_migrations` | Versioned migration history (append-only) |

PostgreSQL path: set `VOICETRUST_DATABASE_URL` to a `postgresql://` URL — the
schema is portable. Embeddings are stored as float32 byte blobs (BYTEA),
exactly the layout pgvector expects, so adopting pgvector later is a schema
*addition*, not a data rewrite.

Migrations: the repo uses a minimal append-only runner
(`app/db/migrations.py`, applied automatically inside `init_db()` at startup)
instead of Alembic — each schema change is an explicit, reviewable entry that
is applied exactly once per database.

### Embedding lifecycle

```
enroll    window → ECAPA embedding (SpeechBrain; deterministic labeled
          fallback when unavailable) → L2 normalize → insert sample row
          → centroid = L2-renormalized mean of active samples (robust
          aggregation, never blind replacement) → enrollment_version++
verify    live 4 s window → embedding with the SAME encoder signature →
          cosine vs centroid → similarity, threshold, match/no-match,
          model_version returned
revoke    soft delete (is_active=false) or hard erase (GDPR-style)
```

Version gating: a similarity is computed **only** when the stored identity's
`(model_identifier, model_version, normalization, embedding_dimension)`
matches the runtime encoder. After an encoder upgrade, unmatched identities
report `model_version_mismatch: true` instead of producing a meaningless
score, and a fresh enrollment starts a new representation under the current
encoder. Configurable knobs (all in `app/config.py`): `VOICETRUST_SPEAKER_MATCH_THRESHOLD`,
`VOICETRUST_SPEAKER_MODEL_VERSION`, `VOICETRUST_SPEAKER_EMBEDDING_NORMALIZATION`,
`VOICETRUST_SPEAKER_ENROLLMENT_AGGREGATION`, `VOICETRUST_SPEAKER_MAX_ENROLLMENT_SAMPLES`.

### API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/speaker/enroll` | Create identity or add enrollment sample (JSON: `speaker_id`, optional `tenant_id`, `display_name`) |
| POST | `/api/v1/speaker/match` | Verify a window (multipart audio + optional `tenant_id`, `speaker_id`) → similarity/threshold/match/model_version |
| GET | `/api/v1/speaker/speakers` | List identities (metadata only) |
| DELETE | `/api/v1/speaker/{speaker_id}` | Revoke (soft) or erase (`hard=true`) |
| GET | `/api/v1/speaker/status` | Vault state, method, model version |

### Privacy properties

* Raw voice is **never** persisted — only derived embeddings and RMS/peak
  quality metadata.
* Embeddings are never logged and never appear in any API response (only
  dimensions, versions, counts, similarities).
* Stored biometric data is bounded (`SPEAKER_MAX_ENROLLMENT_SAMPLES`, oldest
  pruned) and revocable per identity.

## Privacy by design

Raw audio only ever exists in a volatile in-memory ring buffer
(`services/audio_processor.py`) and is discarded once a window is processed.
Only derived metadata — scores, timestamps, triggered rules — reaches
SQLite (`db/models.py`), matching the Privacy and Compliance requirements in
the problem statement.
