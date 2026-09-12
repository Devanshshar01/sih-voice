# SatyaVoice Safe-to-Claim Status

Updated for the final integration audit (post Phase 10 hardening).

## Implemented

- Browser Web Audio API/AudioWorklet capture
- Float32 PCM WebSocket streaming
- Four-second sliding analysis windows with 0.5-second hops (SIH spec: 64,000-sample window / 8,000-sample hop at 16 kHz)
- Codec normalization layer: PCM float32/s16le and G.711 μ-law/A-law decode natively; Opus requires opuslib + native libopus; AMR-NB/WB require a native AMR binding and are reported as unsupported until installed
- Silero VAD preprocessing stage (enabled by default) with per-window speech-coverage telemetry and a documented energy-threshold fallback
- Mock detector behind `VOICETRUST_DETECTOR_MODE=mock`
- Current real-mode placeholder detector loading for `Hemgg/Deepfake-audio-detection`
- Target-stack runtime contract alignment for the presentation: fine-tuned
  Wav2Vec2-XLS-R (300M) anti-spoofing, faster-whisper `small`, Silero VAD,
  and ECAPA-TDNN speaker matching
- Existing acoustic + intent risk fusion
- `ALLOW`, `WARN`, and `LOCK_VERIFY` policy states
- Server-side sensitive-action blocking
- Verification request/challenge workflow
- SQLite derived-metadata audit events
- Detector mode/model metadata in streaming telemetry
- Optional faster-whisper ASR in the WebSocket pipeline when
	`VOICETRUST_ASR_MODE=real`
- Configurable Whisper language hints for Hindi, Bengali, Marathi, Tamil,
	Telugu, and English

## Implemented since the Phase 1 audit (with validation evidence)

- **On-device browser inference**: ONNX Runtime Web anti-spoof inference in a
  Web Worker (`public/onnx-worker.js`, `src/lib/localInference.ts`) with
  canonical 4 s / 0.5 s windowing, model-load state handling, and perf
  telemetry. Validated by 15 vitest cases (`src/tests/localInference.test.ts`).
  No accuracy benchmark for the exported ONNX checkpoint exists — the model
  is an export of the placeholder classifier, not the XLS-R 300M target.
- **Explicit audio modes**: cloud / hybrid / edge-local / demo (`src/types.ts`).
  Edge-local never opens the raw-audio WebSocket (enforced in
  `src/hooks/useCallSession.ts`); the capability is marked degraded rather
  than silently transmitting audio.
- **Persistent speaker vault**: DB-backed, version-gated ECAPA-TDNN
  enrollments with a clearly-labeled deterministic fallback encoder when
  SpeechBrain is unavailable (`app/services/speaker_vault.py`, tested in
  `tests/test_speaker_vault.py`). The fallback is NOT ECAPA — similarity
  scores from it are honest placeholders.
- **Production infrastructure**: PostgreSQL-required production mode,
  Redis-compatible session store, Celery for non-latency-critical jobs,
  rate limiting, request IDs, WS abuse caps, health/readiness endpoints
  (`app/config.py`, `app/core/*`, `docker-compose.yml`; tested in
  `tests/test_deployment.py`, `tests/test_hardening.py`,
  `tests/test_redis_race.py`). Redis/PostgreSQL paths are unit-tested via
  in-process/fakeredis substitutes — a live multi-worker deployment has not
  been exercised.
- **Forensic evidence layer**: canonical evidence packages (hashes only, no
  raw audio/transcripts), global append-only ledger with chain-of-custody
  verification, deterministic server-side PDF, tamper/chain-break/duplicate
  detection (`app/services/evidence_*.py`, `app/services/forensic_pdf.py`;
  tested in `tests/test_forensics.py`), plus an independent verifier CLI
  (`scripts/verify_evidence.py`).
- **Blockchain anchoring**: authorization-gated, append-only
  `AnchorRoot.sol` + Polygon Amoy adapter that degrades honestly when
  unconfigured. Adapter semantics are tested; **no live on-chain anchor has
  been executed** — treat on-chain behavior as NOT VERIFIED until a real
  Amoy transaction is demonstrated.
- **Measured latency instrumentation**: per-stage p50/p95 telemetry in every
  decision frame and `scripts/benchmark_latency.py`. Mock-mode measurement
  (dev CPU): server decision p50 ≈ 61 ms, p95 ≈ 102 ms. Real-model p95
  within 500 ms is NOT yet measured — that claim requires real-mode runs.

## Safe wording for the real detector

> SatyaVoice can run a pretrained Wav2Vec2 audio-classification checkpoint in real mode. The checkpoint is Apache-2.0 and its publisher reports 95.45% accuracy on its own evaluation set. SatyaVoice has not independently benchmarked this model on Indic languages, telephony audio, or unseen attacks yet.

## Not safe to claim yet

- Wav2Vec2-XLS-R specifically (the wired checkpoint is a wav2vec2-base placeholder)
- AASIST checkpoint running in SatyaVoice
- IndicSynth-trained performance
- Indian-language production accuracy
- EER, false-positive rate, or false-negative rate for SatyaVoice
- Sub-500 ms real-model end-to-end latency (mock-mode pipeline latency is measured; real-model runs are not)
- Opus or AMR decode in the default runtime (capability-gated with documented dependencies)
- ECAPA-TDNN accuracy claims: the vault code path and provenance gating are
  implemented and tested, but SpeechBrain/ECAPA is not installed in the dev
  runtime, so similarity quality is unmeasured (fallback encoder is in use)
- Android SDK
- Live multi-worker deployment against real PostgreSQL/Redis
- Live on-chain anchor on Polygon Amoy (adapter is tested; no real transaction)
- Legal admissibility certification (always a human/legal process; the PDF
  documents technical integrity only)
- Production bank or telecom integration

## ASR performance wording

On the development CPU, a two-second silent window measured approximately:

- faster-whisper `small`: 2.89 seconds inference after a 67.15 second load

These are local CPU measurements on a silent input, not production benchmarks.
The project is now configured to target `small` for the presentation stack, but
GPU and deployment benchmarks are still required before making a real-time
latency claim.

## Dataset and licensing caution

IndicSynth is a promising evaluation/fine-tuning source covering 12 Indian
languages, but its published license is CC BY-NC 4.0. Treat it as research-only
unless a separate license permits the intended use. No IndicSynth data is
currently included in or used by this repository.
