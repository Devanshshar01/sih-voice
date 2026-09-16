---
title: SatyaVoice ZeroGPU Inference Space
emoji: 🤗
colorFrom: blue
colorTo: green
sdk: gradio
app_file: app.py
pinned: false
---

# SatyaVoice ZeroGPU Inference Space

This Hugging Face Space provides an API for anti-spoof detection and speaker embedding extraction, designed to be used by the SatyaVoice backend.

## What it does

The Space takes a 4-second mono audio window at 16kHz and returns:

- **spoof_probability**: Probability that the audio is spoofed == the model's **fake** probability (0.0 to 1.0)
- **fake_probability** / **real_probability**: the two class scores. The mapping is fixed by the checkpoint's documented output order `<Fake score, Real score>` (index 0 = fake, index 1 = real)
- **speaker_embedding**: Normalized embedding vector for speaker verification (to be compared with enrolled speaker embeddings in the backend)
- **inference_time_ms**: Time taken for inference on the GPU (in milliseconds)
- **model_version_antispoof**: Anti-spoof model identifier (the exact Hugging Face model ID)
- **model_version_speaker**: Speaker embedding model identifier
- **sample_rate**: Audio sample rate in Hz (16000)
- **duration_ms**: Duration of the audio window in milliseconds (4000)

## How to use

The Space exposes a Gradio API endpoint at `/api/predict/` that accepts:

- **audio**: A numpy array (or audio file) of shape `(n_samples,)` with dtype `float32`, mono, 16kHz, and exactly 4 seconds long (or it will be padded/truncated to 4 seconds).

It returns a JSON object with the fields listed above.

### Example usage with `gradio_client`

```python
from gradio_client import Client

client = Client("your-username/your-space-name")
result = client.predict(
    audio=your_audio_numpy_array,  # numpy array of audio samples
    api_name="/predict"
)
print(result)
```

## Models

| Role | Model | Notes |
|---|---|---|
| Anti-spoof (deepfake) | `nii-yamagishilab/mms-300m-anti-deepfake` | MMS-300M-AntiDeepfake (MMS-300M / Wav2Vec 2.0 front-end + fully connected binary head), NII / Yamagishi Lab, **CC BY-NC-SA 4.0**. Loaded with the official model-card path: fairseq `Wav2Vec2Config` + `Wav2Vec2Model` + `huggingface_hub.PyTorchModelHubMixin`. **Not** fine-tuned by SatyaVoice, and no accuracy figure is claimed for it. |
| Speaker embedding | `speechbrain/spkrec-ecapa-voxceleb` | ECAPA-TDNN; produces the normalized speaker embedding. |

Class order comes from the card's documented output `"<Fake score, Real score>"`:
index 0 = fake, index 1 = real (`config.FAKE_LABEL_INDEX` / `REAL_LABEL_INDEX`).
`spoof_probability` is therefore the **fake** probability — the same direction the
risk engine expects for `acoustic_score` (higher score = higher risk).

## Configuration

The following environment variables can be set to configure the models:

- `ANTISPOOF_MODEL_ID`: Hugging Face model ID for the anti-spoof model (default: `nii-yamagishilab/mms-300m-anti-deepfake`)
- `SPEAKER_MODEL_ID`: Hugging Face model ID for the speaker embedding model (default: `speechbrain/spkrec-ecapa-voxceleb`)

Only point `ANTISPOOF_MODEL_ID` at another checkpoint that keeps the same binary
`<fake, real>` output contract. SatyaVoice-specific fine-tuning is a separate
future task: until it is evaluated on a labelled dataset, no SatyaVoice accuracy
may be reported for this model.

## Model loading

Models are loaded exactly once (on the first GPU invocation) and stay resident in
the ZeroGPU worker; they are never reloaded or reconstructed per request. Failed
inference returns a structured error payload and **never** a fabricated score.

## Requirements

See `requirements.txt` for the exact versions. Note the vendored
`vendor/omegaconf-2.0.6-py3-none-any.whl`: pip >= 24.1 rejects the upstream
omegaconf 2.0.6 metadata that `fairseq==0.12.2` requires, so that wheel is
metadata-repaired in place (code unchanged). `vendor/README.md` documents the
change, the checksums and the reason a `pip<24.1` line cannot fix it.

## Local testing

To run the Space locally:

```bash
pip install -r requirements.txt
python app.py
```

Then, open the URL shown in the console (usually `http://127.0.0.1:7860`) and use the interface, or use the API endpoint.

## Notes

- The Space is designed to be used as a backend service and does not require a frontend.
- The audio input is expected to be preprocessed to 16kHz mono. The backend should handle resampling and channel conversion if necessary.
- The Space does not perform any speaker enrollment or verification; it only extracts embeddings. The backend is responsible for comparing embeddings to enrolled speakers.