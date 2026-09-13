"""
Hugging Face ZeroGPU Space for SatyaVoice inference.

Thin Gradio wrapper: Gradio only exposes the @spaces.GPU-decorated
`infer()` entry point (anti-spoof + ECAPA speaker embedding in one GPU
call) as an HTTP API. All model logic lives in inference.py.
"""
try:
    import spaces  # ZeroGPU: must be imported before torch/gradio
except ImportError:  # local dev / tests: `spaces` only exists on Hugging Face
    spaces = None

import gradio as gr

import sys

# The `spaces` ZeroGPU client creates asyncio event loops internally; on the
# Space's Python 3.10 image their GC finalizers emit harmless-but-noisy
# "Exception ignored in BaseEventLoop.__del__" tracebacks into the container
# logs. Route them through sys.unraisablehook and filter out the known-benign
# closed-loop ValueError so logs stay readable. Real errors still print.
_default_unraisable_hook = sys.unraisablehook


def _quiet_unraisable_hook(unraisable):
    exc = unraisable.exc_value
    if isinstance(exc, ValueError) and "Invalid file descriptor" in str(exc):
        return
    _default_unraisable_hook(unraisable)


sys.unraisablehook = _quiet_unraisable_hook

from inference import infer

# Create the interface
with gr.Blocks() as demo:
    gr.Markdown("# SatyaVoice ZeroGPU Inference Space")
    gr.Markdown(
        """
        This Space provides anti-spoof detection and speaker embedding extraction.
        Send a 4-second mono audio window at 16kHz to get:
        - spoof_probability: probability that the audio is spoofed (0-1)
        - speaker_embedding: normalized embedding vector for speaker verification
        - inference_time_ms: time taken for inference on the GPU
        - model_version_antispoof: anti-spoof model identifier
        - model_version_speaker: speaker model identifier
        - sample_rate: audio sample rate (Hz)
        - duration_ms: duration of the audio window (ms)
        """
    )
    audio_input = gr.Audio(
        label="Input Audio (4 seconds, 16kHz mono)",
        type="numpy",
        sources=["microphone", "upload"],
    )
    output = gr.JSON(label="Inference Result")

    audio_input.change(
        fn=infer,
        inputs=audio_input,
        outputs=output,
        api_name="infer",
    )

# Launch the app
# ssr_mode=False: this Space is an API backend (Render -> /call/infer);
# the SSR Node proxy spins up unclosed asyncio event loops whose GC
# finalizers spam harmless-but-noisy tracebacks in the container logs.
if __name__ == "__main__":
    demo.launch(ssr_mode=False)