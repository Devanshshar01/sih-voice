"""Celery app and non-interactive background task definitions.

The goal is to keep long-running, non-critical work (forensic analysis,
PDF/report generation, side-channel enrichment) off the WebSocket hot path.
"""
from __future__ import annotations

try:
    from celery import Celery
except ImportError:  # pragma: no cover - graceful fallback for local dev
    Celery = None

from app import config


class _FallbackCelery:
    def task(self, *args, **kwargs):
        def decorator(func):
            def _delay(*task_args, **task_kwargs):
                return func(*task_args, **task_kwargs)

            func.delay = _delay
            return func

        if args and callable(args[0]):
            return decorator(args[0])
        return decorator


if Celery is None:
    celery_app = _FallbackCelery()
else:
    celery_app = Celery(
        "satyavoice",
        broker=config.CELERY_BROKER_URL,
        backend=config.CELERY_RESULT_BACKEND,
    )


@celery_app.task(name="app.tasks.generate_forensic_report")
def generate_forensic_report(call_id: str, payload: dict | None = None) -> dict:
    """Placeholder for a non-interactive report-generation task.

    The task intentionally returns structured metadata rather than trying to
    generate a PDF in-process so the endpoint can stay lightweight and the
    work can be moved onto a background worker later.
    """
    report_payload = payload or {}
    return {
        "task": "generate_forensic_report",
        "call_id": call_id,
        "status": "completed",
        "report": {
            "summary": report_payload.get("summary", "Forensic analysis queued."),
            "generated_at": report_payload.get("generated_at"),
        },
    }
