# Deploying SatyaVoice on Oracle Cloud Always Free

Target: the backend (`app/`) on a free Oracle Ampere A1 VM with Docker,
Caddy for automatic HTTPS/WSS, Redis in compose, PostgreSQL on Neon's free
tier. The Vercel frontend stays where it is.

## 0. Prerequisites

- Oracle Cloud account (Always Free — no student verification; card is for
  identity only, never charged on Always Free resources)
- A domain (or a free `duckdns.org` subdomain)
- Vercel frontend URL (e.g. `https://sih-voice.vercel.app`)

If your region shows "out of capacity" for Ampere A1: retry periodically or
switch region (Mumbai/Hyderabad usually have ARM capacity).

## 1. Create the VM

Console → Compute → Create Instance:

- Image: **Ubuntu 22.04** (aarch64)
- Shape: **Ampere A1** — 4 OCPU / 24 GB (Always Free)
- Boot volume: 100 GB (models + whisper weights need room; default 47 GB also works if you skip real ASR)
- Add your SSH key

## 2. Open the firewall (BOTH layers)

**a) Oracle VCN security list:** Instance → Subnet → Security List →
Add Ingress Rule: source `0.0.0.0/0`, TCP ports `80` and `443`.

**b) OS firewall (Ubuntu):**
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 3. DNS

Create an A record: `api.yourdomain.com` → the VM's **public** IP.
(DuckDNS: create `api-yourname.duckdns.org` → your IP.)

DNS must resolve BEFORE the first Caddy start or certificate issuance fails
(it retries automatically, so a late fix is fine).

## 4. Install Docker + start the stack

```bash
ssh ubuntu@<VM_PUBLIC_IP>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && newgrp docker

git clone https://github.com/Devanshshar01/sih-voice.git
cd sih-voice

cp deploy/env.oracle.template.txt deploy/.env
nano deploy/.env          # fill in real values (see template comments)

docker compose -f deploy/docker-compose.oracle.yml --env-file deploy/.env up -d --build
```

Caddy obtains the TLS certificate automatically. Verify:

```bash
curl https://api.yourdomain.com/health            # {"status":"ok","mode":"production"}
curl https://api.yourdomain.com/health/ready      # all checks "ready"
```

## 5. Point the frontend at it

Vercel env vars (then redeploy):

```
VITE_API_BASE_URL=https://api.yourdomain.com/api/v1
VITE_WS_BASE_URL=wss://api.yourdomain.com/api/v1
VITE_API_KEY=sk_your_generated_key
```

Backend `VOICETRUST_CORS_ORIGINS` must exactly match the Vercel origin.

## 6. First deploy vs full stack

| Stage | DETECTOR_MODE | ASR_MODE | Notes |
|---|---|---|---|
| Smoke deploy | `mock` | `manual` | boots in seconds, deterministic demo |
| Full stack | `real` | `real` | ~400 MB model download on first inference; 24 GB RAM handles it |

Switch by editing `deploy/.env` and re-running the `docker compose up -d`
command (it recreates only changed services).

**Model ID warning:** `facebook/wav2vec2-xls-r-300m` is a feature-extractor
base model, NOT an audio classifier — the detector will fail to load it.
Use `Hemgg/Deepfake-audio-detection` (or your own fine-tuned classifier
checkpoint). The XLS-R fine-tune is the target *architecture*, not a
drop-in checkpoint.

## 7. Operations

```bash
docker compose -f deploy/docker-compose.oracle.yml logs -f api   # live logs
docker compose -f deploy/docker-compose.oracle.yml restart api   # after .env edits
docker compose -f deploy/docker-compose.oracle.yml pull && \
docker compose -f deploy/docker-compose.oracle.yml up -d --build # update from git
```

Keep-it-warm: Oracle does NOT sleep Always Free VMs — this is the main
advantage over Render/HF Spaces. (Idle-reclamation applies to very
under-utilized instances; a light periodic ping of `/health` from a cron
job elsewhere is cheap insurance.)

## 8. Known deployment facts (from the integration audit)

- Run the API container as a SINGLE uvicorn worker (default Dockerfile CMD):
  the per-call stream lock and verification challenge store are
  process-local; scale vertically (bigger shape) before horizontally.
- WebSocket auth uses `?token=<key>` (browsers cannot set WS headers) —
  already handled by the frontend's `buildStreamUrl`.
- Celery is optional; evidence anchoring and PDF generation run inline via
  the eager fallback. Add a worker container only if you enable live
  Polygon anchoring.
