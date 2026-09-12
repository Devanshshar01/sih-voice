# Deploying SatyaVoice on Render (Free Tier — no credit card)

The pragmatic no-cost path: Render free web service for the backend,
Neon free PostgreSQL, Render free Redis. Mock/demo detectors + browser
edge-mode inference keep it comfortably inside the 512 MB RAM limit.

> Free-tier trade-offs: the service **sleeps after ~15 min idle**
> (~50 s wake on the next request) and has limited RAM — real ML modes
> (`DETECTOR_MODE=real` / `ASR_MODE=real`) will OOM and are NOT supported
> on this tier. Use edge mode (browser ONNX) for real inference demos.

## 1. Create the data stores

1. **PostgreSQL** → [neon.tech](https://neon.tech) (free) → copy the
   connection string, append `?sslmode=require` if missing.
2. **Redis** → Render Dashboard → **New → Redis** (free instance, same
   region as your web service) → copy the **Internal Connection String**.

## 2. Create the Web Service

Render Dashboard → **New → Web Service** → connect the GitHub repo:

| Setting | Value |
|---|---|
| Branch | `audit/final-integration-gate` (or main after merge) |
| Runtime | **Docker** (uses the repo root `Dockerfile`) |
| Instance type | Free |
| Health check path | `/health/live` |

## 3. Environment variables

| Key | Value | Type |
|---|---|---|
| `VOICETRUST_ENV` | `production` | — |
| `VOICETRUST_CORS_ORIGINS` | `https://sih-voice.vercel.app` | — |
| `VOICETRUST_DATABASE_URL` | Neon URL (from step 1) | **Secret** |
| `VOICETRUST_REDIS_URL` | Render Redis internal URL | **Secret** |
| `VOICETRUST_SESSION_STORE_BACKEND` | `redis` | — |
| `VOICETRUST_AUTH_API_KEYS` | `sih-demo:sk_2e64bab372cb55ca8179f11dd79ae54d519c88901904418ffa1cb6b5594005a3` | **Secret** |
| `VOICETRUST_DETECTOR_MODE` | `mock` | — |
| `VOICETRUST_ASR_MODE` | `manual` | — |
| `VOICETRUST_MODEL_ID` | `Hemgg/Deepfake-audio-detection` | — |
| `VOICETRUST_ASR_MODEL_SIZE` | `small` | — |
| `VOICETRUST_ASR_DEVICE` | `cpu` | — |
| `VOICETRUST_ASR_COMPUTE_TYPE` | `int8` | — |
| `VOICETRUST_SPEAKER_VAULT_ENABLED` | `true` | — |
| `VOICETRUST_RATE_LIMIT_ENABLED` | `true` | — |

Do NOT set the `VOICETRUST_BLOCKCHAIN_*` vars (anchoring disabled).

## 4. Verify

```bash
curl https://<your-service>.onrender.com/health
# {"status":"ok","service":"SatyaVoice API","mode":"production"}

curl -X POST https://<your-service>.onrender.com/api/v1/call/start \
  -H "X-API-Key: sk_2e64bab372cb55ca8179f11dd79ae54d519c88901904418ffa1cb6b5594005a3" \
  -H "Content-Type: application/json" \
  -d '{"caller_id":"test","recipient_id":"desk"}'
```

## 5. Point Vercel at it

```
VITE_API_BASE_URL=https://<your-service>.onrender.com/api/v1
VITE_WS_BASE_URL=wss://<your-service>.onrender.com/api/v1
VITE_API_KEY=sk_2e64bab372cb55ca8179f11dd79ae54d519c88901904418ffa1cb6b5594005a3
```
Then redeploy Vercel and run the demo-cloned-voice flow end to end.

## 6. Demo-day checklist

- **Wake the service first**: `curl /health` (or open the URL) ~5–10 min
  before presenting — free instances sleep after 15 min idle
- Keep the dashboard open during the demo to prevent re-sleep
- Real-model latency claims are NOT possible on this tier — demo mock mode
  + edge mode (browser ONNX), and present `docs/safe-to-claim.md` honestly

## Comparison with the other deploy paths

| | Render free | Oracle VPS | HF Spaces (Docker) |
|---|---|---|---|
| Card | none | required | paid plan |
| RAM | 512 MB | 24 GB | 16 GB |
| Real models | ❌ OOM | ✅ | ✅ |
| Sleep | 15 min idle | never | 48 h idle (Pro) |
| Redis | free add-on | container | none (memory) |
