# SatyaVoice Detector Model Card

## Active production detector (acoustic anti-spoof stage)

- **Model:** [nii-yamagishilab/mms-300m-anti-deepfake](https://huggingface.co/nii-yamagishilab/mms-300m-anti-deepfake)
  — "MMS-300M-AntiDeepfake"
- **Publisher:** Yamagishi Lab, National Institute of Informatics (NII), Japan
- **Base model:** `facebook/mms-300m` (Wav2Vec 2.0 architecture SSL front-end)
- **Back-end:** AdaptiveAvgPool1d + fully connected binary classifier (2 classes)
- **License:** **CC BY-NC-SA 4.0** — research/educational use only.
  Attribution: NII Yamagishi Lab. NOT cleared for commercial deployment
  without a separate license decision.
- **Usage status:** off-the-shelf, post-trained checkpoint as published.
  **SatyaVoice has NOT fine-tuned it.** Fine-tuning is a documented future
  task. No Indian-language performance claim is made or verified.

## Input / output

- **Input:** 16 kHz mono speech, arbitrary length (SatyaVoice sends
  canonical 4-second / 64,000-sample windows from the existing ring buffer;
  preprocessing is `layer_norm` over the whole window, per the official
  inference example).
- **Output (softmax over 2 logits):** index **0 = Fake**, index **1 = Real**
  (verified from the official model card's output formatting).
- **SatyaVoice convention:** `acoustic_score` = `P(fake)` — higher fake
  probability means higher fraud risk. The mapping is regression-tested
  (`tests/test_mms_detector.py::test_acoustic_score_equals_fake_probability_not_real`,
  `test_risk_direction_fake_probability_raises_risk`).

## Loading path (critical)

The checkpoint is a fairseq-style model distributed through
`PyTorchModelHubMixin`. It has **no `transformers` classifier head**, so
`AutoModelForAudioClassification` **cannot** load it. The exact loading
path used (mirroring the official model card):

```
fairseq Wav2Vec2Config(quantize_targets=True, extractor_mode="layer_norm",
    layer_norm_first=True, final_dim=768, encoder_layers=24,
    encoder_embed_dim=1024, encoder_ffn_embed_dim=4096,
    encoder_attention_heads=16, conv_bias=True, ...)
-> Wav2Vec2Model front-end
-> AdaptiveAvgPool1d(1) -> Linear(1024 -> 2)
-> DeepfakeDetector.from_pretrained("nii-yamagishilab/mms-300m-anti-deepfake")
-> .eval(); inference under torch.inference_mode()
```

Implementation: `app/services/anti_spoof_provider.py` (in-process) and
`hf_zero_gpu/inference.py` (ZeroGPU Space). Dependencies per the official
card: `fairseq==0.12.2`, `safetensors==0.5.3`, `soundfile==0.13.1`,
`huggingface-hub==0.31.1` (pinned in `hf_zero_gpu/requirements.txt` only —
fairseq conflicts with this repo's `numpy>=2` runtime, see below).

## Deployment topologies

| Mode | Where the model runs | Notes |
|---|---|---|
| `VOICETRUST_DETECTOR_MODE=real` | backend process (needs torch + fairseq in a compatible env) | full local control |
| `VOICETRUST_DETECTOR_MODE=remote_hf` | **hf_zero_gpu ZeroGPU Space** (only GPU-heavy stage in the stack) | web tier needs only `gradio_client`; response mapped by `app/services/hf_zero_gpu_client.py` |

ZeroGPU efficiency rules enforced in `hf_zero_gpu/inference.py`: the model
loads **exactly once** at Space startup (double-checked locking), stays
GPU-resident in `eval()` mode, and every request runs under
`torch.inference_mode()` with no per-request architecture construction.

fairseq 0.12.2 predates numpy 2 and may not co-install with this repo's
`numpy>=2`. It is therefore pinned **only** in `hf_zero_gpu/requirements.txt`
(Space environment); the Render backend either runs `real` mode in a
fairseq-compatible environment or uses `remote_hf`.

## Failure semantics

- Empty/malformed/NaN/Inf input → sanitized or degraded
  (`acoustic_score = 0.5`, `status: degraded_input`); the WebSocket never
  crashes and the score is **never** presented as "genuine".
- Inference exception → `status: degraded_output` (in-process) or the
  stream pipeline's `anti_spoof_unavailable` degraded flag; fusion applies
  the documented degraded-evidence penalty.
- Space unreachable (remote mode) → `degraded_remote` with the error in
  telemetry. Failures are never mapped to a low (benign) score.

## Performance instrumentation

`acoustic_score` details include `inference_latency_ms` (model call only)
and one-time `load_ms`. The ZeroGPU path additionally reports
`remote_inference_ms` and `remote_device`, so cloud-GPU latency stays
separately identifiable from backend-local latency. **No end-to-end
<500 ms claim is made for the real-model cloud path** — measure with
`scripts/benchmark_latency.py` on the deployment host before claiming it.

## Published evaluation (publisher-reported, NOT SatyaVoice benchmarks)

The official card reports, for this 300M checkpoint: ADD2023 EER 7.93%,
In-the-Wild EER 2.90%, Deepfake-Eval-2024 EER 32.84% (4 s inputs: EER
17.15%, ROC AUC 0.90). These are the publisher's numbers on their
protocols — SatyaVoice has not independently verified any of them, and
none constitute an Indic-language or telephony result.

## Edge/browser model identity (truthfulness)

The Edge/ONNX browser artifact (`public/models/anti_spoof.onnx`, exported
by `scripts/export_anti_spoof_onnx.py`) is derived from a
transformers-format classifier checkpoint and is **NOT** the MMS
checkpoint (fairseq models cannot be exported by that script). Edge
telemetry reports the ONNX metadata's own `model_id`; cloud telemetry
reports the MMS model. The two identities are deliberately kept separate
and truthful.

## Intended use

Research, prototype evaluation, and risk-policy demonstration. Not a
production fraud decision service; not a standalone identity or financial
authorization mechanism. The CC BY-NC-SA 4.0 license additionally
restricts commercial use of the model weights.

## ASR companion component

Unchanged by this migration: faster-whisper `small`, CPU `int8`, per the
existing configuration (`VOICETRUST_ASR_*`). Speaker matching remains
ECAPA-TDNN via the persistent vault.
