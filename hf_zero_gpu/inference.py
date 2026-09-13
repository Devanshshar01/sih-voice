"""
Inference logic for the SatyaVoice ZeroGPU Space.

Contract (SatyaVoice spec):
  * input:  a single 4-second mono audio window (any source sample rate,
            resampled here with a REAL resampler to 16 kHz)
  * output: spoof probability from the XLS-R anti-spoof model AND a real
            ECAPA-TDNN speaker embedding, computed inside ONE ZeroGPU
            invocation.

The public entry point `infer()` is decorated with @spaces.GPU so the
Hugging Face startup check ("No @spaces.GPU function detected") passes.

Models are loaded ONCE at module import (CPU) and moved to CUDA lazily on
the first GPU invocation; they are never reloaded per request.
"""
try:
    import spaces  # ZeroGPU: must be imported before torch/gradio
except ImportError:  # local dev / tests: `spaces` only exists on Hugging Face
    spaces = None

import importlib
import time

import numpy as np
import torch
import torchaudio
import torchaudio.functional as torchaudio_functional
from transformers import AutoModelForAudioClassification, Wav2Vec2FeatureExtractor

try:
    import speechbrain  # noqa: F401  (imported for version reporting only)
except ImportError:  # speechbrain installed via requirements on the Space
    speechbrain = None

from config import (
    ANTISPOOF_MODEL_ID,
    SPEAKER_MODEL_ID,
    SAMPLE_RATE,
    WINDOW_SECONDS,
    WINDOW_SAMPLES,
    DEVICE,
)

# Global model objects (loaded once at startup, on CPU)
_antispoof_processor = None
_antispoof_model = None
_speaker_model = None
_models_on_device = False


def _load_models():
    """Load XLS-R anti-spoof and ECAPA-TDNN models once (CPU at import)."""
    global _antispoof_processor, _antispoof_model, _speaker_model

    if _antispoof_model is None:
        print(f"Loading anti-spoof model (XLS-R): {ANTISPOOF_MODEL_ID}")
        _antispoof_processor = Wav2Vec2FeatureExtractor.from_pretrained(
            ANTISPOOF_MODEL_ID
        )
        _antispoof_model = AutoModelForAudioClassification.from_pretrained(
            ANTISPOOF_MODEL_ID
        )
        _antispoof_model.eval()
        print("Anti-spoof model loaded")

    if _speaker_model is None:
        print(f"Loading speaker model (ECAPA-TDNN): {SPEAKER_MODEL_ID}")
        # Real ECAPA-TDNN from SpeechBrain (not a placeholder). The
        # EncoderClassifier class has moved between SpeechBrain releases:
        #   - latest:   speechbrain.inference.classifiers
        #   - 1.0.x:    speechbrain.inference.interfaces
        #   - 0.5.x:    speechbrain.pretrained.interfaces
        # Resolve it dynamically so any installed version works; if none of
        # the known locations has it, fail loudly with the installed version
        # instead of a confusing ImportError.
        EncoderClassifier = None
        _last_import_error = None
        for _module_name in (
            "speechbrain.inference.classifiers",
            "speechbrain.inference.interfaces",
            "speechbrain.inference",
            "speechbrain.pretrained.interfaces",
            "speechbrain.pretrained",
        ):
            try:
                _module = importlib.import_module(_module_name)
                EncoderClassifier = getattr(_module, "EncoderClassifier", None)
                if EncoderClassifier is not None:
                    break
            except ImportError as _err:
                _last_import_error = _err
        if EncoderClassifier is None:
            raise ImportError(
                "EncoderClassifier not found in any known SpeechBrain "
                f"location (speechbrain version: "
                f"{getattr(speechbrain, '__version__', 'unknown')}); "
                f"last error: {_last_import_error}"
            )
        _speaker_model = EncoderClassifier.from_hparams(
            source=SPEAKER_MODEL_ID,
            savedir="pretrained_models/spkrec-ecapa-voxceleb",
        )
        print("ECAPA-TDNN speaker model loaded")


def _ensure_models_on_device():
    """Move models to the GPU once; subsequent calls are no-ops."""
    global _models_on_device
    if not _models_on_device:
        _antispoof_model.to(DEVICE)
        _speaker_model.to(DEVICE)
        _models_on_device = True

def _to_mono_float32(audio_data: np.ndarray) -> np.ndarray:
    """Return a 1-D float32 array."""
    audio_data = np.asarray(audio_data)
    if audio_data.dtype != np.float32:
        audio_data = audio_data.astype(np.float32)
    if audio_data.ndim > 1:
        audio_data = np.mean(audio_data, axis=1)
    return audio_data


