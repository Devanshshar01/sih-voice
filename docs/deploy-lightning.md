# Deploying SatyaVoice on Lightning AI (Studio, free tier)

A Lightning Studio is a persistent cloud VS Code environment (free tier:
1 always-on Studio, ~16 GB RAM, persistent disk) whose ports can be shared
publicly over HTTPS — effectively a small always-on VM without a credit
card. Good fit for the SatyaVoice backend in mock/manual mode, and lighter
real-model experiments (subject to monthly free credits — GPU time costs
credits, CPU Studio time is the free baseline).

> Trade-offs: free credits are limited; the free plan allows one Studio;
> port-sharing URL is `https://<random>.lightning.ai/<port>/` style — it
> terminates TLS for you (so `wss://` works), but the domain is
> auto-generated and cannot be customized.

## 1. Create the Studio

1. lightning.ai → sign up (GitHub login; no card for the free tier)
2. **New Studio** → CPU (any of the free CPU options) → start it
3. Open its terminal (VS Code integrated terminal works)

## 2. Clone and configure

```bash
git clone https://github.com/Devanshshar01/sih-voice.git
cd sih-voice
git checkout audit/final-integration-gate   # branch with the deploy files

cp deploy/lightning/env.template.txt deploy/lightning/.env
nano deploy/lightning/.env        # fill in real values
```

Env values (see `deploy/lightning/env.template.txt` for annotations):

```
VOICETRUST_ENV=production
VOICETRUST_CORS_ORIGINS=https://sih-voice.vercel.app
VOICETRUST_DATABASE_URL=<Neon free Postgres URL>?sslmode=require
VOICETRUST_AUTH_API_KEYS=sih-demo:sk_<your generated key>
VOICETRUST_SESSION_STORE_BACKEND=memory
VOICETRUST_DETECTOR_MODE=mock
VOICETRUST_ASR_MODE=manual
VOICETRUST_MODEL_ID=Hemgg/Deepfake-audio-detection   # NEVER wav2vec2-xls-r-300m (not a classifier)
VOICETRUST_ASR_MODEL_SIZE=small
```

## 3. Start the backend

```bash
sh ./deploy/lightning/start.sh
```

The script creates a persistent venv, installs requirements, loads
`deploy/lightning/.env`, and runs `uvicorn app.main:app` on `0.0.0.0:8000`
(single worker — the per-call stream lock is process-local).

## 4. Expose it publicly

Lightning terminates HTTPS on shared ports:

1. Studio UI → the **port sharing / network** panel (paperclip/"Port
   sharing" toggle next to the terminal, or the API-builder plugin per
   Lightning's docs — UI naming changes over time)
2. Share port **8000** → Lightning gives you a public HTTPS URL like
   `https://<something>.lightning.ai/8000/...` or a proxied subdomain
3. Verify from your laptop:

```bash
curl https://<the-public-url>/health
# {"status":"ok","service":"SatyaVoice API","mode":"production"}
```

WebSockets pass through the same URL with `wss://`.

## 5. Point Vercel at it

```
VITE_API_BASE_URL=https://<the-public-url>/api/v1
VITE_WS_BASE_URL=wss://<the-public-url>/api/v1
VITE_API_KEY=sk_<your generated key>
```
Redeploy Vercel, then test the demo-cloned-voice flow end to end.

> If Lightning's proxy prefixes the port in the path (`/8000/...`), include
> that prefix in `VITE_API_BASE_URL` accordingly (e.g.
> `https://x.lightning.ai/8000/api/v1`). Test `/health` in a browser first
> and mirror whatever path the working URL uses.

## 6. Keep-alive and caveats

- The Studio keeps running between sessions on the free tier; if you stop
  it, restart with `sh ./deploy/lightning/start.sh` (venv + repo persist).
- Watch monthly credits — the Studio consumes them while running if your
  plan meters CPU Studios; GPU Studios definitely do.
- One Studio per free account: don't need it for training at the same time.
- Demo safety net stays the same: mock mode + edge mode (browser ONNX).

## Compare with the other no-card options

| | Lightning Studio | Render free | Koyeb hobby |
|---|---|---|---|
| RAM | ~16 GB | 512 MB | 512 MB |
| Real models | possibly (credits permitting) | ❌ OOM | ❌ OOM |
| Sleep | Studio persists | 15 min idle | scales to zero |
| Public URL | auto HTTPS (fixed port-share URL) | `.onrender.com` | fixed domain |
| Setup effort | manual (this guide) | UI-driven | UI-driven |
