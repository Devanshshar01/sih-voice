# SatyaVoice Safe-to-Claim Status

Updated for Phase 1 real detector integration.

## Implemented

- Browser Web Audio API/AudioWorklet capture
- Float32 PCM WebSocket streaming
- Four-second sliding analysis windows with 0.5-second hops (SIH spec: 64,000-sample window / 8,000-sample hop at 16 kHz)
- Codec normalization layer: PCM float32/s16le and G.711 μ-law/A-law decode natively; Opus requires opuslib + native libopus; AMR-NB/WB require a native AMR binding and are reported as unsupported until installed
- Silero VAD preprocessing stage (enabled by default) with per-window speech-coverage telemetry and a documented energy-threshold fallback
- Mock detector behind `VOICETRUST_DETECTOR_MODE=mock`
- Active real-mode acoustic deepfake detector:
  `nii-yamagishilab/mms-300m-anti-deepfake` (MMS-300M-AntiDeepfake,
  NII/Yamagishi Lab, CC BY-NC-SA 4.0), loaded via the official fairseq +
  PyTorchModelHubMixin path, used off-the-shelf (not fine-tuned by
  SatyaVoice; fine-tuning is a future task)
- Target-stack runtime contract alignment for the presentation:
  faster-whisper `small`, Silero VAD, and ECAPA-TDNN speaker matching
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

> SatyaVoice runs the pretrained MMS-300M-AntiDeepfake checkpoint
> (`nii-yamagishilab/mms-300m-anti-deepfake`) off-the-shelf as its acoustic
> speech deepfake/spoof detector. The model was post-trained for deepfake
> detection by NII/Yamagishi Lab and is used here under its CC BY-NC-SA 4.0
> license for research/educational purposes. SatyaVoice has not fine-tuned it
> and has not independently benchmarked it on Indic languages, telephony
> audio, or unseen attacks yet.

## Not safe to claim yet

- SatyaVoice fine-tuned or trained the MMS-300M-AntiDeepfake model
- Indian-language performance verified for the detector
- AASIST checkpoint running in SatyaVoice
- IndicSynth-trained performance
- Indian-language production accuracy
- EER, false-positive rate, or false-negative rate for SatyaVoice
- Sub-500 ms real-model end-to-end latency
- Opus or AMR decode in the default runtime (capability-gated with documented dependencies)
- ECAPA-TDNN speaker matching or cross-session vault
- On-device WebAssembly inference matching the cloud detector
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
