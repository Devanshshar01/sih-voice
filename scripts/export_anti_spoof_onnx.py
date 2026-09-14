"""Export a browser ONNX anti-spoof artifact from a transformers classifier.

IMPORTANT PROVENANCE NOTE (MMS migration):
The production CLOUD detector is nii-yamagishilab/mms-300m-anti-deepfake,
which uses a fairseq/PyTorchModelHubMixin architecture and CANNOT be loaded
through transformers' AutoModelForAudioClassification — so it cannot be
exported by this script as-is. The Edge/browser ONNX artifact therefore
remains derived from a transformers-classifier checkpoint and the Edge
telemetry must keep reporting its own model_id, never the MMS checkpoint.

Set MODEL_ID below to the transformers classifier you actually want in the
browser. Do not set it to the MMS checkpoint (it will fail to load here).
"""
from __future__ import annotations

import json
from pathlib import Path

import torch
from transformers import AutoModelForAudioClassification

# Edge/browser artifact source (transformers-format classifier only).
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
    "note": (
        "Edge/browser ONNX artifact — independent of the cloud MMS-300M-"
        "AntiDeepfake detector. Model identities are reported separately "
        "and must stay truthful in telemetry."
    ),
}
(OUT_DIR / "anti_spoof.metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

print(f"Exported ONNX model to {onnx_path}")
print(f"Saved metadata to {OUT_DIR / 'anti_spoof.metadata.json'}")
