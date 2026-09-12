"""
Central configuration for the SatyaVoice backend.

Every tunable knob (risk thresholds, fusion weights, audio window sizing)
lives here so the team can retune the demo the night before judging without
touching business logic in core/ or services/.
"""
import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Environment modes
# ---------------------------------------------------------------------------
# development — localhost, SQLite, mock detectors, permissive CORS, auth open
# demo        — like development but intentionally reproducible for judging
# production  — PostgreSQL required, mock AI refused, strict CORS, auth enforced
#
# Production refuses mock AI: a deployment that would present deterministic
# demo scores as real decisions is worse than one that fails fast at boot.
ENV_MODE = os.getenv("VOICETRUST_ENV", "development").strip().lower()
if ENV_MODE not in {"development", "demo", "production"}:
    raise RuntimeError(
        f"VOICETRUST_ENV must be one of development|demo|production (got '{ENV_MODE}')."
    )

IS_PRODUCTION = ENV_MODE == "production"
IS_DEMO = ENV_MODE == "demo"
IS_DEVELOPMENT = ENV_MODE == "development"

# ---- Server ----
APP_NAME = "SatyaVoice API"
API_V1_PREFIX = "/api/v1"
# Secure CORS defaults per mode: dev/demo stay permissive for localhost; only
# production defaults to a deny-list that requires explicit origins.
_CORS_DEFAULTS = {
    "development": "*",
    "demo": "*",
    "production": "",  # empty default -> startup fails unless origins are set
}
_CORS_RAW = os.getenv("VOICETRUST_CORS_ORIGINS", _CORS_DEFAULTS[ENV_MODE]).strip()
if IS_PRODUCTION and not _CORS_RAW:
    raise RuntimeError(
        "VOICETRUST_CORS_ORIGINS is required in production (comma-separated "
        "frontend origins; wildcard '*' is not allowed with credentials)."
    )
CORS_ORIGINS = [o.strip() for o in _CORS_RAW.split(",") if o.strip()] or ["*"]

# ---- Canonical audio configuration (single source of truth) ----
# These constants implement the SIH 2026 presentation specification exactly:
#   * 16 kHz mono analysis rate (Wav2Vec2-XLS-R / faster-whisper / ECAPA input)
#   * 4.0-second inference windows (WINDOW_SAMPLES == 64000)
#   * 0.5-second hop (HOP_SAMPLES == 8000) -> a decision every 500 ms
# Every other module must import these values from here; duplicated numeric
# literals elsewhere are a spec-drift bug.
@dataclass(frozen=True)
class AudioConfig:
    TARGET_SAMPLE_RATE: int = 16000
    WINDOW_SECONDS: float = 4.0
    HOP_SECONDS: float = 0.5

    @property
    def WINDOW_SAMPLES(self) -> int:
        return int(self.TARGET_SAMPLE_RATE * self.WINDOW_SECONDS)  # 64000

    @property
    def HOP_SAMPLES(self) -> int:
        return int(self.TARGET_SAMPLE_RATE * self.HOP_SECONDS)  # 8000


AUDIO = AudioConfig()

# Flat aliases kept for the existing import sites (streaming path, benchmarks,
# tests). These are the canonical values -- do not recompute or shadow them.
TARGET_SAMPLE_RATE = AUDIO.TARGET_SAMPLE_RATE
SAMPLE_RATE_HZ = AUDIO.TARGET_SAMPLE_RATE
WINDOW_SECONDS = AUDIO.WINDOW_SECONDS
HOP_SECONDS = AUDIO.HOP_SECONDS
WINDOW_SAMPLES = AUDIO.WINDOW_SAMPLES
HOP_SAMPLES = AUDIO.HOP_SAMPLES

# ---- Audio preprocessing / codec normalization ----
# "auto" trusts the per-connection codec declared by the client over the
# WebSocket (default: PCM float32); a fixed value forces one family for the
# whole deployment ("pcm" | "pcm_s16le" | "g711_ulaw" | "g711_alaw" | "opus" | "amr").
AUDIO_CODEC = os.getenv("VOICETRUST_AUDIO_CODEC", "auto")

