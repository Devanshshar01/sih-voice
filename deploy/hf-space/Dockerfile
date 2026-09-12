# SatyaVoice — Hugging Face Spaces (Docker) backend
#
# HF Spaces requirements honored here:
#   * app listens on 0.0.0.0:$PORT with port 7860 (declared in README app_port)
#   * everything runs as a non-root user (uid 1000)
#   * no volume mounts; writable dirs are /tmp and the app directory
#
# Copy this Dockerfile + README.md into a NEW HF Space repo (SDK: Docker)
# together with the backend source:
#   app/            (from the main repo)
#   requirements.txt
#   scripts/        (optional: verify_evidence CLI)
#
# The Space then builds automatically and serves at
# https://<user>-<space>.hf.space

FROM python:3.11-slim

WORKDIR /app

# System deps: libopus for optional Opus codec decoding.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# HF Spaces runs containers as uid 1000; the SQLite fallback path (if no
# Postgres URL is configured) must be writable. Production should always
# point VOICETRUST_DATABASE_URL at Postgres (Neon free tier).
RUN mkdir -p /app/data && chown -R 1000:1000 /app
USER 1000

# HF Spaces routes traffic to this port (must match README app_port).
ENV PORT=7860
EXPOSE 7860

# Liveness-style healthcheck on the app's own /health/live endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/health/live', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
