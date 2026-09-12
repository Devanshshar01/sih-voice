"""
Configuration for the Hugging Face ZeroGPU Space.
"""
import os

# ---- Model IDs ----
# Anti-spoof model: fine-tuned Wav2Vec2-XLS-R (300M)
ANTISPOOF_MODEL_ID = os.getenv("ANTISPOOF_MODEL_ID", "facebook/wav2vec2-xls-r-300m")
# Speaker embedding model: ECAPA-TDNN from SpeechBrain
SPEAKER_MODEL_ID = os.getenv("SPEAKER_MODEL_ID", "speechbrain/spkrec-ecapa-voxceleb")

# ---- Audio processing ----
SAMPLE_RATE = 16000
# We expect audio windows of 4 seconds as per the SatyaVoice specification
WINDOW_SECONDS = 4.0
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SECONDS)

# ---- Device ----
# In ZeroGPU, we rely on the decorator to place tensors on GPU.
# We will set the device to "cuda" if available, but the model loading should happen inside the GPU function.
DEVICE = "cuda"

# ---- Inference timeout ----
# Timeout for the inference function in seconds
INFERENCE_TIMEOUT = float(os.getenv("INFERENCE_TIMEOUT", "30.0"))