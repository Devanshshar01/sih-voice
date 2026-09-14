---
title: SatyaVoice Anti-Spoof (ZeroGPU)
emoji: 🛡️
colorFrom: blue
colorTo: indigo
sdk: gradio
app_file: app.py
pinned: false
---

# SatyaVoice — MMS-300M Anti-Deepfake detector (ZeroGPU)

Single-purpose GPU Space: acoustic deepfake detection for the SatyaVoice
anti-spoof stage.

- **Model:** [nii-yamagishilab/mms-300m-anti-deepfake](https://huggingface.co/nii-yamagishilab/mms-300m-anti-deepfake)
  (NII/Yamagishi Lab — post-trained `facebook/mms-300m`; **CC BY-NC-SA 4.0**,
  research/educational use). Used off-the-shelf; SatyaVoice fine-tuning is a
  future task.
- **Loaded once** at Space startup, `eval()` mode, GPU-resident; every
  request runs under `torch.inference_mode()`. No per-request loading.
- **Input** (named API endpoint `detect`): JSON string
  `{"wav": [floats], "sample_rate": 16000}` — one 16 kHz mono window.
- **Output:** `{"ok": true, "fake_probability": f, "real_probability": f,
  "predicted_label": "fake"|"real", "inference_latency_ms": ms, ...}` or
  `{"ok": false, "status": "degraded", ...}` (failures are NEVER reported
  as genuine).
- The Render backend consumes this Space via the Gradio Client; the schema
  contract is documented in `hf_zero_gpu/inference.py` of the main repo.
