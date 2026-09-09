from __future__ import annotations

import json
from pathlib import Path

import torch
from transformers import AutoModelForAudioClassification

MODEL_ID = "Hemgg/Deepfake-audio-detection"
OUT_DIR = Path("public/models")
OUT_DIR.mkdir(parents=True, exist_ok=True)

model = AutoModelForAudioClassification.from_pretrained(MODEL_ID)
model.eval()

sample_rate = 16000
example_input = torch.zeros((1, sample_rate), dtype=torch.float32)
onnx_path = OUT_DIR / "anti_spoof.onnx"

with torch.no_grad():
    torch.onnx.export(
        model,
        example_input,
        onnx_path,
        input_names=["input_values"],
        output_names=["logits"],
        dynamic_axes={
            "input_values": {0: "batch", 1: "sequence"},
            "logits": {0: "batch"},
        },
        opset_version=17,
        do_constant_folding=True,
    )

labels = {str(k): v for k, v in model.config.id2label.items()}
synthetic_index = None
for index, label in labels.items():
    lowered = label.lower()
    if any(token in lowered for token in ("spoof", "fake", "ai", "clone")):
        synthetic_index = int(index)
        break

metadata = {
    "model_id": MODEL_ID,
    "sample_rate": sample_rate,
    "labels": labels,
    "synthetic_index": synthetic_index,
    "input_length": sample_rate,
}
(OUT_DIR / "anti_spoof.metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

print(f"Exported ONNX model to {onnx_path}")
print(f"Saved metadata to {OUT_DIR / 'anti_spoof.metadata.json'}")
