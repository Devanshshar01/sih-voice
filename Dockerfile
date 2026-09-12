# SatyaVoice backend
#
# Development/demo container (default): SQLite + mock detectors, no external
# dependencies. For production, set VOICETRUST_ENV=production and provide the
# required env vars (CORS origins, PostgreSQL URL, auth keys) — the app fails
# fast at boot if any are missing (see app/config.py).
FROM python:3.11-slim

WORKDIR /app

# System deps: libopus + libsndfile are optional codec runtime libs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libopus0 libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend source + scripts (verify_evidence CLI) — needed at runtime.
COPY app ./app
COPY scripts ./scripts

# SQLite data dir (dev/demo): pre-created and owned by the runtime user so
# the compose volume mount is writable (named volumes inherit this ownership
# on first use).
RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
