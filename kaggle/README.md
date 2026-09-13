# SatyaVoice — Kaggle Development / Benchmarking Environment

> **Kaggle is a DEVELOPMENT / TESTING / BENCHMARKING environment ONLY.**
> Production and the SIH demo run on `Vercel → Render → Hugging Face ZeroGPU`.
> Kaggle must not stay online, must never receive user audio, and must never be
> a Render/Vercel dependency. It exists so we can repeatedly run the **same**
> SatyaVoice inference pipeline on a free GPU without burning the limited
> ZeroGPU quota.

## What runs on Kaggle

The **same shared pipeline** as production — `hf_zero_gpu/inference.py`
(mono → real resampling to 16 kHz → 4-second/64 000-sample window → XLS-R
anti-spoof → ECAPA-TDNN speaker embedding → structured result), executed by
`app/services/local_provider.LocalInferenceProvider`. There is **no second ML
implementation**; Kaggle imports the production code.

## Setup (10 steps)

1. **Open Kaggle** → Create New Notebook → Settings → Accelerator → **GPU T4/P100**.
2. **Enable internet** (Settings → Internet → On) for model downloads.
3. **Clone the repo** in the first cell:
   ```python
   !git clone https://github.com/Devanshshar01/sih-voice.git
   %cd sih-voice
   ```
4. **Install dependencies**:
   ```python
   !pip install -q -r kaggle/requirements-kaggle.txt
   ```
5. **Configure the checkpoint** (must match production — see Step 9 warning
   below):
   ```python
   import os
   os.environ["ANTISPOOF_MODEL_ID"] = "<fine-tuned SatyaVoice checkpoint>"
   os.environ["SPEAKER_MODEL_ID"]  = "speechbrain/spkrec-ecapa-voxceleb"
   os.environ["DEVICE"]            = "cuda"
   os.environ["INFERENCE_PROVIDER"] = "local"   # "kaggle" is an alias
   ```
6. **Run the environment check** — prints GPU name, CUDA version, PyTorch
   version, VRAM, and loaded checkpoints (never hard-coded; whatever Kaggle
   gives you):
   ```python
   !python kaggle/benchmark.py --mode sanity
   ```
7. **Sanity inference** (single structured result, no fabricated values):
   ```python
   !python kaggle/benchmark.py --mode sanity --audio /path/one_clip.wav
   ```
8. **Latency benchmark** (100+ windows after warm-up, CUDA-synchronised,
   p50/p95/p99 for XLS-R / ECAPA / combined + VRAM; writes JSON+CSV to
   `kaggle/reports/`):
   ```python
   !python kaggle/benchmark.py --mode benchmark --runs 100
   ```
9. **Accuracy evaluation** (labels come from filename prefixes
   `fake_/spoof_` vs `real_/genuine_/bonafide_`; language prefixes
   `hi_/ta_/te_/bn_/mr_/en_` enable per-language metrics — never fabricated
   when samples are insufficient):
   ```python
   !python kaggle/benchmark.py --mode evaluate --data-dir /path/labelled_wavs
   ```
10. **Cross-provider consistency** (same deterministic samples through Kaggle
    GPU **and** the production HF ZeroGPU Space; checks score deltas against a
    configurable tolerance, verdict agreement, and model-version agreement):
    ```python
    !python kaggle/consistency.py \
        --space https://devanshshar01-satyavoice-gpu.hf.space \
        --samples 5 --tolerance 0.02
    ```

## Step-9 checkpoint rule (IMPORTANT)

The default `facebook/wav2vec2-xls-r-300m` is the **BASE model with a randomly
initialised classifier head — NOT the SatyaVoice anti-spoof model**. Every
benchmark run prints the loaded checkpoint and flags the base model
explicitly. Only report "SatyaVoice anti-spoof" once the fine-tuned checkpoint
is set via `ANTISPOOF_MODEL_ID`. Report numbers as measured p50/p95/p99 only;
a single passing run is **not** an "SIH compliance" claim (the <500 ms SIH
target is the full end-to-end verdict path, not model inference alone).

## Provider switching

| Environment | `INFERENCE_PROVIDER` | Notes |
|---|---|---|
| Production (Render) | `detector` | default; in-process Render pipeline (unchanged) |
| Production (HF path) | `zerogpu` | routes to the ZeroGPU Space |
| Kaggle / dev GPU | `local` | runs the shared pipeline on the notebook's GPU |

Kaggle never needs a separate provider name: `kaggle` is an accepted alias for
`local`.

## Optional: temporary integration endpoint (development only)

You can manually expose a dev-only endpoint (e.g. `ngrok tcp/http` in a
notebook cell) and point a **development** Render instance at it with
`INFERENCE_PROVIDER=kaggle` + the tunnel URL. This is for integration testing
only, never committed as production configuration, and no tunnel code lives in
the app.

## Do NOT

- Commit Kaggle credentials, HF tokens, or any audio datasets/recordings.
- Point Render/Vercel production at Kaggle.
- Report benchmark numbers as production numbers without the provider/checkpoint labels.
