# Deploying SatyaVoice on RunPod

RunPod pods are Docker containers with **public HTTPS proxy URLs per port**
(`https://<pod-id>-<port>.proxy.runpod.net`) and automatic TLS — the proxy
passes WebSocket upgrades, so `wss://` works out of the box.

> ⚠️ Honest cost note: RunPod is **pay-as-you-go** (card or crypto; small
> promo credits at signup). There is no permanently free tier — a CPU pod
> costs a few cents/hour (~$5–10/month if left running 24/7). Cheaper
> no-card options are in `docs/deploy-render-free.md`. The advantage here:
> no sleep, configurable RAM (up to GBs), GPU optional, and public proxy
> URLs with zero TLS setup.

## 1. Build and push the image

The repo-root `Dockerfile` works as-is (listens on 0.0.0.0:8000):

```bash
git clone https://github.com/Devanshshar01/sih-voice.git
cd sih-voice
git checkout audit/final-integration-gate

docker build -t <dockerhub-user>/satyavoice-api:latest .
docker push <dockerhub-user>/satyavoice-api:latest
```

(Or build it inside a RunPod pod with Docker-in-Docker / `nerdctl` if you
prefer not to push a public image — see step 3's alternative.)

## 2. Create the pod template

RunPod console → **Pods → New Pod → Edit Template**:

| Setting | Value |
|---|---|
| Container image | `<dockerhub-user>/satyavoice-api:latest` |
| Instance type | **CPU** (e.g. 4 vCPU / 16 GB) — GPU not needed for mock mode |
| HTTP service port | `8000` (type **HTTP proxy**) |
| Volume / container disk | ≥ 10 GB (20 GB if you plan real models) |
| Environment variables | from `deploy/runpod/env.template.txt` (below) |

Env vars (same values as other deploy paths):

```
VOICETRUST_ENV=production
VOICETRUST_CORS_ORIGINS=https://sih-voice.vercel.app
VOICETRUST_DATABASE_URL=<Neon URL>?sslmode=require
VOICETRUST_AUTH_API_KEYS=sih-demo:sk_<your generated key>
VOICETRUST_SESSION_STORE_BACKEND=memory
VOICETRUST_DETECTOR_MODE=mock
VOICETRUST_ASR_MODE=manual
VOICETRUST_MODEL_ID=Hemgg/Deepfake-audio-detection
VOICETRUST_ASR_MODEL_SIZE=small
VOICETRUST_ASR_DEVICE=cpu
VOICETRUST_ASR_COMPUTE_TYPE=int8
VOICETRUST_SPEAKER_VAULT_ENABLED=true
```

(Mark `VOICETRUST_DATABASE_URL` and `VOICETRUST_AUTH_API_KEYS` as secret
values in the template. No Redis, no BLOCKCHAIN_* vars.)

## 3. Deploy and get the public URL

1. **Deploy Pod** (on-demand pricing)
2. When running, click the **Connect** / port widget → the HTTP proxy for
   port 8000 → copy the URL: `https://<pod-id>-8000.proxy.runpod.net`
3. Verify:

```bash
curl https://<pod-id>-8000.proxy.runpod.net/health
# {"status":"ok","service":"SatyaVoice API","mode":"production"}

curl -X POST https://<pod-id>-8000.proxy.runpod.net/api/v1/call/start \
  -H "X-API-Key: sk_<your generated key>" \
  -H "Content-Type: application/json" \
  -d '{"caller_id":"t","recipient_id":"d"}'
```

WebSockets: same host with `wss://` (RunPod's proxy forwards the upgrade).

### Alternative: build inside the pod

Deploy a plain `runpod/base` template pod with Docker support, then:

```bash
git clone https://github.com/Devanshshar01/sih-voice.git /workspace/sih-voice
cd /workspace/sih-voice
docker build -t satyavoice-local .
docker run -d -p 8000:8000 --env-file deploy/runpod/.env satyavoice-local
```

## 4. Point Vercel at it

```
VITE_API_BASE_URL=https://<pod-id>-8000.proxy.runpod.net/api/v1
VITE_WS_BASE_URL=wss://<pod-id>-8000.proxy.runpod.net/api/v1
VITE_API_KEY=sk_<your generated key>
```
Redeploy, then run the demo-cloned-voice flow end to end.

## 5. Caveats

- **Pod restarts wipe container disk unless you attach a volume.** Attach a
  network volume at `/workspace` if you enable real modes (model weights are
  ~400 MB and re-downloading every restart is slow).
- **Pod ID changes cost you the URL.** The proxy hostname is tied to the
  pod; if you destroy/recreate it, update the Vercel env vars. For a stable
  demo, keep the pod stopped-but-not-terminated (stopped pods preserve the
  ID with attached storage; stop still bills disk only).
- Real models: choose an instance with ≥ 16 GB RAM; `ASR_DEVICE=cpu`
  `int8` keeps it cheap. Measure with `scripts/benchmark_latency.py` before
  claiming latency numbers.

## Comparison with the other paths

| | RunPod pod | Render free | Lightning Studio | Oracle VPS |
|---|---|---|---|---|
| Cost | cents/hour, no sleep | free, sleeps | credits | free forever |
| Card | yes | no | no | yes |
| RAM | you choose | 512 MB | ~16 GB | 24 GB |
| Stable URL | per-pod proxy URL | yes | port-share URL | your domain |
| TLS | automatic proxy | automatic | automatic | Caddy |
