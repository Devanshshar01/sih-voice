# SatyaVoice Production Audit

**Audit date:** 2026-09-17  
**Repository:** `Devanshshar01/sih-voice`  
**Production path:** Vercel → Render FastAPI → Hugging Face ZeroGPU (`devanshshar01/satyavoice-gpu`) → MMS-300M AntiDeepfake → Render → Vercel

## Executive summary

The repository contains the remote-HF score handling fix and the final local hardening changes. The Render audio endpoint no longer classifies a missing detector score as `HUMAN`; it returns an explicit degraded `503` response. Valid HF responses use the MMS `fake_probability` as the canonical spoof/acoustic score and preserve the exact model identifier:

`nii-yamagishilab/mms-300m-anti-deepfake`

The repository is ready for deployment and a live three-layer smoke test after Render redeploys the pushed commit. A live end-to-end success must not be claimed until that request has actually passed through Render and the HF Space.

## Verified implementation

### Backend

- `app/api/v1/analyze.py`
  - Accepts WAV audio and preserves the existing raw float32 compatibility path.
  - Rejects empty, malformed, non-finite, oversized, and over-duration input.
  - Validates spoof/fake/real scores as finite values in `[0, 1]` summing to approximately `1`.
  - Returns HTTP `503` with an explicit unavailable error when inference fails or produces no valid score.
  - Uses `SPOOF_THRESHOLD` only for classification; raw probabilities are unchanged.
- `app/services/zerogpu_provider.py`
  - Extracts `fake_probability` from the live HF response, with legacy `spoof_probability` compatibility.
  - Validates `real_probability`, probability consistency, and the exact MMS model ID.
  - Preserves `None` on failures; it never fabricates a score.
- `app/config.py`
  - Default model ID is locked to MMS.
  - `SPOOF_THRESHOLD` defaults to `0.50` and is range-validated.
  - Upload and duration limits are configurable.
  - Production detector configuration requires a ZeroGPU endpoint.
- `app/main.py`
  - Provides `/health` and `/ready` checks.
  - Supports exact production CORS configuration through `VOICETRUST_CORS_ORIGINS`.

### Frontend

- `src/lib/api.ts` uses `VITE_API_BASE_URL`; WebSocket URL is derived from it unless explicitly configured.
- Requests have a 30-second abort timeout and convert network failures into actionable errors.
- Vercel must define the production API URL; the localhost fallback is for local development only.

### Evidence and forensics

The existing Merkle evidence and PDF workflow remains intact:

- `POST /api/v1/forensics/merkle/register`
- `POST /api/v1/forensics/merkle/{evidence_id}/verify`
- `GET /api/v1/forensics/merkle/{evidence_id}/report.pdf`

Evidence uses server-derived hashes and verification. Blockchain anchoring remains optional and reports unavailable/operator action when no blockchain configuration is present. No blockchain or forensic architecture was changed in this pass.

## Probability and model contract

For successful inference, the expected response fields are:

```json
{
  "status": "ok",
  "spoof_probability": 0.7482935,
  "fake_probability": 0.7482935,
  "real_probability": 0.2517065,
  "model_version_antispoof": "nii-yamagishilab/mms-300m-anti-deepfake",
  "inference_time_ms": 1234.5,
  "sample_rate": 16000,
  "duration_ms": 4000.0
}
```

The mapping is `fake_probability == spoof_probability`; `real_probability == 1 - fake_probability` when the remote response supplies only the legacy spoof field. Missing, non-finite, out-of-range, inconsistent, or wrong-model responses are rejected as unavailable.

## Tests and validation

Added/retained coverage includes:

- Missing-score regression: no `None >= 0.5` crash and no false `HUMAN` classification.
- Valid MMS response mapping with fake `0.7482935` and real `0.2517065`.
- Provider structured failures and transport failures.
- MMS model identity regression checks.
- Detector safety and degraded response checks.

Run locally with the repository's supported Python environment:

```powershell
python -m pytest -q
```

Validation on 2026-09-17: targeted regression/provider tests passed (`23 passed`). The full suite completed with `333 passed, 23 failed`. The failures are outside the changed batch-analysis/provider contract and include blockchain test state/adapter behavior, an authentication-dependent smoke test, Python 3.14 binary compatibility for `web3`, and older MMS test doubles. These must be resolved before declaring the complete repository suite green.

## Required deployment variables

### Render

```text
ENVIRONMENT=production
VOICETRUST_DETECTOR_MODE=remote_hf
HF_ZERO_GPU_SPACE=https://huggingface.co/spaces/devanshshar01/satyavoice-gpu
VOICETRUST_CORS_ORIGINS=https://satyavoice.vercel.app
SPOOF_THRESHOLD=0.50
```

Use the repository's `.env.example` for the remaining required secrets. Do not put raw audio, embeddings, tokens, or private keys in logs.

### Vercel

```text
VITE_API_BASE_URL=https://<production-render-host>/api/v1
```

Set `VITE_WS_BASE_URL` only if the WebSocket host differs from the API host. Do not use localhost in the production project.

### Hugging Face Space

```text
ANTISPOOF_MODEL_ID=nii-yamagishilab/mms-300m-anti-deepfake
```

After changing the variable, perform a Factory reboot and verify the API response model field. A stale `facebook/wav2vec2-xls-r-300m` value means migration is incomplete.

## Live smoke-test procedure

Replace the placeholders with the actual Render URL and an audio file of 1–4 seconds.

### 1. Direct HF test

```powershell
python -c "from gradio_client import Client, handle_file; import json; r=Client('devanshshar01/satyavoice-gpu').predict(audio=handle_file(r'C:\path\sample.wav'), api_name='/infer'); print(json.dumps(r, indent=2))"
```

Verify `status: "ok"`, finite probabilities summing to approximately `1`, `sample_rate: 16000`, and the exact MMS model ID.

### 2. Render Swagger/cURL test

```powershell
curl.exe -X POST "https://<production-render-host>/api/v1/audio/analyze" -F "audio_file=@C:\path\sample.wav" -F "language=en-IN"
```

Verify HTTP `200`, `classification`, valid confidence, and the normalized probability/model fields in the response.

### 3. Vercel browser test

Open the production Vercel URL, upload the same sample, and inspect DevTools → Network. Verify the request targets the Render production URL, shows a loading state, returns HTTP `200`, and displays the MMS model ID and fake/real percentages. On HTTP `503` or timeout, the UI must show detection unavailable and must not display a stale prior result.

## Remaining blockers

1. Render must redeploy the pushed commit `69f5f06` plus this audit commit.
2. The live Render → HF request must be executed after deployment; repository tests cannot prove production connectivity.
3. Vercel and Render deployment variables must be checked in their respective dashboards.
4. Full `pytest -q` is not green yet: `333 passed, 23 failed`; resolve the listed environment/baseline failures in a supported CI environment.

## Final status

**READY FOR LIVE THREE-LAYER TEST** — code and deployment instructions are prepared; live production success remains subject to the post-deploy smoke test above.