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

- **spoof_probability**: Probability that the audio is spoofed (0.0 to 1.0)
- **speaker_embedding**: Normalized embedding vector for speaker verification (to be compared with enrolled speaker embeddings in the backend)
- **inference_time_ms**: Time taken for inference on the GPU (in milliseconds)
- **model_version_antispoof**: Identifier of the anti-spoof model used
- **model_version_speaker**: Identifier of the speaker embedding model used
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

## Configuration

The following environment variables can be set to configure the models:

- `ANTISPOOF_MODEL_ID`: Hugging Face model ID for the anti-spoof model (default: `facebook/wav2vec2-xls-r-300m`)
- `SPEAKER_MODEL_ID`: Hugging Face model ID for the speaker embedding model (default: `speechbrain/spkrec-ecapa-voxceleb`)

Note: For production, you should set `ANTISPOOF_MODEL_ID` to your fine-tuned Wav2Vec2-XLS-R checkpoint.

## Model loading

The models are loaded once when the Space starts and are kept in memory for efficient inference.

## Requirements

See `requirements.txt` for the exact versions.

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