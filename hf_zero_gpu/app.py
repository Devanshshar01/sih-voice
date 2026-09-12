"""
Hugging Face ZeroGPU Space for SatyaVoice inference.

This Space provides an API for anti-spoof detection and speaker embedding extraction.
"""
import os

import gradio as gr

from .inference import infer

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
        sampling_rate=16000,
        length=4.0,
    )
    output = gr.JSON(label="Inference Result")
    
    audio_input.change(
        fn=infer,
        inputs=audio_input,
        outputs=output,
    )

# Launch the app
if __name__ == "__main__":
    demo.launch()