def _resample(audio_data: np.ndarray, orig_sr: int) -> np.ndarray:
    """REAL resampling to SAMPLE_RATE using torchaudio (sinc interpolation).

    Truncation/padding is NOT resampling and is never used for rate
    conversion. Padding/truncation only happens afterwards, in
    _enforce_window, to hold the exact 4-second contract.
    """
    if int(orig_sr) != SAMPLE_RATE:
        audio_tensor = torch.from_numpy(audio_data).float()
        audio_tensor = torchaudio_functional.resample(
            audio_tensor, orig_freq=int(orig_sr), new_freq=SAMPLE_RATE
        )
        audio_data = audio_tensor.numpy()
    return audio_data


def _enforce_window(audio_data: np.ndarray) -> np.ndarray:
    """Pad or truncate to exactly WINDOW_SAMPLES (4 s @ 16 kHz = 64000)."""
    if len(audio_data) < WINDOW_SAMPLES:
        audio_data = np.pad(audio_data, (0, WINDOW_SAMPLES - len(audio_data)))
    elif len(audio_data) > WINDOW_SAMPLES:
        audio_data = audio_data[:WINDOW_SAMPLES]
    return audio_data


def _prepare_audio(audio) -> np.ndarray:
    """Convert arbitrary Gradio audio input to the 4 s / 16 kHz mono window."""
    if audio is None:
        raise ValueError("No audio provided")
    if isinstance(audio, (tuple, list)):
        sr, audio_data = audio
    else:
        audio_data = audio
        sr = SAMPLE_RATE
    audio_data = _to_mono_float32(audio_data)
    audio_data = _resample(audio_data, sr)
    return _enforce_window(audio_data)


def _spoof_label_index() -> int:
    """Index of the spoof/fake class in the anti-spoof model's labels."""
    id2label = getattr(_antispoof_model.config, "id2label", {}) or {}
    for index, label in id2label.items():
        text = str(label).lower()
        if any(k in text for k in ("spoof", "fake", "ai", "synthetic")):
            return int(index)
    return 0


def _run_inference(audio) -> dict:
    """Implementation body: XLS-R + ECAPA inside ONE GPU invocation."""
    start_time = time.time()

    _load_models()
    _ensure_models_on_device()
    audio_data = _prepare_audio(audio)

    # ---- XLS-R anti-spoof (Wav2Vec2 processor keeps sampling_rate=16000) ----
    inputs = _antispoof_processor(
        audio_data,
        sampling_rate=SAMPLE_RATE,
        return_tensors="pt",
        padding=True,
    )
    inputs = {key: value.to(DEVICE) for key, value in inputs.items()}

    with torch.inference_mode():
        logits = _antispoof_model(**inputs).logits
        probabilities = torch.softmax(logits, dim=-1)[0]

        # ---- ECAPA-TDNN speaker embedding (same GPU invocation) ----
        waveform = torch.from_numpy(audio_data).float().unsqueeze(0).to(DEVICE)
        embedding_tensor = _speaker_model.encode_batch(waveform)
        embedding = embedding_tensor.squeeze().cpu().numpy().astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

    inference_time_ms = (time.time() - start_time) * 1000

    return {
        "status": "ok",
        "spoof_probability": float(probabilities[_spoof_label_index()].item()),
        "speaker_embedding": [float(x) for x in embedding],
        "speaker_embedding_dim": int(embedding.shape[0]),
        "inference_time_ms": round(inference_time_ms, 2),
        "model_version_antispoof": ANTISPOOF_MODEL_ID,
        "model_version_speaker": SPEAKER_MODEL_ID,
        "sample_rate": SAMPLE_RATE,
        "duration_ms": round((len(audio_data) / SAMPLE_RATE) * 1000, 2),
    }


def _structured_error(exc: Exception) -> dict:
    """Structured error payload: Render backend marks inference unavailable.

    NOTE: deliberately contains NO spoof_probability fallback (no fake 0.5).
    """
    return {
        "status": "error",
        "error": {
            "type": type(exc).__name__,
            "message": str(exc),
        },
        "model_version_antispoof": ANTISPOOF_MODEL_ID,
        "model_version_speaker": SPEAKER_MODEL_ID,
        "sample_rate": SAMPLE_RATE,
    }


if spaces is not None:
    # Real ZeroGPU entry point: ONE @spaces.GPU call covering BOTH the
    # XLS-R anti-spoof pass and the ECAPA speaker embedding.
    @spaces.GPU
    def infer(audio) -> dict:
        """
        Run SatyaVoice inference (anti-spoof + speaker embedding) on one
        4-second / 16-kHz audio window.

        Raises ValueError on invalid input; unexpected runtime errors are
        returned as a structured error payload so the Render backend can
        mark inference unavailable (never a fake spoof_probability).
        """
        try:
            return _run_inference(audio)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid audio input: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - structured error to backend
            print(f"Inference error: {type(exc).__name__}: {exc}")
            return _structured_error(exc)
else:
    # Local fallback: `spaces` only exists on Hugging Face ZeroGPU. Same
    # behaviour, executed on CPU without the ZeroGPU decorator.
    def infer(audio) -> dict:
        try:
            return _run_inference(audio)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid audio input: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            print(f"Inference error: {type(exc).__name__}: {exc}")
            return _structured_error(exc)
