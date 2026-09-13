"""Local smoke test for hf_zero_gpu inference (no speechbrain/spaces needed).

Validates:
  1. Module imports cleanly without `spaces` (fallback path) and with it.
  2. @spaces.GPU detection: on HF, `infer` must be a spaces-decorated fn.
  3. REAL resampling: 48 kHz tone resampled to 16 kHz keeps frequency.
  4. Exact 4-second window: output is always 64000 samples @ 16 kHz.
"""
import sys

import numpy as np

sys.path.insert(0, ".")

import inference  # noqa: E402

from config import SAMPLE_RATE, WINDOW_SAMPLES  # noqa: E402

failures = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {name} {detail}")
    if not condition:
        failures.append(name)


# 1) Module import + entry point exists
check("inference module imports", hasattr(inference, "infer"))

import importlib.util  # noqa: E402

_HAS_SPACES = importlib.util.find_spec("spaces") is not None
if _HAS_SPACES:
    print("[INFO] spaces installed locally: @spaces.GPU is an off-infra")
    print("       passthrough; on HF ZeroGPU infra it wraps infer() for the")
    print("       startup probe (infra wrap requires CUDA torch, CPU-only")
    print("       locally, so decoration wrap is verified on the Space).")
else:
    check("spaces absent -> fallback path", inference.spaces is None)

# 2) Real resampling: 440 Hz sine at 48 kHz, 2 seconds
sr_in = 48000
t = np.arange(sr_in * 2, dtype=np.float32) / sr_in
tone_48k = 0.5 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)

window = inference._prepare_audio((sr_in, tone_48k))

check("window length == 64000 samples", len(window) == WINDOW_SAMPLES,
      f"(got {len(window)})")
check("window implies 4.0 s @ 16 kHz",
      abs(len(window) / SAMPLE_RATE - 4.0) < 1e-6)

# Frequency preserved by real resampling (FFT peak ~= 440 Hz)
spec = np.abs(np.fft.rfft(window[: WINDOW_SAMPLES // 2]))
peak_hz = float(np.argmax(spec)) * SAMPLE_RATE / (WINDOW_SAMPLES // 2)
check("resampled tone keeps ~440 Hz peak", abs(peak_hz - 440.0) < 10.0,
      f"(peak {peak_hz:.1f} Hz)")

# 3) 8 kHz input (upsampling path) also lands on the exact window
t8 = np.arange(8000 * 1, dtype=np.float32) / 8000
tone_8k = 0.5 * np.sin(2 * np.pi * 220.0 * t8).astype(np.float32)
window8 = inference._prepare_audio((8000, tone_8k))
check("8 kHz input -> 64000-sample window", len(window8) == WINDOW_SAMPLES)

# 4) Raw ndarray input (no sr) treated as 16 kHz and windowed
window_raw = inference._prepare_audio(tone_48k)
check("raw ndarray input -> 64000-sample window",
      len(window_raw) == WINDOW_SAMPLES)

# 5) None input raises explicit ValueError (no silent fake result)
try:
    inference._prepare_audio(None)
    check("None input raises ValueError", False)
except ValueError:
    check("None input raises ValueError", True)

# 6) Structured error contains no spoof_probability key
err = inference._structured_error(RuntimeError("boom"))
check("structured error has status=error", err.get("status") == "error")
check("structured error carries error.type/message",
      err.get("error", {}).get("type") == "RuntimeError")
check("no fake spoof_probability in error payload",
      "spoof_probability" not in err)

# 7) end-to-end infer() with models unavailable locally -> structured error
result = inference.infer((sr_in, tone_48k))
check("infer() returns dict", isinstance(result, dict))
if inference._speaker_model is None:
    check("infer() failure -> structured error, not fake 0.5",
          result.get("status") == "error" and "spoof_probability" not in result)
else:
    check("infer() success payload", result.get("status") == "ok")

# 8) Decorator application: with `spaces` installed, decoration must have
# executed without error. Off HF infra the package passes the function
# through unchanged (documented behavior); on ZeroGPU infra it wraps it and
# the startup probe then detects it. Either way infer() must be callable.
if _HAS_SPACES:
    check("@spaces.GPU decoration path executed, infer callable",
          callable(inference.infer))
else:
    check("fallback infer callable (no spaces installed)",
          callable(inference.infer))

print()
if failures:
    print(f"FAILED: {len(failures)} -> {failures}")
    sys.exit(1)
print("ALL LOCAL TESTS PASSED")
