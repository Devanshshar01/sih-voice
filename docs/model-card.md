# SatyaVoice Real Detector Model Card

## Model

- **Model ID:** `Hemgg/Deepfake-audio-detection`
- **Architecture:** `Wav2Vec2ForSequenceClassification`
- **Base model:** `facebook/wav2vec2-base`
- **Labels:** `AIVoice` and `HumanVoice`
- **Sample rate:** 16 kHz
- **Checkpoint format:** Safetensors
- **License:** Apache-2.0, according to the Hugging Face model metadata
- **Source:** https://huggingface.co/Hemgg/Deepfake-audio-detection

## Integration

SatyaVoice loads the checkpoint lazily through `transformers` when
`VOICETRUST_DETECTOR_MODE=real`. The detector implements the existing
`BaseVoiceDetector` contract and returns an `acoustic_score` in `[0, 1]`, where
the score is the probability assigned to the model's `AIVoice` label.

Configuration:

```text
VOICETRUST_DETECTOR_MODE=real
VOICETRUST_MODEL_ID=Hemgg/Deepfake-audio-detection
VOICETRUST_MODEL_DEVICE=cpu
VOICETRUST_MODEL_REVISION=main
VOICETRUST_MODEL_PATH=
```

`VOICETRUST_MODEL_PATH` can point to a local model directory. Otherwise,
Transformers downloads the checkpoint from Hugging Face on first inference and
caches it locally. The checkpoint is approximately 378 MB and is intentionally
not committed to this repository.

## Published evaluation

The model metadata reports **95.45% accuracy** on its self-described
audiofolder evaluation set. This result is not independently verified by
SatyaVoice and must not be presented as a SatyaVoice benchmark, an EER result,
or a telephony/Indic-language result.

The official AASIST repository reports ASVspoof 2019 results of 0.83% EER for
AASIST and 0.99% EER for AASIST-L, but those are separate models and datasets;
SatyaVoice does not currently ship an AASIST checkpoint.

## Data and limitations

The Hugging Face card describes a multi-ethnic English audiofolder training and
evaluation setup. It does not establish performance on Indian languages,
telephony codecs, noisy contact-center audio, replay attacks, or unseen TTS
systems. SatyaVoice has not yet measured calibration, false-positive rate,
false-negative rate, EER, or latency for this integration.

IndicSynth is a useful future evaluation/fine-tuning dataset, but its published
license is **CC BY-NC 4.0**, which restricts commercial use. It must not be
used for a commercial training pipeline without a separate license decision.
It covers 12 Indian languages and contains synthetic audio plus metadata, but
using it here would require a separate data pipeline and evaluation protocol.

## Intended use

This integration is intended for local research, prototype evaluation, and
risk-policy demonstration. It is not a production fraud decision service and
must not be treated as a standalone identity or financial authorization
mechanism.

## Failure modes

- Distribution shift from English training data to Indic languages
- Telephony codec and bandwidth degradation
- Replay and re-recording attacks
- Unseen TTS or voice-conversion systems
- Background noise, music, clipping, and overlapping speakers
- Probability calibration differences between this checkpoint and SatyaVoice
  policy thresholds
- CPU inference latency on long or repeated windows

## Reproducibility

1. Install `requirements.txt` in the project virtual environment.
2. Set `VOICETRUST_DETECTOR_MODE=real`.
3. Run the focused detector check or start the API.
4. Record the model ID, revision, device, input sample rate, and measured
   latency for every experiment.

No model weights or external dataset are committed to this repository.

## ASR companion component

SatyaVoice optionally uses `faster-whisper` for transcription when
`VOICETRUST_ASR_MODE=real`. The current default is the `base` model with CPU
`int8` compute. On the development machine, a two-second silent window took
1.69 seconds for `base` inference versus 2.89 seconds for `small`, excluding
the one-time model load. These measurements are local CPU observations and do
not establish production real-time performance.
