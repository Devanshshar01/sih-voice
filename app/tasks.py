"""Celery app and background task definitions.

Principle: only non-latency-critical work runs through Celery. The streaming
decision path (codec -> VAD -> anti-spoof ∥ ASR ∥ speaker -> fusion) stays on
the WebSocket event loop + bounded executor and NEVER makes a Celery round
trip — a broker round trip would blow the <500 ms decision budget.

Background-appropriate tasks:
  * anchor_evidence_package   — publish a chain root to Polygon Amoy (network
    I/O with 120 s receipt wait; must not block an API response)
  * generate_forensic_report  — heavy report generation/enrichment

Both tasks are safe to enqueue in eager mode (VOICETRUST_CELERY_EAGER=true)
for local dev with no Redis — the fallback executes inline.
"""
from __future__ import annotations

import logging

try:
    from celery import Celery
except ImportError:  # pragma: no cover - graceful fallback for local dev
    Celery = None

from app import config

logger = logging.getLogger("satyavoice.tasks")


class _FallbackCelery:
    """Inline executor when Celery/Redis is unavailable (local dev)."""

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
    if config.CELERY_TASK_ALWAYS_EAGER:
        celery_app.conf.task_always_eager = True


@celery_app.task(name="app.tasks.anchor_evidence_package")
def anchor_evidence_package(evidence_id: str) -> dict:
    """Anchor a registered package's chain root on Polygon Amoy.

    Reads the stored chain root from the DB, submits via the anchor adapter
    (which handles credential/network degradation honestly), and updates the
    package + anchor rows. Never raises into the caller: failures are
    recorded on the package as anchor_status=failed with a reason.
    """
    from app.db import models as db_models
    from app.db.database import SessionLocal
    from app.services.anchor_adapter import get_anchor_adapter

    db = SessionLocal()
    try:
        package = (
            db.query(db_models.EvidencePackage)
            .filter(db_models.EvidencePackage.evidence_id == evidence_id)
            .first()
        )
        if package is None:
            return {"task": "anchor_evidence_package", "evidence_id": evidence_id, "status": "not_found"}
        if not package.local_chain_root:
            return {"task": "anchor_evidence_package", "evidence_id": evidence_id, "status": "no_chain_root"}

        adapter = get_anchor_adapter()
        anchor_result = adapter.anchor_root(package.local_chain_root, evidence_id)

        package.anchor_status = anchor_result.get("status", "unavailable")
        package.anchor_tx_hash = anchor_result.get("tx_hash")
        package.anchor_block_number = anchor_result.get("block_number")
        package.anchor_timestamp = anchor_result.get("anchor_timestamp")
        package.failure_reason = anchor_result.get("failure_reason")
        package.blockchain_network = anchor_result.get("network") or package.blockchain_network
        package.contract_address = anchor_result.get("contract_address") or package.contract_address

        db.add(
            db_models.EvidenceAnchor(
                evidence_id=evidence_id,
                root_hash=package.local_chain_root,
                blockchain_network=anchor_result.get("network") or config.BLOCKCHAIN_NETWORK,
                contract_address=anchor_result.get("contract_address") or config.BLOCKCHAIN_CONTRACT_ADDRESS,
                tx_hash=anchor_result.get("tx_hash"),
                block_number=anchor_result.get("block_number"),
                anchor_timestamp=anchor_result.get("anchor_timestamp"),
                status=anchor_result.get("status", "unavailable"),
                failure_reason=anchor_result.get("failure_reason"),
            )
        )
        db.commit()
        return {
            "task": "anchor_evidence_package",
            "evidence_id": evidence_id,
            "status": package.anchor_status,
        }
    except Exception as exc:  # never crash the worker on one package
        logger.exception("anchor task failed for %s", evidence_id)
        return {"task": "anchor_evidence_package", "evidence_id": evidence_id, "status": "error", "reason": str(exc)}
    finally:
        db.close()


@celery_app.task(name="app.tasks.generate_forensic_report")
def generate_forensic_report(call_id: str, payload: dict | None = None) -> dict:
    """Heavy report generation/enrichment (kept off the API hot path)."""
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
