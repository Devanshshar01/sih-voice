"""
Codec normalization layer (SIH spec item B).

Every input family is decoded to one canonical format before it touches the
detector, VAD, or speaker vault:

    mono · float32 · 16 kHz · amplitude-normalized to [-1, 1]

Design rules:
  * No fake codec support. If the runtime cannot decode a family (Opus needs
    `opuslib` + libopus; AMR needs a native AMR decoder), `ensure_available()`
    says so explicitly and `normalize_frame()` raises `UnsupportedCodecError`.
  * No conversion code in the WebSocket handler: stream.py declares the
    negotiated codec and calls this service only.
  * Canonicalization is idempotent where it can be (resample only when needed,
    stereo->mono only when needed).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np

from app import config

# Input families. "pcm" is the browser contract (AudioWorklet Float32 chunks);
# the rest exist for telephony/interconnect ingestion.
CODEC_FAMILIES = {
    "pcm",         # raw float32 LE, mono or interleaved stereo, any sane rate
    "pcm_s16le",   # 16-bit signed LE integers
    "g711_ulaw",   # G.711 mu-law, 8 kHz, 8-bit companded
    "g711_alaw",   # G.711 A-law, 8 kHz, 8-bit expander
    "opus",        # capability-gated: requires opuslib + libopus
    "amr",         # capability-gated: requires a native AMR decoder (AMR-NB/WB)
}

_RAW_SAMPLE_FAMILIES = {"pcm", "pcm_s16le", "g711_ulaw", "g711_alaw"}
_OPUS_RATES = {48000, 24000, 16000, 12000, 8000}
_AMR_RATES = {8000, 16000}  # AMR-NB / AMR-WB native rates


class UnsupportedCodecError(ValueError):
    """Raised when the runtime lacks the native decoder for a negotiated codec."""


@dataclass
class _Capability:
    supported: bool
    decoder: str
    dependency: Optional[str] = None
    note: str = ""


def _opus_capability() -> _Capability:
    try:
        import opuslib  # noqa: F401

        return _Capability(True, "opuslib.Decoder (libopus)", "opuslib>=2.0.0")
    except Exception as exc:  # ImportError or missing libopus native library
        return _Capability(
            False,
            "",
            "opuslib>=2.0.0 (requires the native libopus shared library)",
            f"opuslib unavailable: {exc.__class__.__name__}",
        )


def _amr_capability() -> _Capability:
    try:
        import audioop  # noqa: F401  (stdlib: cannot decode AMR payload framing)

        return _Capability(
            False,
            "",
            "native AMR decoder (e.g. libamr / vo-amrwbenc bindings)",
            "No pure-Python or stdlib AMR payload decoder exists; per the spec, "
            "support is declared only where a real decoder is present.",
        )
    except Exception:  # pragma: no cover - audioop exists on all supported Pythons
        return _Capability(False, "", "native AMR decoder", "audioop unavailable")


def describe_capabilities() -> Dict[str, dict]:
    """Honest capability report for telemetry / /health style introspection."""
    report: Dict[str, dict] = {}
    for codec in sorted(CODEC_FAMILIES):
        if codec in _RAW_SAMPLE_FAMILIES:
            entry = {"supported": True, "decoder": "in-process numpy", "dependency": None, "note": ""}
        elif codec == "opus":
            cap = _opus_capability()
            entry = {
                "supported": cap.supported,
                "decoder": cap.decoder,
                "dependency": cap.dependency,
                "note": cap.note,
            }
        else:  # amr
            cap = _amr_capability()
            entry = {
                "supported": cap.supported,
                "decoder": cap.decoder,
                "dependency": cap.dependency,
                "note": cap.note,
            }
        report[codec] = entry
    return report


def ensure_available(codec: str) -> None:
    """Raise UnsupportedCodecError unless `codec` can be decoded in this runtime."""
    codec = (codec or "").strip().lower()
    if codec not in CODEC_FAMILIES:
        raise UnsupportedCodecError(
            f"Unknown codec '{codec}'. Supported families: {sorted(CODEC_FAMILIES)}"
        )
    if codec in _RAW_SAMPLE_FAMILIES:
        return
    cap = _opus_capability() if codec == "opus" else _amr_capability()
    if not cap.supported:
        raise UnsupportedCodecError(
            f"Codec '{codec}' is not decodable in this runtime. "
            f"Install the documented dependency and restart: {cap.dependency}"
        )


# ---------------------------------------------------------------------------
# G.711 expanders (bit-exact ITU-T G.711 reconstruction, vectorized)
# ---------------------------------------------------------------------------

def _build_ulaw_table() -> np.ndarray:
    table = np.empty(256, dtype=np.float32)
    for i in range(256):
        ulaw = ~np.uint8(i) & np.uint8(0xFF)
        ulaw = int(ulaw)
        sign = ulaw & 0x80
        exponent = (ulaw >> 4) & 0x07
        mantissa = ulaw & 0x0F
        sample = ((mantissa << 3) + 0x84) << exponent
        sample -= 0x84  # bias removal
        value = sample / 32768.0
        table[i] = -value if sign else value
    return table


def _build_alaw_table() -> np.ndarray:
    # ITU-T G.711 A-law: after the 0x55 alternate-bit inversion, a set sign
    # bit encodes a POSITIVE value (inverted convention vs. mu-law).
    table = np.empty(256, dtype=np.float32)
    for i in range(256):
        alaw = i ^ 0x55
        sign = alaw & 0x80
        exponent = (alaw >> 4) & 0x07
        mantissa = alaw & 0x0F
        if exponent == 0:
            sample = (mantissa << 4) + 8
        else:
            sample = ((mantissa << 4) + 0x108) << (exponent - 1)
        value = sample / 32768.0
        table[i] = value if sign else -value
    return table


_ULAW_TABLE = _build_ulaw_table()
_ALAW_TABLE = _build_alaw_table()


def decode_g711_ulaw(payload: bytes) -> np.ndarray:
    return _ULAW_TABLE[np.frombuffer(payload, dtype=np.uint8)]


def decode_g711_alaw(payload: bytes) -> np.ndarray:
    return _ALAW_TABLE[np.frombuffer(payload, dtype=np.uint8)]


# ---------------------------------------------------------------------------
# Canonicalization helpers
# ---------------------------------------------------------------------------

def _to_float32(samples: np.ndarray) -> np.ndarray:
    """Map arbitrary integer/floating input to float32 in [-1, 1]."""
    samples = np.asarray(samples)
    if samples.dtype == np.float32 or samples.dtype == np.float64:
        out = samples.astype(np.float32)
    elif samples.dtype == np.int16:
        out = samples.astype(np.float32) / 32768.0
    elif samples.dtype == np.int32:
        out = samples.astype(np.float32) / 2147483648.0
    elif samples.dtype == np.uint8:
        out = (samples.astype(np.float32) - 128.0) / 128.0
    else:
        out = samples.astype(np.float32)
    return np.clip(out, -1.0, 1.0)


def _to_mono(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 1:
        return samples
    # Interleaved (N, C) or (C, N): average channels into one mono track.
    if samples.shape[0] > samples.shape[1]:  # (N, C)
        return samples.mean(axis=1, dtype=np.float32).astype(np.float32)
    return samples.mean(axis=0, dtype=np.float32).astype(np.float32)


def resample_linear(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    """Deterministic linear-interpolation resampler (no scipy dependency)."""
    if source_rate == target_rate or samples.size == 0:
        return samples.astype(np.float32, copy=False)
    duration = samples.shape[0] / float(source_rate)
    target_length = max(1, int(round(duration * target_rate)))
    source_indices = np.linspace(0.0, samples.shape[0] - 1.0, num=samples.shape[0])
    target_indices = np.linspace(0.0, samples.shape[0] - 1.0, num=target_length)
    return np.interp(target_indices, source_indices, samples).astype(np.float32)


def normalize_waveform(samples: np.ndarray) -> np.ndarray:
    """Safety net so downstream models always see sane amplitudes."""
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        return samples
    # Replace non-finite values produced by malformed payloads.
    if not np.all(np.isfinite(samples)):
        samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    peak = float(np.max(np.abs(samples)))
    if peak > 1.0:
        samples = samples / peak
    return np.clip(samples, -1.0, 1.0)


def _linear_to_multichannel(payload: bytes, channels: int) -> np.ndarray:
    # Truncated frames (not a whole number of samples) are decoded over the
    # largest whole-sample prefix so a malformed trailing fragment cannot
    # crash the live stream.
    usable = len(payload) - (len(payload) % 4)
    flat = np.frombuffer(payload[:usable], dtype=np.float32)
    if channels <= 1 or flat.size % channels != 0:
        return flat
    return flat.reshape(-1, channels)


def _s16le_to_multichannel(payload: bytes, channels: int) -> np.ndarray:
    usable = len(payload) - (len(payload) % 2)
    flat = np.frombuffer(payload[:usable], dtype=np.int16)
    if channels <= 1 or flat.size % channels != 0:
        return _to_float32(flat)
    return _to_float32(flat.reshape(-1, channels))


def normalize_frame(
    payload: bytes,
    codec: Optional[str] = None,
    sample_rate: Optional[int] = None,
    channels: int = 1,
) -> np.ndarray:
    """
    Decode one wire frame into the canonical stream format.

    Returns exactly: mono float32 @ config.TARGET_SAMPLE_RATE in [-1, 1].
    """
    codec = (codec or "pcm").strip().lower()
    channels = max(1, int(channels or 1))

    if codec == "pcm":
        samples = _to_mono(_linear_to_multichannel(payload, channels))
        rate = int(sample_rate) if sample_rate else config.TARGET_SAMPLE_RATE
    elif codec == "pcm_s16le":
        samples = _to_mono(_s16le_to_multichannel(payload, channels))
        rate = int(sample_rate) if sample_rate else config.TARGET_SAMPLE_RATE
    elif codec == "g711_ulaw":
        samples = decode_g711_ulaw(payload)
        rate = int(sample_rate) if sample_rate else 8000
    elif codec == "g711_alaw":
        samples = decode_g711_alaw(payload)
        rate = int(sample_rate) if sample_rate else 8000
    elif codec == "opus":
        samples = _decode_opus_payload(payload)
        rate = int(sample_rate) if sample_rate else 48000
        if rate not in _OPUS_RATES:
            raise UnsupportedCodecError(
                f"Opus sample rate {rate} Hz is not a valid Opus stream rate."
            )
    elif codec == "amr":
        samples = _decode_amr_payload(payload)
        rate = int(sample_rate) if sample_rate else 8000
        if rate not in _AMR_RATES:
            raise UnsupportedCodecError(
                f"AMR sample rate {rate} Hz is not AMR-NB (8000) or AMR-WB (16000)."
            )
    else:
        raise UnsupportedCodecError(
            f"Unknown codec '{codec}'. Supported families: {sorted(CODEC_FAMILIES)}"
        )

    samples = resample_linear(np.asarray(samples, dtype=np.float32), rate, config.TARGET_SAMPLE_RATE)
    return normalize_waveform(samples)


def _decode_opus_payload(payload: bytes) -> np.ndarray:
    """Decode an Opus packet only when a real libopus decoder is present."""
    ensure_available("opus")
    import opuslib  # local import: only needed on the Opus path

    decoder = opuslib.Decoder(48000, 1)
    pcm = decoder.decode(payload, frame_size=5760)
    return _to_float32(np.frombuffer(pcm, dtype=np.int16))


def _decode_amr_payload(payload: bytes) -> np.ndarray:
    """Decode AMR-NB/WB only when a native decoder binding is present."""
    ensure_available("amr")
    raise UnsupportedCodecError(
        "AMR support requires a native decoder binding; this runtime does not ship one."
    )


def canonical_format() -> dict:
    """The contract every producer must satisfy after this module runs."""
    return {
        "codec": "pcm_f32le",
        "channels": 1,
        "sample_rate": config.TARGET_SAMPLE_RATE,
        "dtype": "float32",
        "range": [-1.0, 1.0],
    }
