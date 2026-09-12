---
title: SatyaVoice API
emoji: 🎙️
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# SatyaVoice backend (FastAPI + WebSocket)

FastAPI backend for SatyaVoice — real-time voice anti-spoofing, risk fusion,
and forensic evidence anchoring. Deployed as a Docker Space.

## Health
- `GET /health` — liveness
- `GET /health/ready` — readiness (DB, models, session store)

## Env vars (Space Settings → Variables and secrets)
See `docs/deploy-hf-spaces.md` in the main repository for the full,
annotated list.