# Silero VAD is a mandatory preprocessing stage of the SIH stack and is
# enabled by default. It gates detector inference on speech activity without
# discarding legitimate short pauses (see app/services/vad.py).
VAD_ENABLED = os.getenv("VOICETRUST_VAD_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Legacy energy-threshold fallback used only when Silero is unavailable.
VAD_ENERGY_THRESHOLD = float(os.getenv("VOICETRUST_VAD_ENERGY_THRESHOLD", "0.01"))
VAD_MIN_ACTIVE_FRAMES = int(os.getenv("VOICETRUST_VAD_MIN_ACTIVE_FRAMES", "4"))
# Silero tuning: short pauses inside a sentence must survive (min_silence is
# generous), and speech is padded so window construction keeps full context.
VAD_THRESHOLD = float(os.getenv("VOICETRUST_VAD_THRESHOLD", "0.5"))
VAD_MIN_SPEECH_DURATION_MS = int(os.getenv("VOICETRUST_VAD_MIN_SPEECH_DURATION_MS", "150"))
VAD_MIN_SILENCE_DURATION_MS = int(os.getenv("VOICETRUST_VAD_MIN_SILENCE_DURATION_MS", "250"))
VAD_SPEECH_PAD_MS = int(os.getenv("VOICETRUST_VAD_SPEECH_PAD_MS", "60"))

# ---- Risk fusion (SIH Phase 2: explicit, centralized, documented) ----
# The fused risk equation implemented by app/core/risk_engine.py is:
#
#   R_total = 100 * (Wa*A + Wi*I + Wm*M)
#   M       = identity_mismatch = (1 - speaker_similarity)   [only when a
#             reference embedding exists; 0 when identity is UNKNOWN]
#   hard override: if a transactional hard trigger fires, R_total = 100
#   status   : ALLOW if R <= WARN_THRESHOLD
#              WARN  if WARN_THRESHOLD < R <= LOCK_THRESHOLD
#              LOCK_VERIFY otherwise
#
# Semantics (IMPORTANT): speaker_similarity measures how well the live audio
# matches the ENROLLED caller reference. High similarity = identity
# CONSISTENT = low identity risk. Only a LOW similarity WITH a reference
# (an identity MISMATCH) contributes to risk. With no reference enrolled,
# identity evidence is neutral (M=0), it must never be treated as fraud.
#
# Weights sum to exactly 1.0 so R_total is a proper convex combination.
# Override via env at deployment time; the README documents the same formula.
@dataclass(frozen=True)
class RiskFusionConfig:
    ACOUSTIC_WEIGHT: float = float(os.getenv("VOICETRUST_ACOUSTIC_WEIGHT", "0.60"))
    INTENT_WEIGHT: float = float(os.getenv("VOICETRUST_INTENT_WEIGHT", "0.30"))
    IDENTITY_MISMATCH_WEIGHT: float = float(os.getenv("VOICETRUST_IDENTITY_WEIGHT", "0.10"))
    WARN_THRESHOLD: int = int(os.getenv("VOICETRUST_WARN_THRESHOLD", "40"))
    LOCK_VERIFY_THRESHOLD: int = int(os.getenv("VOICETRUST_LOCK_THRESHOLD", "70"))
    # Transactional hard trigger: when true, the fused score is forced to 100.
    HARD_TRIGGER_ENABLED: bool = os.getenv("VOICETRUST_HARD_TRIGGER_ENABLED", "true").lower() in {
        "1", "true", "yes", "on"
    }
    # Minimum ambiguity (max component score) below which a hard trigger is
    # applied. Keeps stray single-word fuzzy matches from locking a call.
    HARD_TRIGGER_MIN_AMBIGUITY: float = float(os.getenv("VOICETRUST_HARD_TRIGGER_MIN_AMBIGUITY", "0.10"))
    # Degraded (model-failure) fusion: penalize unknown evidence instead of
    # assuming the best case, so failures preserve safety.
    DEGRADED_FUSION_PENALTY: float = float(os.getenv("VOICETRUST_DEGRADED_PENALTY", "0.05"))

    @property
    def WEIGHT_SUM(self) -> float:
        return self.ACOUSTIC_WEIGHT + self.INTENT_WEIGHT + self.IDENTITY_MISMATCH_WEIGHT


RISK = RiskFusionConfig()

# Categories that constitute a hard transactional trigger when flagged by the
# intent analyzer (OTP / UPI / transfer requests). Phrase families map to
# these categories in IntentAnalyzer.MULTILINGUAL_PHRASE_SETS.
HARD_TRIGGER_CATEGORIES = {"otp", "upi"}

# Flat aliases preserved for existing import sites.
ACOUSTIC_WEIGHT = RISK.ACOUSTIC_WEIGHT
INTENT_WEIGHT = RISK.INTENT_WEIGHT
SPEAKER_WEIGHT = RISK.IDENTITY_MISMATCH_WEIGHT  # legacy alias (now means mismatch weight)
RISK_LOW_MAX = RISK.WARN_THRESHOLD - 1  # legacy: max ALLOW score
RISK_MEDIUM_MAX = RISK.LOCK_VERIFY_THRESHOLD - 1  # legacy: max WARN score


class RiskStatus:
    ALLOW = "ALLOW"
    WARN = "WARN"
    LOCK_VERIFY = "LOCK_VERIFY"


# ---- Parallel inference ----
# Bounded executor shared by the streaming path: anti-spoof, ASR, and speaker
# embedding run concurrently per window. Bounded so a burst of connections
# cannot spawn unbounded threads; the stream awaits with a timeout.
INFERENCE_EXECUTOR_MAX_WORKERS = int(os.getenv("VOICETRUST_INFERENCE_WORKERS", "6"))
INFERENCE_TIMEOUT_SECONDS = float(os.getenv("VOICETRUST_INFERENCE_TIMEOUT", "4.0"))

# ---- Risk engine fusion weights (legacy; see RiskFusionConfig above) ----

# ---- Session lifecycle ----
SESSION_TTL_SECONDS = int(os.getenv("VOICETRUST_SESSION_TTL", "3600"))
TELEMETRY_INTERVAL_SECONDS = 0.5

# ---- Verification ----
TOTP_CODE_LENGTH = 6
TOTP_CHALLENGE_TIMEOUT_SECONDS = 60

# ---- Database ----
# Development/demo: SQLite by default. Production: PostgreSQL required — the
# process refuses to boot on SQLite in production (single-file DBs cannot
# serve multi-worker deployments safely).
_DATABASE_URL_ENV = os.getenv("VOICETRUST_DATABASE_URL", "")
if not _DATABASE_URL_ENV:
    if IS_PRODUCTION:
        raise RuntimeError(
            "VOICETRUST_DATABASE_URL is required in production and must be a "
            "PostgreSQL URL (postgresql://... or postgresql+psycopg://...)."
        )
    DATABASE_URL = "sqlite:///./satyavoice.db"
else:
    DATABASE_URL = _DATABASE_URL_ENV
if IS_PRODUCTION and DATABASE_URL.startswith("sqlite"):
    raise RuntimeError(
        "SQLite is not a supported production database. Point "
        "VOICETRUST_DATABASE_URL at PostgreSQL for multi-worker deployments."
    )
DATABASE_ECHO = os.getenv("VOICETRUST_DATABASE_ECHO", "false").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Session store: memory keeps local demo friction-free; production defaults to
# Redis so active calls survive worker restarts and are shared across workers.
SESSION_STORE_BACKEND = os.getenv(
    "VOICETRUST_SESSION_STORE_BACKEND", "redis" if IS_PRODUCTION else "memory"
).lower()
REDIS_URL = os.getenv("VOICETRUST_REDIS_URL", "redis://localhost:6379/0")

# ---- Background tasks (Celery + Redis) ----
# Only non-latency-critical work (evidence anchoring, PDF/report generation)
# is routed through Celery — never the streaming decision path.
CELERY_BROKER_URL = os.getenv("VOICETRUST_CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.getenv("VOICETRUST_CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_TASK_ALWAYS_EAGER = os.getenv("VOICETRUST_CELERY_EAGER", "").lower() in {
    "1", "true", "yes", "on"
}

# ---- AI modes per environment ----
# Production defaults refuse mock behavior: a deployment presenting
# deterministic demo scores as real decisions fails fast at boot instead.
def _ai_mode(env_var: str, dev_default: str, production_default: str) -> str:
    value = os.getenv(env_var, "")
    if value:
        return value.strip().lower()
    return production_default if IS_PRODUCTION else dev_default


VOICE_DETECTOR_MODE = _ai_mode("VOICETRUST_DETECTOR_MODE", "mock", "real")
ASR_MODE = _ai_mode("VOICETRUST_ASR_MODE", "manual", "real")

# ---- Authentication (API keys per tenant) ----
# Format: comma-separated "tenant_id:key" pairs, e.g. "acme:sk_live_x,contoso:sk_live_y".
# An empty value disables auth (development/demo only). Production REQUIRES it:
# a multi-user deployment without auth boundaries is not production-grade.
AUTH_API_KEYS = os.getenv("VOICETRUST_AUTH_API_KEYS", "")
if IS_PRODUCTION and not AUTH_API_KEYS.strip():
    raise RuntimeError(
        "VOICETRUST_AUTH_API_KEYS is required in production (comma-separated "
        '"tenant_id:key" pairs). The API cannot be exposed unauthenticated.'
    )
AUTH_REQUIRED = IS_PRODUCTION or bool(AUTH_API_KEYS.strip())
AUTH_HEADER = "X-API-Key"

# ---- Rate limiting ----
# Sliding-window per API key (or client IP when auth is open). Redis-backed in
# production; in-process fallback otherwise.
RATE_LIMIT_ENABLED = os.getenv("VOICETRUST_RATE_LIMIT_ENABLED", str(IS_PRODUCTION)).lower() in {
    "1", "true", "yes", "on"
}
RATE_LIMIT_REQUESTS = int(os.getenv("VOICETRUST_RATE_LIMIT_REQUESTS", "120"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("VOICETRUST_RATE_LIMIT_WINDOW_SECONDS", "60"))
RATE_LIMIT_REDIS_URL = os.getenv("VOICETRUST_RATE_LIMIT_REDIS_URL", REDIS_URL)

# ---- Request payload limits ----
MAX_AUDIO_UPLOAD_BYTES = int(os.getenv("VOICETRUST_MAX_AUDIO_UPLOAD_BYTES", str(8 * 1024 * 1024)))
MAX_JSON_BODY_BYTES = int(os.getenv("VOICETRUST_MAX_JSON_BODY_BYTES", str(256 * 1024)))

# ---- WebSocket abuse protection ----
WS_MAX_FRAME_BYTES = int(os.getenv("VOICETRUST_WS_MAX_FRAME_BYTES", str(256 * 1024)))
WS_MAX_TOTAL_BYTES_PER_CALL = int(os.getenv("VOICETRUST_WS_MAX_TOTAL_BYTES", str(500 * 1024 * 1024)))
# Max binary frames per second a client may push (a real 0.5s-hop client needs ~2/s).
WS_MAX_FRAMES_PER_SECOND = int(os.getenv("VOICETRUST_WS_MAX_FRAMES_PER_SECOND", "50"))

# ---- Structured logging ----
LOG_LEVEL = os.getenv("VOICETRUST_LOG_LEVEL", "INFO" if IS_PRODUCTION else "DEBUG")
LOG_JSON = os.getenv("VOICETRUST_LOG_JSON", str(IS_PRODUCTION)).lower() in {
    "1", "true", "yes", "on"
}

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
# Production target stack: a fine-tuned Wav2Vec2-XLS-R (300M) anti-spoof
# checkpoint. Defaults are mode-aware (see the env-modes block above):
# development/demo default to "mock"; production defaults to "real" and
# refuses mock. Set VOICETRUST_DETECTOR_MODE=real and point VOICETRUST_MODEL_ID
# at the fine-tuned checkpoint when it is ready.
VOICE_MODEL_ID = os.getenv("VOICETRUST_MODEL_ID", "Hemgg/Deepfake-audio-detection")
VOICE_MODEL_PATH = os.getenv("VOICETRUST_MODEL_PATH", "")
VOICE_MODEL_DEVICE = os.getenv("VOICETRUST_MODEL_DEVICE", "cpu")
VOICE_MODEL_REVISION = os.getenv("VOICETRUST_MODEL_REVISION", "main")

# ---- Automatic speech recognition ----
# Target stack: faster-whisper small. Mode-aware default (see env-modes):
# development keeps "manual" for deterministic local testing; production
# defaults to "real" with the small model size.
ASR_MODEL_SIZE = os.getenv("VOICETRUST_ASR_MODEL_SIZE", "small")
ASR_DEVICE = os.getenv("VOICETRUST_ASR_DEVICE", "cpu")
ASR_COMPUTE_TYPE = os.getenv("VOICETRUST_ASR_COMPUTE_TYPE", "int8")
ASR_LANGUAGE = os.getenv("VOICETRUST_ASR_LANGUAGE", "")
# Beam width for faster-whisper (1 = greedy; higher = better accuracy, more
# latency). Kept configurable so the sub-500 ms target can be re-tuned.
ASR_BEAM_SIZE = int(os.getenv("VOICETRUST_ASR_BEAM_SIZE", "1"))
# Whisper's internal VAD filter drops non-speech before decoding; the pipeline
# already gates with Silero upstream, so this is a second-stage noise filter.
ASR_VAD_FILTER = os.getenv("VOICETRUST_ASR_VAD_FILTER", "true").lower() in {
    "1", "true", "yes", "on"
}
# Language policy:
#   "auto"           -> no language forced; Whisper auto-detects per window.
#   fixed code (e.g. "hi") -> force one language globally (not recommended
#                       for the SIH multilingual target).
# Per-window hints from the client always override this default.
ASR_LANGUAGE_POLICY = os.getenv("VOICETRUST_ASR_LANGUAGE_POLICY", "auto")

# SIH presentation target languages. "Indian English" is represented in
# product config as "en" (Indian English is not a distinct Whisper locale;
# the model transcribes it via its English capability). We never fabricate a
# language-model identifier — the presentation-facing name is display-only.
SIH_TARGET_LANGUAGES = {
    "en": "English (Indian English)",
    "hi": "Hindi",
    "ta": "Tamil",
    "te": "Telugu",
    "bn": "Bengali",
    "mr": "Marathi",
}

# ---- Speaker vault (Phase 3) ----
# Target stack: ECAPA-TDNN. Keep the existing SpeechBrain checkpoint path as
# the production speaker model and leave the deterministic fallback in place
# only for environments where SpeechBrain is unavailable.
SPEAKER_VAULT_ENABLED = os.getenv("VOICETRUST_SPEAKER_VAULT_ENABLED", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SPEAKER_MODEL = os.getenv("VOICETRUST_SPEAKER_MODEL", "speechbrain/spkrec-ecapa-voxceleb")
SPEAKER_MATCH_THRESHOLD = float(os.getenv("VOICETRUST_SPEAKER_MATCH_THRESHOLD", "0.75"))
SPEAKER_EMBEDDING_DIM = int(os.getenv("VOICETRUST_SPEAKER_EMBEDDING_DIM", "64"))

# ---- Persistent speaker identity vault ----
# Explicit model provenance: every stored embedding records which encoder,
# checkpoint version, and normalization produced it. When the encoder or its
# version changes, existing enrollments are gated (version-mismatch) rather
# than silently compared across incompatible embedding spaces.
SPEAKER_MODEL_VERSION = os.getenv("VOICETRUST_SPEAKER_MODEL_VERSION", "ecapa-voxceleb-v1")
SPEAKER_EMBEDDING_NORMALIZATION = os.getenv(
    "VOICETRUST_SPEAKER_EMBEDDING_NORMALIZATION", "l2"
)
# Enrollment aggregation: 'centroid' averages all active L2-normalized sample
# embeddings and re-normalizes the mean ('robust' would trim outliers; kept
# simple until real enrollment noise data exists).
SPEAKER_ENROLLMENT_AGGREGATION = os.getenv(
    "VOICETRUST_SPEAKER_ENROLLMENT_AGGREGATION", "centroid"
)
# Maximum active enrollment samples retained per identity (privacy: bounds
# stored biometric data; oldest samples are pruned when exceeded).
SPEAKER_MAX_ENROLLMENT_SAMPLES = int(
    os.getenv("VOICETRUST_SPEAKER_MAX_ENROLLMENT_SAMPLES", "8")
)

# ---- Intent keyphrases (Phase 1 lightweight matcher) ----
HIGH_RISK_KEYPHRASES = [
    "wire transfer", "urgent transfer", "send money immediately", "confidential",
    "otp", "one time password", "verification code", "password", "routing number",
    "account number", "gift card", "crypto wallet", "don't tell anyone",
    "act now", "immediately approve", "bypass approval", "cash out",
]
