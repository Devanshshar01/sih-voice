FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY app ./app

# Alembic configuration and migrations
COPY alembic.ini .
COPY alembic ./alembic
COPY scripts ./scripts

EXPOSE 8000

# Baseline-stamp a pre-existing (create_all-built) database ONCE and only when
# needed (see scripts/alembic_bootstrap.py), then apply pending migrations.
# Unconditional stamping here would crash-loop on the second boot.
CMD ["sh", "-c", "python scripts/alembic_bootstrap.py && python -m alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]