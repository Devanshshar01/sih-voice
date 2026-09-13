# SatyaVoice — Kaggle Development Architecture

## PRODUCTION (unchanged — do not break)

```
Vercel (sih-voice.vercel.app)
   ↓  HTTPS, VITE_API_BASE
Render FastAPI (satyavoice-api.onrender.com)
   ↓  risk engine + session/risk state
Hugging Face ZeroGPU Space (satyavoice-gpu)
   ↓  hf_zero_gpu/inference.py  (@spaces.GPU infer())
XLS-R anti-spoof + ECAPA-TDNN speaker
   ↓
Render risk engine → Vercel UI
```

Default Render configuration is `INFERENCE_PROVIDER=detector` (in-process
Render pipeline), which is the behaviour that existed before this integration.
`zerogpu` routes window inference to the Space; both are production providers.
**Kaggle is not part of this path in any way.**

## DEVELOPMENT / BENCHMARKING

```
Kaggle GPU notebook
   ↓  imports app/services/local_provider.py
   ↓  which imports the SAME hf_zero_gpu/inference.py pipeline
shared pipeline (mono → real resample 16 kHz → 4 s window → XLS-R → ECAPA)
   ↓
kaggle/benchmark.py · kaggle/consistency.py · kaggle/reports/
```

Key property: there is exactly ONE ML implementation in the repository
(`hf_zero_gpu/inference.py`). The HF Space runs it behind `@spaces.GPU`;
Kaggle runs it in-process via `LocalInferenceProvider`; no code is copied.

## OPTIONAL integration-testing mode (explicitly configured, never default)

```
Render (development instance)
   ↓  INFERENCE_PROVIDER=kaggle   (alias of "local")
LocalInferenceProvider → in-process CUDA
```

A developer may additionally run an inference API inside a Kaggle notebook and
manually expose it (ngrok/Cloudflare Tunnel) **only** to point a dev Render
instance at it for integration tests. No tunnel code ships in the app; this is
never production configuration.

## Why Kaggle is NOT production

1. Kaggle sessions are ephemeral, rate-limited and cannot receive traffic from
   the public internet reliably — they cannot back a live demo.
2. Kaggle must never handle real user audio (privacy / consent).
3. ZeroGPU quota preservation: repeated stress tests, benchmarks and
   evaluations run on Kaggle instead of the Space.
4. Provider abstraction keeps the risk engine provider-agnostic
   (`InferenceProvider` interface): it cannot tell — and does not care — whether
   a result came from ZeroGPU, Kaggle, or a future cloud GPU.

## Guarantees & invariants

- `InferenceResult.failure()` **never** fabricates a `spoof_probability`
  (no fake 0.5); errors carry `success=False` + `error_code`
  (`INFERENCE_UNAVAILABLE`, `INVALID_AUDIO_INPUT`).
- The 4 s / 16 kHz / mono audio contract and real resampling are shared by all
  providers.
- Benchmark outputs always print the loaded checkpoint; the base
  `facebook/wav2vec2-xls-r-300m` is labelled **BASE XLS-R — NOT FINAL
  SATYAVOICE ANTI-SPOOF MODEL**.
- Latency is reported as measured p50/p95/p99 with CUDA synchronisation and
  warm-up excluded; model critical path ≠ end-to-end verdict latency (SIH's
  <500 ms target refers to the latter).
