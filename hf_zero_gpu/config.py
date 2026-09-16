"""
Configuration for the Hugging Face ZeroGPU Space.
"""
import os

# ---- Model IDs ----
# Anti-spoof model: MMS-300M-AntiDeepfake (Wav2Vec 2.0 front-end + FC head),
# post-trained for deepfake speech detection by NII / Yamagishi Lab.
# Loaded exactly as the official model card documents: fairseq Wav2Vec2Model
# (built from Wav2Vec2Config) + fully connected 2-class head, packaged with
# huggingface_hub.PyTorchModelHubMixin. It is NOT a transformers
# AutoModelForAudioClassification checkpoint (its config.json declares
# Wav2Vec2ForPreTraining). Used off-the-shelf; SatyaVoice has NOT fine-tuned it.
ANTISPOOF_MODEL_ID = os.getenv(
    "ANTISPOOF_MODEL_ID", "nii-yamagishilab/mms-300m-anti-deepfake"
)
# Speaker embedding model: ECAPA-TDNN from SpeechBrain
SPEAKER_MODEL_ID = os.getenv("SPEAKER_MODEL_ID", "speechbrain/spkrec-ecapa-voxceleb")

# ---- Class mapping (verified against the official model card) ----
# The card reports the binary score as "<Fake score, Real score>" and prints
# "real prob = prob[1], fake prob = prob[0]" -> index 0 is FAKE, index 1 is REAL.
# Never reorder these without re-verifying against the card.
FAKE_LABEL_INDEX = 0
REAL_LABEL_INDEX = 1

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