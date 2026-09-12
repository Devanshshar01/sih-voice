# Deploying SatyaVoice on Hugging Face Spaces (Docker)

> ⚠️ **STATUS (2026): HF Docker Spaces now require a PAID plan.** Free
> accounts only get Gradio/Static SDKs, which cannot properly host a raw
> FastAPI + WebSocket backend. Prefer the Oracle VPS path
> (`docs/deploy-oracle-vps.md`) if a card is available, or Render free
> (no card, mock mode + edge mode) otherwise. This guide is retained for
> Pro users.

Free, no credit card, 16 GB RAM / 2 vCPU. WebSockets supported.
Trade-offs: sleeps after ~48 h idle (~1–2 min wake), HTTP only via HF's
TLS (fine — `wss://` works through their proxy), no Redis (session store
runs in memory — single-replica is fine for the demo).

## 1. Create the Space

1. huggingface.co → **New Space**
2. Space name: `satyavoice-api` · SDK: **Docker** · License: your choice
3. HF creates a git repo: `https://huggingface.co/spaces/<user>/satyavoice-api`

## 2. Push the Space contents

Clone the Space repo and copy in exactly these files:

```
Dockerfile            <- deploy/hf-space/Dockerfile (from this repo)
README.md             <- deploy/hf-space/README.md   (from this repo)
app/                  <- the backend source tree from this repo
requirements.txt      <- from this repo root
scripts/              <- optional (verify_evidence CLI)
```

```bash
git clone https://huggingface.co/spaces/<user>/satyavoice-api
cd satyavoice-api
cp ../sih-voice/deploy/hf-space/Dockerfile .
cp ../sih-voice/deploy/hf-space/README.md .
cp -r ../sih-voice/app .
cp ../sih-voice/requirements.txt .
cp -r ../sih-voice/scripts .
git add . && git commit -m "SatyaVoice backend" && git push
```

The Space builds automatically (first build ~5–10 min: torch + transformers
are large). Watch the **Logs** tab.

## 3. Set environment variables

Space → **Settings → Variables and secrets**. Secrets for sensitive values,
plain Variables for the rest.

### Required

| Key | Value | Type |
|---|---|---|
| `VOICETRUST_ENV` | `production` | Variable |
| `VOICETRUST_CORS_ORIGINS` | `https://sih-voice.vercel.app` | Variable |
| `VOICETRUST_DATABASE_URL` | `postgresql://<user>:<pass>@ep-xxx.aws.neon.tech/neondb?sslmode=require` (Neon free tier) | **Secret** |
| `VOICETRUST_AUTH_API_KEYS` | `sih-demo:sk_2e64bab372cb55ca8179f11dd79ae54d519c88901904418ffa1cb6b5594005a3` | **Secret** |

### AI modes (start conservative)

| Key | Value | Type |
|---|---|---|
| `VOICETRUST_DETECTOR_MODE` | `mock` (flip to `real` after first successful boot) | Variable |
| `VOICETRUST_ASR_MODE` | `manual` (flip to `real` later) | Variable |
| `VOICETRUST_MODEL_ID` | `Hemgg/Deepfake-audio-detection` — **NOT** `facebook/wav2vec2-xls-r-300m` (base model, not a classifier; real mode would crash) | Variable |
| `VOICETRUST_ASR_MODEL_SIZE` | `small` | Variable |
| `VOICETRUST_ASR_DEVICE` | `cpu` | Variable |
| `VOICETRUST_ASR_COMPUTE_TYPE` | `int8` | Variable |

### Session store (no Redis on HF)

| Key | Value | Type |
|---|---|---|
| `VOICETRUST_SESSION_STORE_BACKEND` | `memory` | Variable |

(Memory store is single-process — fine for the SIH demo. Multi-worker
scaling is not available on free Spaces anyway.)

### Optional

| Key | Value | Type |
|---|---|---|
| `VOICETRUST_SPEAKER_VAULT_ENABLED` | `true` (uses the labeled deterministic fallback when SpeechBrain is unavailable) | Variable |
| `VOICETRUST_LOG_LEVEL` | `INFO` | Variable |
| `VOICETRUST_RATE_LIMIT_ENABLED` | `true` | Variable |

### NOT needed here (remove from your Render-style list)

- `VOICETRUST_REDIS_URL` — no Redis on HF Spaces
- `VOICETRUST_BLOCKCHAIN_*` (4 vars) — anchoring disabled; re-add only with a funded Amoy key

## 4. Verify

```bash
curl https://<user>-satyavoice-api.hf.space/health
# {"status":"ok","service":"SatyaVoice API","mode":"production"}

curl https://<user>-satyavoice-api.hf.space/health/ready

curl -X POST https://<user>-satyavoice-api.hf.space/api/v1/call/start \
  -H "X-API-Key: sk_2e64bab372cb55ca8179f11dd79ae54d519c88901904418ffa1cb6b5594005a3" \
  -H "Content-Type: application/json" \
  -d '{"caller_id":"test","recipient_id":"desk"}'
```

## 5. Point Vercel at it

Vercel env vars (then redeploy):

```
VITE_API_BASE_URL=https://<user>-satyavoice-api.hf.space/api/v1
VITE_WS_BASE_URL=wss://<user>-satyavoice-api.hf.space/api/v1
VITE_API_KEY=sk_2e64bab372cb55ca8179f11dd79ae54d519c88901904418ffa1cb6b5594005a3
```

## 6. Demo-day checklist

- **Warm it up**: open the Space URL (or `curl /health`) 10 minutes before
  presenting — a sleeping Space takes 1–2 minutes to wake
- Keep the Space page open in a tab during the demo to prevent sleep
- Free Spaces have no uptime SLA; the Render-deployed fallback is a good
  backup link
- Real ASR on 2 vCPU: measure with `scripts/benchmark_latency.py` before
  claiming any latency numbers

## Differences vs the Oracle VPS deployment

| | HF Spaces | Oracle VPS (`deploy/docker-compose.oracle.yml`) |
|---|---|---|
| RAM | 16 GB | 24 GB |
| Sleep | after ~48 h idle | never |
| TLS | automatic (HF domain) | Caddy + your domain |
| Redis | none (memory store) | redis container |
| Card | none | required |
| Custom domain | paid tier only | free (your domain) |
