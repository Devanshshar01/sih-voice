"""
REST endpoints for call lifecycle: start a session, check the current risk
snapshot, and gate sensitive actions behind the live risk score.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.core.session_manager import session_manager
from app.db import models as db_models
from app.db.database import get_db
from app.models.schemas import (
    CallActionRequest,
    CallActionResponse,
    CallRiskResponse,
    CallStartRequest,
    CallStartResponse,
    RiskTimelinePoint,
)

router = APIRouter(prefix="/call", tags=["call"])

HIGH_RISK_THRESHOLD = 70


@router.post("/start", response_model=CallStartResponse)
def start_call(payload: CallStartRequest, db: DBSession = Depends(get_db)):
    session = session_manager.create_session(payload.caller_id, payload.recipient_id)

    db.add(
        db_models.Session(
            call_id=session.call_id,
            caller_id=payload.caller_id,
            recipient_id=payload.recipient_id,
            status="ACTIVE",
        )
    )
    db.commit()

    return CallStartResponse(
        call_id=session.call_id,
        status="INITIATED",
        ws_url=f"/api/v1/call/{session.call_id}/stream",
    )


@router.get("/{call_id}/risk", response_model=CallRiskResponse)
def get_risk(call_id: str):
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
def terminate_call(call_id: str, db: DBSession = Depends(get_db)):
    session = session_manager.end_session(call_id, status="COMPLETED")
    if not session:
        raise HTTPException(status_code=404, detail="Call session not found.")

    db_session = db.query(db_models.Session).filter_by(call_id=call_id).first()
    if db_session:
        db_session.status = session.status
        db_session.max_risk_score = session.current_risk_score
        db_session.end_time = db_session.end_time or datetime.now(timezone.utc)
        db.commit()

    return {"call_id": call_id, "status": session.status}
