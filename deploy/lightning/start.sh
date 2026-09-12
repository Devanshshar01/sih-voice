#!/usr/bin/env bash
# SatyaVoice — Lightning AI Studio launcher.
#
# Run this INSIDE a Lightning Studio terminal:
#   cd ~/sih-voice && sh ./deploy/lightning/start.sh
#
# Notes:
#   * Lightning Studios expose ports publicly with automatic HTTPS via the
#     Studio's port-sharing feature (see docs/deploy-lightning.md) — uvicorn
#     itself only needs plain HTTP on 0.0.0.0.
#   * Studio filesystem is persistent, so the git checkout, the venv, and any
#     model caches survive restarts.
set -euo pipefail

cd "$(dirname "$0")/../.."

# --- venv (idempotent) ------------------------------------------------------
if [ ! -d .venv ]; then
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --no-cache-dir -r requirements.txt

# --- env file ---------------------------------------------------------------
# Fill in deploy/lightning/.env before first run (see env template
# deploy/lightning/env.template.txt in the repo).
if [ -f deploy/lightning/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source deploy/lightning/.env
    set +a
else
    echo "WARNING: deploy/lightning/.env not found — continuing with defaults." >&2
fi

# --- run ---------------------------------------------------------------------
# Single worker: the per-call stream lock and verification challenge store
# are process-local (documented in the integration audit).
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
