"""Forensics evidence registration and verification API.

SECURITY:
  - Error details from internal exceptions are sanitised before returning to
    clients (B7: no internal DB error messages or stack traces exposed).
  - The EvidenceAnchorService is exception-safe and returns explicit status
    dicts rather than raising; only ValueError propagates (evidence not found).
  - Payload size is validated in the service layer (MAX_EVIDENCE_PAYLOAD_BYTES).
"""
from __future__ import annotations

import base64
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.evidence_anchor import EvidenceAnchorService
from app.services.merkle_evidence import MerkleEvidenceError, MerkleEvidenceService

logger = logging.getLogger("satyavoice.forensics")

router = APIRouter(prefix="/forensics", tags=["forensics"])

# Evidence ids are opaque, server-generated-ish tokens. They are used in URLs
# (QR targets) and stored keys, so constrain them to a safe charset.
_EVIDENCE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _validate_evidence_id(evidence_id: str) -> str:
    if not _EVIDENCE_ID_RE.match(evidence_id or ""):
        raise HTTPException(
            status_code=400,
            detail="Invalid evidence_id: use 1-128 characters from [A-Za-z0-9._:-].",
        )
    return evidence_id


class EvidenceRegistrationRequest(BaseModel):
    evidence_id: str | None = None
    payload: dict[str, Any]


class MerkleEvidenceItem(BaseModel):
    """One evidence item. Data is base64 (bytes) or plain text (UTF-8)."""

    name: str
    data_base64: str | None = None
    text: str | None = None


class MerkleEvidenceRegistrationRequest(BaseModel):
    evidence_id: str | None = None
    session_id: str | None = None
    items: list[MerkleEvidenceItem]
    model_metadata: dict[str, Any] | None = None
    anchor: bool = True


class MerkleVerifyRequest(BaseModel):
    """Optional raw items to re-derive. Data is base64 (bytes) or text."""

    items: list[MerkleEvidenceItem] | None = None
    verify_on_chain: bool = True


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


# ===========================================================================
# Phase 10 — Merkle-root evidence endpoints
# ===========================================================================

def _items_to_bytes(items: list[MerkleEvidenceItem]) -> dict[str, bytes]:
    """Convert a request's item list into a {name: bytes} mapping for the service."""
    result: dict[str, bytes] = {}
    for item in items:
        if item.data_base64 is not None:
            try:
                result[item.name] = base64.b64decode(item.data_base64, validate=True)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item '{item.name}': data_base64 is not valid base64.",
                )
        elif item.text is not None:
            result[item.name] = item.text.encode("utf-8")
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Item '{item.name}': provide either data_base64 or text.",
            )
    return result


@router.post("/merkle/register")
def register_merkle_evidence(
    request: MerkleEvidenceRegistrationRequest,
    db: Session = Depends(get_db),
):
    """Register a Merkle-root evidence package and (optionally) anchor its root.

    Each item is hashed individually (SHA-256) and combined into a Merkle tree
    (RFC 8785 canonical manifest). Only the root + a hashed evidence id go
    on-chain; raw items never leave the local ledger.
    """
    if request.evidence_id is not None:
        _validate_evidence_id(request.evidence_id)
    if not request.items:
        raise HTTPException(status_code=400, detail="At least one evidence item is required.")

    items = _items_to_bytes(request.items)
    service = MerkleEvidenceService(db)
    result = service.register_merkle_package(
        items=items,
        evidence_id=request.evidence_id,
        session_id=request.session_id,
        model_metadata=request.model_metadata,
        anchor=request.anchor,
    )
    if result.get("status") == "error":
        # Validation errors are safe to surface; anything else uses a generic 500.
        detail = result.get("error", "Merkle evidence registration failed.")
        if "required" in detail or "must be" in detail or "must not" in detail:
            raise HTTPException(status_code=400, detail=detail)
        raise HTTPException(status_code=500, detail="Merkle evidence registration failed.")
    return result


@router.post("/merkle/{evidence_id}/verify")
def verify_merkle_evidence(
    evidence_id: str,
    request: MerkleVerifyRequest | None = None,
    db: Session = Depends(get_db),
):
    """Verify a Merkle package: recompute the root and (optionally) the on-chain
    commitment. All results are server-derived; client 'verified' claims are ignored.
    """
    _validate_evidence_id(evidence_id)
    service = MerkleEvidenceService(db)
    provided = _items_to_bytes(request.items) if (request and request.items) else None
    verify_on_chain = request.verify_on_chain if request else True
    try:
        return service.verify_merkle_package(
            evidence_id, provided_items=provided, verify_on_chain=verify_on_chain
        )
    except MerkleEvidenceError:
        raise HTTPException(
            status_code=404,
            detail=f"Merkle evidence package '{evidence_id}' was not found.",
        )


@router.get("/merkle/{evidence_id}/proof/{item_name}")
def get_merkle_proof(evidence_id: str, item_name: str, db: Session = Depends(get_db)):
    """Return the stored Merkle inclusion proof for one item."""
    _validate_evidence_id(evidence_id)
    service = MerkleEvidenceService(db)
    try:
        return service.get_proof(evidence_id, item_name)
    except MerkleEvidenceError:
        raise HTTPException(
            status_code=404,
            detail=f"Item '{item_name}' was not found in evidence package '{evidence_id}'.",
        )


@router.get("/merkle/{evidence_id}/report.pdf")
def get_merkle_report_pdf(
    evidence_id: str,
    verify_on_chain: bool = True,
    db: Session = Depends(get_db),
):
    """Render the forensic report PDF (Blockchain Integrity section + QR code)."""
    _validate_evidence_id(evidence_id)
    from app.services.forensic_report import build_forensic_report_pdf

    service = MerkleEvidenceService(db)
    try:
        verification = service.verify_merkle_package(
            evidence_id, verify_on_chain=verify_on_chain
        )
    except MerkleEvidenceError:
        raise HTTPException(
            status_code=404,
            detail=f"Merkle evidence package '{evidence_id}' was not found.",
        )

    pdf = build_forensic_report_pdf(evidence_id=evidence_id, verification=verification)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="satyavoice-evidence-{evidence_id}.pdf"'
        },
    )


@router.get("/anchor/queue")
def get_anchor_queue(status: str | None = None, db: Session = Depends(get_db)):
    """List offline/pending anchor-queue entries (optionally filtered by status)."""
    from app.services import anchor_queue

    if status is not None and status.upper() not in anchor_queue.ALL_STATES:
        raise HTTPException(
            status_code=400,
            detail=f"status must be one of {list(anchor_queue.ALL_STATES)}.",
        )
    entries = anchor_queue.list_queue(db, status.upper() if status else None)
    return {"count": len(entries), "entries": entries}


@router.post("/anchor/flush")
def flush_anchor_queue(db: Session = Depends(get_db)):
    """Attempt to anchor every queued (OFFLINE/FAILED) entry — call on reconnect."""
    from app.services import anchor_queue

    return anchor_queue.flush_queue(db)
