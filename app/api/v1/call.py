"""
REST endpoints for call lifecycle: start a session, check the current risk
snapshot, and gate sensitive actions behind the live risk score.

SECURITY (B2 / B10):
  - GET /{call_id}/risk and POST /{call_id}/terminate require the requester to
    be the authenticated owner of the call session (IDOR/BOLA prevention via
    require_call_owner dependency from app.core.http_auth).
  - POST /action is intentionally more permissive in the current prototype
    (any caller can attempt an action; the risk gate is the primary control).
    In production, action gating should also require ownership verification.
  - POST /start does NOT require auth (creates a new session for the caller).
"""
from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app import config
from app.core.http_auth import require_call_owner
from app.core.session_manager import session_manager
from app.core.ws_auth import create_access_token
from app.db import models as db_models
from app.db.database import commit_with_retry, get_db
from app.models.schemas import (
    CallActionRequest,
    CallActionResponse,
    CallRiskResponse,
    CallStartRequest,
    CallStartResponse,
    RiskTimelinePoint,
)

router = APIRouter(prefix="/call", tags=["call"])

_logger = logging.getLogger("satyavoice.call")

# Action gating uses the central LOCK_VERIFY threshold from config — no magic
# numbers here (see RiskFusionConfig in app/config.py).
HIGH_RISK_THRESHOLD = config.RISK.LOCK_VERIFY_THRESHOLD


@router.post("/start", response_model=CallStartResponse)
def start_call(payload: CallStartRequest, db: DBSession = Depends(get_db)):
    session = session_manager.create_session(payload.caller_id, payload.recipient_id)

    def _stage_session_row() -> None:
        # Re-staged on retry: a rolled-back session has no pending inserts, and
        # building a fresh ORM object avoids reusing an expired instance.
        db.add(
            db_models.Session(
                call_id=session.call_id,
                caller_id=payload.caller_id,
                recipient_id=payload.recipient_id,
                status="ACTIVE",
            )
        )

    _stage_session_row()
    persisted = commit_with_retry(
        db,
        _stage_session_row,
        context=f"call_start_persist call_id={session.call_id}",
    )

    if not persisted:
        # The audit row is the FK parent for every per-window RiskEvent, so a
        # missed write is NOT reported as a successfully persisted session.
        if config.PERSISTENCE_REQUIRED:
            session_manager.end_session(session.call_id, status="FAILED")
            raise HTTPException(
                status_code=503,
                detail={
                    "status": "error",
                    "error_code": "SESSION_PERSISTENCE_UNAVAILABLE",
                    "error_message": (
                        "Call session could not be persisted; no monitored "
                        "session was created. Retry shortly."
                    ),
                },
            )
        # Explicit best-effort mode: proceed without durable persistence and
        # tell every downstream writer to stop attempting DB writes.
        session.persistence_degraded = True
        session_manager.sync_session(session)
        _logger.warning(
            "Call %s started WITHOUT durable persistence "
            "(VOICETRUST_DB_PERSISTENCE=best_effort); DB writes skipped",
            session.call_id,
        )

    return CallStartResponse(
        call_id=session.call_id,
        status="INITIATED_DEGRADED" if session.persistence_degraded else "INITIATED",
        ws_url=f"/api/v1/call/{session.call_id}/stream",
        token=create_access_token(payload.caller_id),
    )


@router.get("/{call_id}/risk", response_model=CallRiskResponse)
def get_risk(
    call_id: str,
    _subject: str = Depends(require_call_owner),
):
    """Return current risk snapshot for a call. Requires caller ownership."""
    session = session_manager.get(call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found or expired.")

    timeline = [
        RiskTimelinePoint(t=i, score=point["risk_score"])
        for i, point in enumerate(session.risk_timeline)
    ]
    return CallRiskResponse(
        call_id=call_id,
        current_risk_score=session.current_risk_score,
        timeline=timeline,
    )


@router.post("/action", response_model=CallActionResponse)
def execute_action(payload: CallActionRequest):
    session = session_manager.get(payload.call_id)
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found or expired.")

    if session.current_risk_score >= HIGH_RISK_THRESHOLD and not session.verified:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Action '{payload.action}' blocked: risk score "
                f"{session.current_risk_score}/100 requires out-of-band verification."
            ),
        )

    return CallActionResponse(executed=True, message=f"{payload.action} executed successfully.")


@router.post("/{call_id}/terminate")
def terminate_call(
    call_id: str,
    db: DBSession = Depends(get_db),
    _subject: str = Depends(require_call_owner),
):
    """Terminate a call. Requires caller ownership."""
    session = session_manager.end_session(call_id, status="COMPLETED")
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found.")

    def _apply_termination() -> None:
        # Re-applied on retry so the bounded retry has an UPDATE to commit.
        row = db.query(db_models.Session).filter_by(call_id=call_id).first()
        if row:
            row.status = session.status
            row.max_risk_score = session.current_risk_score
            row.end_time = row.end_time or datetime.now(timezone.utc)

    _apply_termination()
    persisted = commit_with_retry(
        db, _apply_termination, context=f"call_terminate_persist call_id={call_id}"
    )
    if not persisted:
        # The call IS terminated in memory (the authoritative session store); the
        # audit-trail write failed, and that is reported instead of hidden.
        _logger.error(
            "Termination of call_id=%s completed in memory but the audit row "
            "was not updated; persistence=degraded",
            call_id,
        )

    return {
        "call_id": call_id,
        "status": session.status,
        "persistence": "ok" if persisted else "degraded",
    }
