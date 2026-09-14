"""Run one real-detector inference after the checkpoint is available locally.

Active checkpoint: nii-yamagishilab/mms-300m-anti-deepfake (NII Yamagishi
Lab, CC BY-NC-SA 4.0). Verifies the fake/real probability mapping and the
SatyaVoice acoustic-score direction (acoustic_score == fake probability).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app import config
from app.services.ml_detector import get_detector


def main() -> None:
    detector = get_detector(
        "real",
        model_path=config.VOICE_MODEL_PATH or None,
        model_id=config.VOICE_MODEL_ID,
        device=config.VOICE_MODEL_DEVICE,
        revision=config.VOICE_MODEL_REVISION,
    )
    result = detector.predict(np.zeros(config.SAMPLE_RATE_HZ, dtype=np.float32))
    score = result["acoustic_score"]
    details = result["details"]
    assert 0.0 <= score <= 1.0
    assert details["mode"] == "real"
    assert details["model"] == "nii-yamagishilab/mms-300m-anti-deepfake"
    # Direction contract: acoustic_score IS the fake probability.
    assert abs(score - details["fake_probability"]) < 1e-6
    # Probabilities are normalized: fake + real ~= 1.
    assert abs(details["fake_probability"] + details["real_probability"] - 1.0) < 1e-3
    print("[ok] MMS-300M-AntiDeepfake detector ->", result)


if __name__ == "__main__":
    main()
