"""Forensics evidence registration and verification API.

SECURITY:
  - Error details from internal exceptions are sanitised before returning to
    clients (B7: no internal DB error messages or stack traces exposed).
  - The EvidenceAnchorService is exception-safe and returns explicit status
    dicts rather than raising; only ValueError propagates (evidence not found).
  - Payload size is validated in the service layer (MAX_EVIDENCE_PAYLOAD_BYTES).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.evidence_anchor import EvidenceAnchorService

logger = logging.getLogger("satyavoice.forensics")

router = APIRouter(prefix="/forensics", tags=["forensics"])


class EvidenceRegistrationRequest(BaseModel):
    evidence_id: str | None = None
    payload: dict[str, Any]


@router.post("/register")
def register_evidence(
    request: EvidenceRegistrationRequest,
    db: Session = Depends(get_db),
):
    """Register an evidence package in the local integrity ledger.

    Returns registration metadata including evidence hash and chain root.
    Duplicate payloads (same hash) are idempotent — the existing record is returned.

    The service layer never raises on DB failures; check status=='error' in the
    response body when integrating (HTTP 500 is reserved for truly unexpected errors).
    """
    service = EvidenceAnchorService(db)
    result = service.register_evidence_package(request.payload, request.evidence_id)

    if result.get("status") == "error":
        # Return the error message but sanitise it: only return the
        # user-safe message from the service layer, not any DB details.
        error_msg = result.get("error", "Evidence registration failed.")
        # If the message looks like a size/validation issue, it's safe to surface.
        # Otherwise use a generic message so no internal details leak (B7).
        safe_errors = {
            "A non-empty evidence payload is required.",
        }
        if error_msg in safe_errors or "maximum permitted size" in error_msg:
            raise HTTPException(status_code=400, detail=error_msg)
        raise HTTPException(
            status_code=500,
            detail="Evidence registration failed. Please contact the system administrator.",
        )

    return result


@router.post("/{evidence_id}/verify")
def verify_evidence(evidence_id: str, db: Session = Depends(get_db)):
    """Independently verify an evidence package's integrity.

    Returns a full verification report. All fields are server-derived;
    no client-supplied 'verified' claims are trusted.
    """
    try:
        service = EvidenceAnchorService(db)
        return service.verify_evidence_package(evidence_id)
    except ValueError:
        # Evidence not found: safe to surface the evidence_id in the message
        # since the caller already provided it.
        raise HTTPException(
            status_code=404,
            detail=f"Evidence package '{evidence_id}' was not found.",
        )
    except Exception:
        logger.exception("Unexpected error during evidence verification (evidence_id=%s)", evidence_id)
        raise HTTPException(
            status_code=500,
            detail="Evidence verification failed unexpectedly.",
        )
