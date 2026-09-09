"""Run one real-detector inference after the checkpoint is available locally."""
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
    assert 0.0 <= score <= 1.0
    assert result["details"]["mode"] == "real"
    print("[ok] real detector ->", result)


if __name__ == "__main__":
    main()
