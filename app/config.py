"""
Central configuration for the VoiceTrust backend.

Every tunable knob (risk thresholds, fusion weights, audio window sizing)
lives here so the team can retune the demo the night before judging without
touching business logic in core/ or services/.
"""
import os

# ---- Server ----
APP_NAME = "VoiceTrust API"
API_V1_PREFIX = "/api/v1"
CORS_ORIGINS = os.getenv("VOICETRUST_CORS_ORIGINS", "*").split(",")

# ---- Audio windowing (per prototype blueprint: 2.0s window, 0.5s hop) ----
SAMPLE_RATE_HZ = 16000
WINDOW_SECONDS = 2.0
HOP_SECONDS = 0.5
WINDOW_SAMPLES = int(SAMPLE_RATE_HZ * WINDOW_SECONDS)  # 32,000 samples
HOP_SAMPLES = int(SAMPLE_RATE_HZ * HOP_SECONDS)         # 8,000 samples

# ---- Risk engine fusion weights (must sum to 1.0) ----
ACOUSTIC_WEIGHT = 0.55
INTENT_WEIGHT = 0.45

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
DATABASE_URL = os.getenv("VOICETRUST_DATABASE_URL", "sqlite:///./voicetrust.db")

# ---- Detector selection ----
# "mock" -> deterministic / keyword-triggered scores (Phase 1, safe for live demo)
# "ml"   -> classical feature extractor + trained sklearn classifier (Phase 2)
VOICE_DETECTOR_MODE = os.getenv("VOICETRUST_DETECTOR_MODE", "mock")

# ---- Intent keyphrases (Phase 1 lightweight matcher) ----
HIGH_RISK_KEYPHRASES = [
    "wire transfer", "urgent transfer", "send money immediately", "confidential",
    "otp", "one time password", "verification code", "password", "routing number",
    "account number", "gift card", "crypto wallet", "don't tell anyone",
    "act now", "immediately approve", "bypass approval", "cash out",
]
