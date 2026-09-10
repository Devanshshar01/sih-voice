"""
Central configuration for the SatyaVoice backend.

Every tunable knob (risk thresholds, fusion weights, audio window sizing)
lives here so the team can retune the demo the night before judging without
touching business logic in core/ or services/.
"""
import os

# ---- Server ----
APP_NAME = "SatyaVoice API"
API_V1_PREFIX = "/api/v1"
CORS_ORIGINS = os.getenv("VOICETRUST_CORS_ORIGINS", "*").split(",")

# ---- Audio windowing ----
# Benchmarking showed the 2.0s window is a better fit for the current demo
# flow because it preserves faster response time without sacrificing the
# detector's signal quality. Keep the code and docs aligned on that choice.
SAMPLE_RATE_HZ = 16000
WINDOW_SECONDS = float(os.getenv("VOICETRUST_WINDOW_SECONDS", "2.0"))
HOP_SECONDS = float(os.getenv("VOICETRUST_HOP_SECONDS", "0.5"))
WINDOW_SAMPLES = int(SAMPLE_RATE_HZ * WINDOW_SECONDS)
HOP_SAMPLES = int(SAMPLE_RATE_HZ * HOP_SECONDS)

# ---- Audio preprocessing ----
# Optional VAD reduces pointless silence before the detector. The default stays
# disabled so the legacy smoke test remains stable, but production/demo use can
# turn it on with VOICETRUST_VAD_ENABLED=true.
VAD_ENABLED = os.getenv("VOICETRUST_VAD_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
VAD_ENERGY_THRESHOLD = float(os.getenv("VOICETRUST_VAD_ENERGY_THRESHOLD", "0.01"))
VAD_MIN_ACTIVE_FRAMES = int(os.getenv("VOICETRUST_VAD_MIN_ACTIVE_FRAMES", "4"))
AUDIO_CODEC = os.getenv("VOICETRUST_AUDIO_CODEC", "pcm")

# ---- Risk engine fusion weights (must sum to 1.0) ----
ACOUSTIC_WEIGHT = 0.55
INTENT_WEIGHT = 0.45
SPEAKER_WEIGHT = float(os.getenv("VOICETRUST_SPEAKER_WEIGHT", "0.15"))

# ---- Risk thresholds (0-100) ----
RISK_LOW_MAX = 39      # 0-39   -> ALLOW
RISK_MEDIUM_MAX = 69   # 40-69  -> WARN
# 70-100 -> LOCK_VERIFY


class RiskStatus:
    ALLOW = "ALLOW"
    WARN = "WARN"
    LOCK_VERIFY = "LOCK_VERIFY"


# ---- Session lifecycle ----
SESSION_TTL_SECONDS = int(os.getenv("VOICETRUST_SESSION_TTL", "3600"))
TELEMETRY_INTERVAL_SECONDS = 0.5

# ---- Verification ----
TOTP_CODE_LENGTH = 6
TOTP_CHALLENGE_TIMEOUT_SECONDS = 60

# ---- Database ----
DATABASE_URL = os.getenv("VOICETRUST_DATABASE_URL", "sqlite:///./satyavoice.db")
DATABASE_ECHO = os.getenv("VOICETRUST_DATABASE_ECHO", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SESSION_STORE_BACKEND = os.getenv("VOICETRUST_SESSION_STORE_BACKEND", "sqlite").lower()
REDIS_URL = os.getenv("VOICETRUST_REDIS_URL", "redis://localhost:6379/0")

# ---- Background tasks (Celery + Redis) ----
CELERY_BROKER_URL = os.getenv("VOICETRUST_CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("VOICETRUST_CELERY_RESULT_BACKEND", REDIS_URL)

# ---- Evidence anchoring (Phase 8) ----
EVIDENCE_SCHEMA_VERSION = os.getenv("VOICETRUST_EVIDENCE_SCHEMA_VERSION", "phase7-v1")
BLOCKCHAIN_ANCHORING_ENABLED = os.getenv("VOICETRUST_BLOCKCHAIN_ANCHORING_ENABLED", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
BLOCKCHAIN_NETWORK = os.getenv("VOICETRUST_BLOCKCHAIN_NETWORK", "polygon-amoy")
BLOCKCHAIN_RPC_URL = os.getenv("VOICETRUST_BLOCKCHAIN_RPC_URL", "")
BLOCKCHAIN_CONTRACT_ADDRESS = os.getenv("VOICETRUST_BLOCKCHAIN_CONTRACT_ADDRESS", "")
BLOCKCHAIN_PRIVATE_KEY = os.getenv("VOICETRUST_BLOCKCHAIN_PRIVATE_KEY", "")
BLOCKCHAIN_CHAIN_ID = int(os.getenv("VOICETRUST_BLOCKCHAIN_CHAIN_ID", "80002"))
BLOCKCHAIN_GAS_LIMIT = int(os.getenv("VOICETRUST_BLOCKCHAIN_GAS_LIMIT", "300000"))

# ---- Detector selection ----
# "mock" -> deterministic / keyword-triggered scores (safe for live demo)
# "real" -> verified Hugging Face audio anti-spoof classifier
VOICE_DETECTOR_MODE = os.getenv("VOICETRUST_DETECTOR_MODE", "mock").lower()
VOICE_MODEL_ID = os.getenv("VOICETRUST_MODEL_ID", "Hemgg/Deepfake-audio-detection")
VOICE_MODEL_PATH = os.getenv("VOICETRUST_MODEL_PATH", "")
VOICE_MODEL_DEVICE = os.getenv("VOICETRUST_MODEL_DEVICE", "cpu")
VOICE_MODEL_REVISION = os.getenv("VOICETRUST_MODEL_REVISION", "main")

# ---- Automatic speech recognition ----
# "manual" preserves Phase 1 transcript behavior; "real" enables faster-whisper.
ASR_MODE = os.getenv("VOICETRUST_ASR_MODE", "manual").lower()
ASR_MODEL_SIZE = os.getenv("VOICETRUST_ASR_MODEL_SIZE", "base")
ASR_DEVICE = os.getenv("VOICETRUST_ASR_DEVICE", "cpu")
ASR_COMPUTE_TYPE = os.getenv("VOICETRUST_ASR_COMPUTE_TYPE", "int8")
ASR_LANGUAGE = os.getenv("VOICETRUST_ASR_LANGUAGE", "")

# ---- Speaker vault (Phase 3) ----
SPEAKER_VAULT_ENABLED = os.getenv("VOICETRUST_SPEAKER_VAULT_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SPEAKER_MODEL = os.getenv("VOICETRUST_SPEAKER_MODEL", "speechbrain/spkrec-ecapa-voxceleb")
SPEAKER_MATCH_THRESHOLD = float(os.getenv("VOICETRUST_SPEAKER_MATCH_THRESHOLD", "0.80"))
SPEAKER_EMBEDDING_DIM = int(os.getenv("VOICETRUST_SPEAKER_EMBEDDING_DIM", "64"))

# ---- Intent keyphrases (Phase 1 lightweight matcher) ----
HIGH_RISK_KEYPHRASES = [
    "wire transfer", "urgent transfer", "send money immediately", "confidential",
    "otp", "one time password", "verification code", "password", "routing number",
    "account number", "gift card", "crypto wallet", "don't tell anyone",
    "act now", "immediately approve", "bypass approval", "cash out",
]
