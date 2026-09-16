"""
Inference logic for the SatyaVoice ZeroGPU Space.

Contract (SatyaVoice spec):
  * input:  a single 4-second mono audio window (any source sample rate,
            resampled here with a REAL resampler to 16 kHz)
  * output: spoof probability from the MMS-300M-AntiDeepfake anti-spoof model
            AND a real ECAPA-TDNN speaker embedding, computed inside ONE
            ZeroGPU invocation.

Anti-spoof model: nii-yamagishilab/mms-300m-anti-deepfake
  * Architecture: MMS-300M (Wav2Vec 2.0) front-end + fully connected binary
    head, built exactly as the official model card documents: fairseq
    Wav2Vec2Config/Wav2Vec2Model + huggingface_hub.PyTorchModelHubMixin.
    It is NOT a transformers AutoModelForAudioClassification checkpoint --
    its config.json declares "Wav2Vec2ForPreTraining".
  * Output order (card): "<Fake score, Real score>", i.e.
    "real prob = prob[1], fake prob = prob[0]" -> FAKE = index 0, REAL = 1
    (see config.FAKE_LABEL_INDEX / config.REAL_LABEL_INDEX).
  * License: CC BY-NC-SA 4.0 (NII / Yamagishi Lab). Used off-the-shelf:
    SatyaVoice has NOT fine-tuned it and claims no accuracy figure for it.

The public entry point `infer()` is decorated with @spaces.GPU so the
Hugging Face startup check ("No @spaces.GPU function detected") passes.

Models are loaded ONCE (on the first GPU invocation) and stay resident in the
worker; they are never reloaded or reconstructed per request.
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

# PyTorchModelHubMixin is the checkpoint-loading mechanism the MMS-300M
# AntiDeepfake model card uses. fairseq is deliberately NOT imported at module
# scope (only the anti-spoof model needs it, and it is imported lazily inside
# SSLModel.__init__), so importing this module never requires the build-heavy
# fairseq/hydra runtime -- see hf_zero_gpu/requirements.txt.
from huggingface_hub import PyTorchModelHubMixin

try:
    import speechbrain  # noqa: F401  (imported for version reporting only)
except ImportError:  # speechbrain installed via requirements on the Space
    speechbrain = None

try:  # package import (Kaggle/local provider: `from hf_zero_gpu import inference`)
    from .config import (
        ANTISPOOF_MODEL_ID,
        SPEAKER_MODEL_ID,
        SAMPLE_RATE,
        WINDOW_SECONDS,
        WINDOW_SAMPLES,
        DEVICE,
        FAKE_LABEL_INDEX,
        REAL_LABEL_INDEX,
    )
except ImportError:  # Space runtime: app dir is on sys.path, flat import works
    from config import (
        ANTISPOOF_MODEL_ID,
        SPEAKER_MODEL_ID,
        SAMPLE_RATE,
        WINDOW_SECONDS,
        WINDOW_SAMPLES,
        DEVICE,
        FAKE_LABEL_INDEX,
        REAL_LABEL_INDEX,
    )

# Global model objects (loaded once, then resident for the worker's lifetime)
_antispoof_model = None
_speaker_model = None
_models_on_device = False


class SSLModel(torch.nn.Module):
    """MMS-300M front-end, built from the model card's `Wav2Vec2Config`.

    Defined at module scope exactly like the card, but the fairseq import
    happens inside __init__ so that merely importing this module (Render
    backend, unit tests, CI) never requires the fairseq/hydra runtime.
    """

    def __init__(self) -> None:
        super().__init__()
        try:
            from fairseq.models.wav2vec import Wav2Vec2Config, Wav2Vec2Model
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise ImportError(
                "The MMS-300M-AntiDeepfake checkpoint is loaded through "
                "fairseq (`from fairseq.models.wav2vec import Wav2Vec2Model, "
                "Wav2Vec2Config`) exactly as the official model card "
                "documents. Install hf_zero_gpu/requirements.txt (fairseq + "
                "the metadata-repaired omegaconf wheel) on the Space/GPU host; "
                "the Render remote_hf path does not need it."
            ) from exc

        # Model config used to build the SSL architecture (verbatim from the
        # official model card for MMS-300M-AntiDeepfake).
        cfg = Wav2Vec2Config(
            quantize_targets=True,
            extractor_mode="layer_norm",
            layer_norm_first=True,
            final_dim=768,
            latent_temp=(2.0, 0.1, 0.999995),
            encoder_layerdrop=0.0,
            dropout_input=0.0,
            dropout_features=0.0,
            dropout=0.0,
            attention_dropout=0.0,
            conv_bias=True,
            encoder_layers=24,
            encoder_embed_dim=1024,
            encoder_ffn_embed_dim=4096,
            encoder_attention_heads=16,
            feature_grad_mult=1.0,
        )
        # Random init here; the post-trained weights arrive via
        # PyTorchModelHubMixin.from_pretrained (see _load_models).
        self.model = Wav2Vec2Model(cfg)

    def extract_feat(self, input_data):
        """Feature extraction: [B, T] -> [B, T', D] (card behaviour)."""
        if input_data.ndim == 3:
            input_data = input_data[:, :, 0]
        with torch.no_grad():
            return self.model(input_data, mask=False, features_only=True)["x"]


class AntiDeepfakeDetector(torch.nn.Module, PyTorchModelHubMixin):
    """Card's `DeepfakeDetector`: SSL front-end + pooling + FC binary head.

    Logits are ordered <fake, real> per the card, so index 0 is the FAKE score
    and index 1 is the REAL score (config.FAKE_LABEL_INDEX/REAL_LABEL_INDEX).
    """

    def __init__(self) -> None:
        super().__init__()
        self.ssl_orig_output_dim = 1024
        self.num_classes = 2

        # Frontend: SSL model
        self.m_ssl = SSLModel()

        # Backend: pooling + classification (card structure)
        self.adap_pool1d = torch.nn.AdaptiveAvgPool1d(output_size=1)
        self.proj_fc = torch.nn.Linear(
            in_features=self.ssl_orig_output_dim,
            out_features=self.num_classes,
        )

    def forward(self, wav):
        emb = self.m_ssl.extract_feat(wav)              # [B, T', D]
        emb = emb.transpose(1, 2)                       # [B, D, T']
        pooled_emb = self.adap_pool1d(emb).squeeze(-1)  # [B, D]
        return self.proj_fc(pooled_emb)                 # [B, 2] = <fake, real>


def _load_models():
    """Load the MMS anti-spoof + ECAPA-TDNN models once, then keep them resident."""
    global _antispoof_model, _speaker_model

    if _antispoof_model is None:
        print(
            "Loading anti-spoof model (MMS-300M-AntiDeepfake): "
            f"{ANTISPOOF_MODEL_ID}"
        )
        # PyTorchModelHubMixin.from_pretrained loads the checkpoint's
        # safetensors weights into this architecture (strict): a real
        # post-trained head, never a randomly initialised classifier.
        _antispoof_model = AntiDeepfakeDetector.from_pretrained(
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


def _binary_probabilities(logits):
    """Return (fake_probability, real_probability) from the 2-class logits.

    The mapping is FIXED by the checkpoint's documented output order
    "<Fake score, Real score>" (the card prints "real prob = prob[1],
    fake prob = prob[0]"). It is deliberately not inferred from an id2label
    dictionary: the MMS checkpoint ships a plain tensor head rather than HF
    label metadata, so guessing the order would risk reporting fake as real.

    A head that is not exactly 2-class, or non-finite probabilities, is
    raised as an error so it can never be reported as a genuine verdict.
    """
    probabilities = torch.softmax(logits, dim=-1)[0]
    if probabilities.shape[-1] != 2:
        raise RuntimeError(
            "MMS-300M-AntiDeepfake must return exactly 2 logits "
            f"(<fake, real>); got {int(probabilities.shape[-1])}."
        )
    fake_probability = float(probabilities[FAKE_LABEL_INDEX].item())
    real_probability = float(probabilities[REAL_LABEL_INDEX].item())
    if not np.isfinite([fake_probability, real_probability]).all():
        raise RuntimeError(
            "Non-finite anti-spoof probabilities returned by the MMS model."
        )
    return fake_probability, real_probability


def _run_inference(audio) -> dict:
    """Implementation body: MMS anti-spoof + ECAPA inside ONE GPU invocation."""
    start_time = time.time()

    _load_models()
    _ensure_models_on_device()
    audio_data = _prepare_audio(audio)

    # Raw window for the ECAPA speaker path (unchanged contract: the speaker
    # embedding keeps its original amplitude behaviour).
    raw_waveform = torch.from_numpy(audio_data).float().unsqueeze(0).to(DEVICE)
    if not bool(torch.isfinite(raw_waveform).all()):
        raise ValueError(
            "Audio window contains NaN/Inf samples and cannot be analysed"
        )

    # MMS preprocessing follows the model card: the waveform is layer-normalised
    # before the forward pass. Applied to the exact 4-second / 16 kHz window
    # SatyaVoice feeds the model.
    antispoof_waveform = torch.nn.functional.layer_norm(
        raw_waveform, raw_waveform.shape
    )

    with torch.inference_mode():
        # ---- MMS-300M-AntiDeepfake: logits are <fake, real> ----
        logits = _antispoof_model(antispoof_waveform)
        fake_probability, real_probability = _binary_probabilities(logits)

        # ---- ECAPA-TDNN speaker embedding (same GPU invocation) ----
        embedding_tensor = _speaker_model.encode_batch(raw_waveform)
        embedding = embedding_tensor.squeeze().cpu().numpy().astype(np.float32)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

    inference_time_ms = (time.time() - start_time) * 1000

    return {
        "status": "ok",
        # SatyaVoice convention: spoof_probability is the FAKE probability, and
        # the risk engine treats a higher acoustic_score as higher risk.
        "spoof_probability": fake_probability,
        "fake_probability": fake_probability,
        "real_probability": real_probability,
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
    # MMS-300M-AntiDeepfake anti-spoof pass and the ECAPA speaker embedding.
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
