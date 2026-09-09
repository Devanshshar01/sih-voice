"""Forensics evidence registration and verification API."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.evidence_anchor import EvidenceAnchorService

router = APIRouter(prefix="/forensics", tags=["forensics"])


class EvidenceRegistrationRequest(BaseModel):
    evidence_id: str | None = None
    payload: dict[str, Any]


@router.post("/register")
def register_evidence(
    payload: EvidenceRegistrationRequest,
    db: Session = Depends(get_db),
):
    try:
        service = EvidenceAnchorService(db)
        return service.register_evidence_package(payload.payload, payload.evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{evidence_id}/verify")
def verify_evidence(evidence_id: str, db: Session = Depends(get_db)):
    try:
        service = EvidenceAnchorService(db)
        return service.verify_evidence_package(evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
