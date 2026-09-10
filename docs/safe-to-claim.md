# SatyaVoice Safe-to-Claim Status

Updated for Phase 1 real detector integration.

## Implemented

- Browser Web Audio API/AudioWorklet capture
- Float32 PCM WebSocket streaming
- Two-second sliding analysis windows with 0.5-second hops
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

## Safe wording for the real detector

> SatyaVoice can run a pretrained Wav2Vec2 audio-classification checkpoint in real mode. The checkpoint is Apache-2.0 and its publisher reports 95.45% accuracy on its own evaluation set. SatyaVoice has not independently benchmarked this model on Indic languages, telephony audio, or unseen attacks yet.

## Not safe to claim yet

- Wav2Vec2-XLS-R specifically
- AASIST checkpoint running in SatyaVoice
- IndicSynth-trained performance
- Indian-language production accuracy
- EER, false-positive rate, or false-negative rate for SatyaVoice
- Sub-500 ms real-model end-to-end latency
- Silero VAD
- ECAPA-TDNN speaker matching or cross-session vault
- On-device WebAssembly inference
- Android SDK
- PostgreSQL, Redis, or Celery production infrastructure
- Technical integrity evidence package for local/demo review only; legal admissibility certification remains a human/legal process
- Blockchain anchoring
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
