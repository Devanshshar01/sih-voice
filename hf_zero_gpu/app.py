"""
SatyaVoice — Hugging Face ZeroGPU Space (Gradio API).

Purpose: the ONLY GPU-heavy stage in the SatyaVoice stack — acoustic
deepfake detection with nii-yamagishilab/mms-300m-anti-deepfake.

The Render backend calls this Space through the Gradio Client using the
named API endpoint `detect` below; it never imports fairseq itself, so the
512 MB-class web tier stays light.

ZeroGPU quota discipline (hard requirements):
  * The model is loaded EXACTLY ONCE at Space startup (import time), never
    per request — `detect_fake` reuses the resident instance.
  * Every inference runs under torch.inference_mode() with no extra
    tensor copies beyond the single [1, T] waveform tensor.
  * The API endpoint is @spaces.GPU-decorated so ZeroGPU assigns the
    process only for the inference call itself.

The Gradio API contract (named endpoint "detect", JSON input/output) is
stable: the backend's hf_zero_gpu client parses exactly the schema
documented in hf_zero_gpu/inference.py.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Tuple

import gradio as gr
import numpy as np

try:
    import spaces  # ZeroGPU runtime; absent when running locally
except ImportError:  # local/dev: degrade to a no-op decorator
    class _NoopSpaces:
        def GPU(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco
    spaces = _NoopSpaces()  # type: ignore[assignment]

from hf_zero_gpu import inference as mms

# ---- One-time startup load (imports run once when the Space boots) ----
try:
    STARTUP_INFO = mms.load_model()
except Exception as exc:  # the Space must still boot to surface the error
    STARTUP_INFO = {"loaded": False, "load_error": f"{type(exc).__name__}: {exc}"}


def _detect_impl(wav_json: str) -> str:
    """Named API endpoint body. Input: JSON string {"wav": [...], "sample_rate": 16000}.

    The client (Render backend) sends the 4-second window as a flat float
    array over JSON — small (~256 KB), schema-simple, and works through the
    standard Gradio Client without binary transport.
    """
    try:
        payload = json.loads(wav_json)
        wav = np.asarray(payload.get("wav", []), dtype=np.float32)
        sample_rate = int(payload.get("sample_rate", 16000))
    except Exception as exc:
        return json.dumps(mms._failure("invalid_input", f"{type(exc).__name__}: {exc}"))

    result = mms.detect_fake(wav, sample_rate)
    return json.dumps(result)


@spaces.GPU(duration=30)
def detect(wav_json: str) -> str:
    return _detect_impl(wav_json)


@spaces.GPU(duration=30)
def detect_tuple(wav: np.ndarray, sample_rate: int) -> Tuple[np.ndarray]:
    """Typed-path variant (Gradio native audio/array inputs)."""
    result = mms.detect_fake(np.asarray(wav).reshape(-1), sample_rate)
    return (np.asarray([[result.get("fake_probability", 0.5),
                         result.get("real_probability", 0.5)]]),)


def status() -> Dict[str, Any]:
    return mms.model_info()


# ---- Gradio app: API-only (no visual UI needed; the dashboard is Vercel) ----
demo = gr.Interface(
    fn=detect,
    inputs=gr.Text(label="wav_json"),
    outputs=gr.Text(label="result_json"),
    api_name="detect",
    title="SatyaVoice — MMS-300M Anti-Deepfake (ZeroGPU)",
    description=(
        "Acoustic deepfake detector: nii-yamagishilab/mms-300m-anti-deepfake "
        "(NII Yamagishi Lab, CC BY-NC-SA 4.0). Input JSON: "
        '{"wav": [floats], "sample_rate": 16000}. Output JSON: fake/real '
        "probabilities + latency, or {ok:false, status:degraded} on failure."
    ),
)

# Secondary status API (named endpoint "status").
with gr.Blocks() as status_blocks:
    status_btn = gr.Button("status")
    status_out = gr.JSON()
    status_btn.click(fn=status, outputs=status_out, api_name="status")

app = gr.mount_gradio_app  # re-export for uvicorn if hosted that way

if __name__ == "__main__":
    demo.launch(show_api=True)
