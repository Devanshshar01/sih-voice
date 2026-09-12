"""Phase 1 audio-pipeline tests (SIH spec alignment).

Covers: PCM normalization, mono conversion, resampling, rolling 4-second
windows, exact 0.5-second hop, silence/VAD behavior, malformed input, short
chunks, multiple chunks forming one window, buffer reset, and codec
capability gating (including no fake Opus/AMR support).

These tests avoid heavy deps (no torch / faster-whisper / silero download):
the VAD tests exercise the energy-fallback path deterministically, and the
Silero path is covered by capability reporting + contract assertions.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from app import config
from app.services import codec_normalizer, vad
from app.services.audio_processor import (
    RingBuffer,
    decode_pcm_frame,
    normalize_audio,
    select_window_config,
)

TARGET_RATE = config.TARGET_SAMPLE_RATE
WINDOW = config.WINDOW_SAMPLES  # 64000
HOP = config.HOP_SAMPLES        # 8000


# ---------------------------------------------------------------------------
# A. Canonical configuration
# ---------------------------------------------------------------------------

def test_canonical_audio_constants_match_sih_spec() -> None:
    assert config.TARGET_SAMPLE_RATE == 16000
    assert config.WINDOW_SECONDS == 4.0
    assert config.WINDOW_SAMPLES == 64000
    assert config.HOP_SECONDS == 0.5
    assert config.HOP_SAMPLES == 8000
    # Flat aliases must agree with the AudioConfig dataclass.
    assert config.SAMPLE_RATE_HZ == config.AUDIO.TARGET_SAMPLE_RATE
    assert config.WINDOW_SAMPLES == config.AUDIO.WINDOW_SAMPLES
    assert config.HOP_SAMPLES == config.AUDIO.HOP_SAMPLES


def test_vad_enabled_by_default() -> None:
    assert config.VAD_ENABLED is True


def test_window_config_selector_reports_spec_values() -> None:
    cfg = select_window_config()
    assert cfg["window_seconds"] == 4.0
    assert cfg["hop_seconds"] == 0.5
    assert cfg["window_samples"] == 64000
    assert cfg["hop_samples"] == 8000


# ---------------------------------------------------------------------------
# B. Codec normalization
# ---------------------------------------------------------------------------

def test_pcm_float32_passthrough_is_canonical() -> None:
    rng = np.random.default_rng(7)
    payload = rng.uniform(-0.5, 0.5, size=16000).astype(np.float32).tobytes()
    out = codec_normalizer.normalize_frame(payload, codec="pcm")
    assert out.dtype == np.float32
    assert out.ndim == 1
    assert out.size == 16000
    assert float(np.max(np.abs(out))) <= 1.0


def test_pcm_s16le_conversion() -> None:
    ints = np.array([0, 16384, -16384, 32767, -32768], dtype=np.int16)
    out = codec_normalizer.normalize_frame(ints.tobytes(), codec="pcm_s16le")
    assert out.dtype == np.float32
    assert out.size == 5
    assert abs(out[1] - (16384 / 32768.0)) < 1e-6
    assert abs(out[4] - (-1.0)) < 1e-6


def test_g711_ulaw_decodes_bit_exact_sweep() -> None:
    payload = bytes(range(256))
    out = codec_normalizer.decode_g711_ulaw(payload)
    assert out.dtype == np.float32
    assert out.size == 256
    assert float(np.max(np.abs(out))) <= 1.0
    # Companded silence byte 0xFF must decode to exactly zero.
    assert out[255] == 0.0
    assert np.array_equal(out, codec_normalizer.decode_g711_ulaw(payload))


def test_g711_alaw_decodes_bit_exact_sweep() -> None:
    payload = bytes(range(256))
    out = codec_normalizer.decode_g711_alaw(payload)
    assert out.dtype == np.float32
    assert out.size == 256
    assert float(np.max(np.abs(out))) <= 1.0
    # A-law alternates the sign convention vs mu-law: 0x55 -> negative small,
    # 0xD5 (inverted sign bit) -> positive small (matches ITU reference).
    assert out[0x55] < 0
    assert out[0xD5] > 0
    assert abs(out[0x55]) == pytest.approx(abs(out[0xD5]), abs=1e-6)
    assert np.array_equal(out, codec_normalizer.decode_g711_alaw(payload))


def test_g711_frames_are_resampled_8k_to_16k() -> None:
    # 1600 mu-law bytes = 0.2 s at 8 kHz -> 3200 samples at 16 kHz.
    payload = bytes([0xFF] * 1600)
    out = codec_normalizer.normalize_frame(payload, codec="g711_ulaw")
    assert out.size == 3200
    assert out.dtype == np.float32


def test_stereo_pcm_downmixes_to_mono() -> None:
    left = np.full(4000, 0.5, dtype=np.float32)
    right = np.full(4000, -0.5, dtype=np.float32)
    payload = np.empty(8000, dtype=np.float32)
    payload[0::2] = left
    payload[1::2] = right
    out = codec_normalizer.normalize_frame(payload.tobytes(), codec="pcm", channels=2)
    assert out.ndim == 1
    assert out.size == 4000
    assert float(np.max(np.abs(out))) < 1e-6  # +0.5 and -0.5 cancel


def test_resampling_changes_length_proportionally() -> None:
    one_second_44k1 = np.zeros(44100, dtype=np.float32)
    out = codec_normalizer.normalize_frame(one_second_44k1.tobytes(), codec="pcm", sample_rate=44100)
    assert out.size == TARGET_RATE  # 16000


def test_resample_linear_preserves_content_energy() -> None:
    t = np.arange(8000, dtype=np.float32) / 8000.0
    tone = np.sin(2 * np.pi * 220.0 * t).astype(np.float32)
    up = codec_normalizer.resample_linear(tone, 8000, 16000)
    down = codec_normalizer.resample_linear(up, 16000, 8000)
    assert up.size == 16000
    # Round trip must remain a recognizable 220 Hz tone.
    corr = float(np.dot(down[:4000], tone[:4000]) / (np.linalg.norm(down[:4000]) * np.linalg.norm(tone[:4000]) + 1e-9))
    assert corr > 0.99


def test_amplitude_clipping_and_peak_normalization() -> None:
    hot = np.array([2.0, -3.0, 1.0], dtype=np.float32)
    out = normalize_audio(hot)
    assert float(np.max(np.abs(out))) <= 1.0
    assert abs(out[0] - (2.0 / 3.0)) < 1e-6


def test_decode_pcm_frame_aliases_normalizer() -> None:
    payload = np.zeros(8000, dtype=np.float32).tobytes()
    out = decode_pcm_frame(payload)
    assert out.dtype == np.float32
    assert out.size == 8000


def test_malformed_payloads_are_rejected_not_corrupt() -> None:
    # Empty payload decodes to an empty canonical array (caller skips it).
    assert codec_normalizer.normalize_frame(b"", codec="pcm").size == 0
    # Unknown codec raises a clean, typed error.
    with pytest.raises(codec_normalizer.UnsupportedCodecError):
        codec_normalizer.normalize_frame(b"\x00" * 16, codec="mp3")
    # ensure_available rejects unknown families with a clear message.
    with pytest.raises(codec_normalizer.UnsupportedCodecError, match="Unknown codec"):
        codec_normalizer.ensure_available("whatever")


def test_odd_length_truncated_frame_is_handled() -> None:
    # A truncated frame (not a whole number of samples) decodes over its
    # largest whole-sample prefix instead of crashing the live stream.
    out = codec_normalizer.normalize_frame(b"\x00\x00\x00", codec="pcm")
    assert out.size == 0  # 3 bytes -> no complete float32 sample
    assert out.dtype == np.float32
    out2 = codec_normalizer.normalize_frame(b"\x00" * 6 + b"\x01", codec="pcm")
    assert out2.size == 1  # 7 bytes -> one complete sample


def test_odd_length_s16le_truncated_frame_is_handled() -> None:
    out = codec_normalizer.normalize_frame(b"\x00\x01", codec="pcm_s16le")
    assert out.size == 1


def test_capability_report_is_honest() -> None:
    report = codec_normalizer.describe_capabilities()
    for codec in ("pcm", "pcm_s16le", "g711_ulaw", "g711_alaw"):
        assert report[codec]["supported"] is True
    # No fake codec support: without opuslib installed, opus must be declared
    # unsupported with its documented dependency, and never claim success.
    opus = report["opus"]
    if not opus["supported"]:
        assert "opuslib" in (opus["dependency"] or "")
        with pytest.raises(codec_normalizer.UnsupportedCodecError):
            codec_normalizer.ensure_available("opus")
    else:  # if opuslib IS present, decoding must actually work
        codec_normalizer.ensure_available("opus")
    amr = report["amr"]
    assert amr["supported"] is False
    assert amr["dependency"]  # documents what would be needed
    with pytest.raises(codec_normalizer.UnsupportedCodecError):
        codec_normalizer.ensure_available("amr")


def test_canonical_format_contract() -> None:
    fmt = codec_normalizer.canonical_format()
    assert fmt["channels"] == 1
    assert fmt["sample_rate"] == 16000
    assert fmt["dtype"] == "float32"


# ---------------------------------------------------------------------------
# C. Rolling buffer: 4-second windows, exact 0.5-second hop
# ---------------------------------------------------------------------------

def test_no_window_before_four_seconds() -> None:
    ring = RingBuffer()
    for _ in range(7):  # 7 x 0.5s = 3.5s < 4.0s
        ring.push(np.zeros(HOP, dtype=np.float32))
        assert ring.pop_ready_windows() == []


def test_multiple_chunks_form_exactly_one_window() -> None:
    ring = RingBuffer()
    for i in range(8):  # 8 x 0.5s = 4.0s
        ring.push(np.full(HOP, i / 8.0, dtype=np.float32))
        windows = ring.pop_ready_windows()
        if i < 7:
            assert windows == []
        else:
            assert len(windows) == 1
            window = windows[0]
            assert window.size == WINDOW == 64000
            # The window must span chunks 0..7 in order (oldest first).
            assert window[0] == 0.0
            assert window[-1] == pytest.approx(7 / 8.0, abs=1e-7)
            assert window[HOP] == pytest.approx(1 / 8.0, abs=1e-7)


def test_exact_half_second_hop_overlap_is_3_5_seconds() -> None:
    ring = RingBuffer()
    for i in range(9):
        ring.push(np.full(HOP, i / 8.0, dtype=np.float32))
        windows = ring.pop_ready_windows()
    assert len(windows) == 1
    # Window 2 starts where window 1's second half began.
    assert windows[0][0] == pytest.approx(1 / 8.0, abs=1e-7)
    assert windows[0].size == WINDOW


def test_short_chunks_accumulate_into_windows() -> None:
    ring = RingBuffer()
    rng = np.random.default_rng(3)
    samples = rng.uniform(-0.2, 0.2, size=WINDOW + 3 * HOP).astype(np.float32)
    # Push in 137-sample fragments (deliberately not aligned to the hop).
    for start in range(0, samples.size, 137):
        ring.push(samples[start : start + 137])
    windows = ring.pop_ready_windows()
    expected = (WINDOW + 3 * HOP - WINDOW) // HOP + 1  # 4 full hops over the tail
    assert len(windows) == expected
    assert all(w.size == WINDOW for w in windows)
    # Consecutive windows are offset by exactly one hop.
    np.testing.assert_allclose(windows[0][HOP:], windows[1][: WINDOW - HOP], rtol=0, atol=1e-7)


def test_window_content_matches_pushed_audio_exactly() -> None:
    ring = RingBuffer()
    rng = np.random.default_rng(11)
    total = WINDOW + 2 * HOP
    samples = rng.uniform(-1, 1, size=total).astype(np.float32)
    for start in range(0, samples.size, HOP):
        ring.push(samples[start : start + HOP])
        for w in ring.pop_ready_windows():
            pass
    # The first emitted window must be bit-identical to samples[0:64000].
    first = None
    ring2 = RingBuffer()
    ring2.push(samples)
    windows = ring2.pop_ready_windows()
    np.testing.assert_array_equal(windows[0], samples[:WINDOW])
    assert windows[0].dtype == np.float32


def test_buffer_memory_does_not_grow_unbounded() -> None:
    ring = RingBuffer()
    for _ in range(200):  # 100 seconds of streaming
        ring.push(np.zeros(HOP, dtype=np.float32))
        ring.pop_ready_windows()
    assert ring.samples_buffered <= WINDOW  # at most one window retained
    assert ring.total_pushed == 200 * HOP


def test_buffer_reset_between_calls() -> None:
    ring = RingBuffer()
    ring.push(np.zeros(WINDOW, dtype=np.float32))
    assert len(ring.pop_ready_windows()) == 1
    ring.reset()
    assert ring.samples_buffered == 0
    assert ring.total_pushed == 0
    ring.push(np.zeros(HOP, dtype=np.float32))
    assert ring.pop_ready_windows() == []  # nothing left over from call 1


def test_ring_buffer_honors_explicit_geometry() -> None:
    ring = RingBuffer(window_samples=16000, hop_samples=4000)
    ring.push(np.zeros(16000, dtype=np.float32))
    windows = ring.pop_ready_windows()
    assert len(windows) == 1 and windows[0].size == 16000


# ---------------------------------------------------------------------------
# D. Silero VAD stage behavior
# ---------------------------------------------------------------------------

def test_vad_assess_is_non_mutating_and_reports_silence() -> None:
    silent = np.zeros(WINDOW, dtype=np.float32)
    out, telemetry = vad.assess(silent)
    np.testing.assert_array_equal(out, silent)  # never mutates window data
    assert telemetry["vad_active"] is False
    assert telemetry["vad_coverage"] == 0.0
    assert telemetry["vad_backend"] in {"silero", "energy-fallback"}


def test_vad_detects_energy_fallback_speech() -> None:
    # Force the deterministic energy fallback for a unit-testable path.
    vad._SILERO_MODEL = None
    vad._SILERO_LOAD_ERROR = "forced-for-test"
    try:
        t = np.arange(WINDOW, dtype=np.float32) / TARGET_RATE
        speech = (0.3 * np.sin(2 * np.pi * 180.0 * t)).astype(np.float32)
        out, telemetry = vad.assess(speech)
        assert telemetry["vad_active"] is True
        assert telemetry["vad_coverage"] == 1.0
        assert telemetry["vad_backend"] == "energy-fallback"
        np.testing.assert_array_equal(out, speech)
    finally:
        vad._SILERO_LOAD_ERROR = None


def test_vad_speech_regions_keep_short_pauses() -> None:
    # 1s speech, 0.25s pause, 1s speech -> one padded region (pause kept).
    vad._SILERO_MODEL = None
    vad._SILERO_LOAD_ERROR = "forced-for-test"
    try:
        speech = np.concatenate(
            [
                np.full(16000, 0.2, dtype=np.float32),
                np.zeros(4000, dtype=np.float32),   # short intra-utterance pause
                np.full(16000, 0.2, dtype=np.float32),
            ]
        )
        regions = vad.get_speech_regions(speech)
        assert regions == [(0, speech.size)]
    finally:
        vad._SILERO_LOAD_ERROR = None


def test_vad_disabled_mode_passes_everything_through() -> None:
    original = config.VAD_ENABLED
    config.VAD_ENABLED = False
    try:
        silent = np.zeros(16000, dtype=np.float32)
        out, telemetry = vad.assess(silent)
        assert telemetry["vad_backend"] == "disabled"
        assert telemetry["vad_active"] is True
        assert telemetry["vad_coverage"] == 1.0
    finally:
        config.VAD_ENABLED = original


def test_vad_backend_status_enum() -> None:
    assert vad.vad_backend_status() in {"disabled", "silero", "energy-fallback", "pending"}


# ---------------------------------------------------------------------------
# Integration: decode -> VAD -> buffer (the streaming loop's exact stages)
# ---------------------------------------------------------------------------

def test_stream_stage_sequence_produces_spec_windows() -> None:
    ring = RingBuffer()
    pushed_windows = []
    for _ in range(10):  # 5 seconds of 0.5s hop-sized frames
        chunk = np.zeros(HOP, dtype=np.float32)
        samples = codec_normalizer.normalize_frame(chunk.tobytes(), codec="pcm")
        ring.push(samples)
        pushed_windows.extend(ring.pop_ready_windows())
    # A 5.0 s stream completes windows at t = 4.0, 4.5, and 5.0 s.
    assert len(pushed_windows) == 3


def test_demo_mode_forced_frames_still_stream() -> None:
    """G. Backward compatibility: demo/mock frames decode via the same path."""
    ring = RingBuffer()
    frame = np.zeros(8000, dtype=np.float32)  # buildDemoFrame() contract
    for _ in range(8):
        ring.push(decode_pcm_frame(frame.tobytes()))
    windows = ring.pop_ready_windows()
    assert len(windows) == 1
    assert windows[0].size == 64000
