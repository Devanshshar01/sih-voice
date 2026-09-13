"""Test script to get zeroGPU latency."""
import os
import sys

sys.path.insert(0, ".")
os.environ["VOICETRUST_DETECTOR_MODE"] = "zerogpu"
os.environ.setdefault("HF_ZERO_GPU_SPACE", "https://devanshshar01-satyavoice-gpu.hf.space")

from app.services.ml_detector import get_detector
import numpy as np
import time

detector = get_detector("zerogpu")

# Wait for 5 requests
for i in range(5):
    t0 = time.time()
    audio = np.zeros(64000, dtype=np.float32)
    res = detector.predict(audio)
    t1 = time.time()
    print(f"Request {i+1}: { (t1-t0)*1000:.2f} ms")
    print(res)
