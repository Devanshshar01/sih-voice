# SatyaVoice Detector Model Card

## Target stack

The presentation target stack for SatyaVoice is:

- **Anti-spoofing:** `nii-yamagishilab/mms-300m-anti-deepfake` (MMS-300M-AntiDeepfake)
- **ASR:** faster-whisper `small`
- **Speaker embedding:** ECAPA-TDNN
- **VAD:** Silero VAD

## Active acoustic deepfake detector

- **Model ID:** `nii-yamagishilab/mms-300m-anti-deepfake`
- **Name:** MMS-300M-AntiDeepfake
- **Role:** acoustic speech deepfake / spoof detector
- **Base model:** `facebook/mms-300m` (Wav2Vec 2.0 architecture)
- **Architecture:** MMS-300M SSL front-end + fully connected binary
  classification head (per the official model card)
- **Input:** 16 kHz mono floating-point waveform (layer-normalized per the
  official inference example)
- **Output:** binary fake/real probabilities
  (`softmax(logits)[0]` = fake probability, `[1]` = real probability).
  SatyaVoice maps **fake probability → `acoustic_score`** so a higher score
  always means higher acoustic risk.
- **Source:** https://huggingface.co/nii-yamagishilab/mms-300m-anti-deepfake
- **License:** CC BY-NC-SA 4.0 (research/educational use), released by
  NII/Yamagishi Lab at the National Institute of Informatics, Japan. All model
  weights are the intellectual property of NII.

## Usage status

This is the **pretrained/post-trained AntiDeepfake checkpoint used
off-the-shelf**. SatyaVoice has NOT fine-tuned it, has NOT trained it, and has
NOT verified its performance on Indian languages, telephony audio, or
SatyaVoice-specific evaluation sets. SatyaVoice-specific fine-tuning is a
future task.

## Integration

The detector is implemented as `RealAntiSpoofDetector` in
`app/services/ml_detector.py` behind the existing `BaseVoiceDetector`
contract. Loading follows the official model card exactly:

- fairseq `Wav2Vec2Model` front-end (built from the documented
  `Wav2Vec2Config`) plus a fully connected head, packaged with
  `huggingface_hub.PyTorchModelHubMixin`.
- It is **not** loadable via `transformers.AutoModelForAudioClassification`
  (the checkpoint's HF config declares `Wav2Vec2ForPreTraining`).
- The model is loaded lazily once and reused for every 4-second analysis
  window; inference runs under `torch.inference_mode()` with `model.eval()`.

Configuration:

```text
VOICETRUST_DETECTOR_MODE=real
VOICETRUST_MODEL_ID=nii-yamagishilab/mms-300m-anti-deepfake
VOICETRUST_MODEL_DEVICE=cpu
VOICETRUST_MODEL_REVISION=main
VOICETRUST_MODEL_PATH=
```

`VOICETRUST_MODEL_PATH` can point to a local model directory. Otherwise,
`PyTorchModelHubMixin.from_pretrained` downloads the checkpoint from Hugging
Face on first inference and caches it locally. The checkpoint is several
hundred MB and is intentionally not committed to this repository.

Dependencies: the production path (`VOICETRUST_DETECTOR_MODE=remote_hf`, alias
`zerogpu`) calls the Hugging Face Space over `gradio-client` and does not load
MMS locally. Running the detector in-process needs `torch`, `fairseq==0.12.2`,
`hydra-core==1.0.7`, `omegaconf==2.0.6`, `safetensors`, `soundfile`, and
`huggingface-hub`, pinned per the official model card. The build-heavy
fairseq/hydra trio compiles native extensions and needs `g++`, so it is
deliberately kept out of the root `requirements.txt` that the Render image
installs; it lives in `hf_zero_gpu/requirements.txt` for the Space.
Known caveat: fairseq 0.12.2 predates NumPy 2; if the fairseq import fails
under NumPy 2, pin `numpy<2` (this does not affect the remote/zerogpu path).

## Streaming behavior

- 16 kHz mono float32 PCM windows (existing ring-buffer windowing, VAD, and
  codec normalization are unchanged).
- Every result carries `details.model`, `details.mode`, per-class
  `fake_probability` / `real_probability`, `predicted_label`, and
  `inference_latency_ms`.
- Empty audio, all-non-finite samples, inference exceptions, and model-load
  failures return a **degraded** result (`status: "degraded"`, neutral
  `acoustic_score` of 0.5 with an explicit `warning`/`error`), never a
  confident "genuine" verdict.

## Published evaluation (not measured by SatyaVoice)

The official model card reports the metrics below for the upstream model.
These are **NII's published numbers**, not SatyaVoice benchmarks, and must not
be presented as SatyaVoice results. SatyaVoice has not independently measured
accuracy, EER, calibration, latency, or language coverage for this
integration.

| Test Database | ROC AUC | EER (%) |
|---|---|---|
| ADD2023 | 0.977 | 7.93 |
| DeepVoice | 0.998 | 2.35 |
| FakeOrReal | 0.999 | 1.40 |
| In-the-Wild | 0.996 | 2.90 |
| Deepfake-Eval-2024 | 0.742 | 32.84 |

The model card also documents a Deepfake-Eval-2024 fine-tune (4s input:
0.9009 ROC AUC); that fine-tuned checkpoint is a separate release and is not
the checkpoint SatyaVoice uses.

## Data, limitations, and failure modes

The post-training set spans 56,370 hours of genuine and 18,280 hours of fake
speech across 100+ languages (see the official model card). SatyaVoice has
not measured this integration on:

- Indian-language and code-switched speech
- Telephony codecs, noisy contact-center audio, replay/re-recording attacks
- Unseen TTS / voice-conversion systems, overlapping speakers, clipping

Additional failure modes: probability calibration differences versus
SatyaVoice policy thresholds, and CPU inference latency on long or repeated
windows. No end-to-end latency claim is made.

## Licensing caution

CC BY-NC-SA 4.0 restricts commercial use. SatyaVoice's use of this checkpoint
is research/educational; any commercial deployment requires a separate
license decision from NII/Yamagishi Lab.

## Intended use

Local research, prototype evaluation, and risk-policy demonstration. This is
not a production fraud decision service and must not be treated as a
standalone identity or financial authorization mechanism.

## Reproducibility

1. Install `requirements.txt` in the project virtual environment, plus the
   fairseq/hydra runtime from `hf_zero_gpu/requirements.txt` (needed only for
   in-process `real` mode; the production remote path does not need it).
2. Set `VOICETRUST_DETECTOR_MODE=real`.
3. Run `python scripts/real_detector_check.py` (one inference, verified
   output structure, fake/real probabilities, no exception) or start the API.
4. Record the model ID, revision, device, input sample rate, and measured
   latency for every experiment.

No model weights or external dataset are committed to this repository.

## Browser/Edge detector identity

The browser ONNX Edge detector (`public/models/anti_spoof.onnx`) is a
separate artifact exported from a different checkpoint and is NOT the
MMS-300M-AntiDeepfake model. Cloud and Edge model identity remain
separately and truthfully reported in telemetry.

## ASR companion component

SatyaVoice optionally uses `faster-whisper` for transcription when
`VOICETRUST_ASR_MODE=real`. The project targets the `small` model with CPU
`int8` compute for the presentation stack. On the development machine,
a two-second silent window took approximately 2.89 seconds for `small`
inference, excluding the one-time model load. These measurements are local
CPU observations and do not establish production real-time performance.
