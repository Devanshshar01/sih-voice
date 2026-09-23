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
from app.services.evidence_anchor import EVIDENCE_ID_CONFLICT, EvidenceAnchorService
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

    Semantics (identity-first, evidence is immutable):

      * new ``evidence_id``                        -> 200, package created
      * existing id + identical frozen snapshot    -> 200, ``duplicate: true``
      * existing id + different snapshot           -> 409 EVIDENCE_ID_CONFLICT
        (never overwritten; existing hash + submitted hash are returned)
      * concurrent duplicate insert                -> resolved to one of the above

    ``exported_at``/``package_signature`` (export-operation fields) are removed
    before hashing, so repeated exports of the same finalized call register the
    same ``evidence_hash``. Removed paths are echoed back as
    ``ignored_export_fields``.

    Successful registration also creates the canonical Merkle commitment for the
    same snapshot, so ``GET /{evidence_id}/verify``, the integrity summary, the
    QR target and the forensic PDF all work from one canonical snapshot.

    The service layer never raises on DB failures; check status=='error' in the
    response body when integrating (HTTP 500 is reserved for truly unexpected errors).
    """
    service = EvidenceAnchorService(db)
    result = service.register_evidence_package(request.payload, request.evidence_id)

    if result.get("status") == "conflict":
        # EVIDENCE_ID_CONFLICT (Fix 1C): the id is already registered with
        # different frozen content. Registered evidence is immutable, so the
        # existing package is left untouched and both hashes are reported.
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": result.get("error_code", EVIDENCE_ID_CONFLICT),
                "message": result.get("error", "Evidence id already registered."),
                "evidence_id": result.get("evidence_id"),
                "existing_evidence_hash": result.get("existing_evidence_hash"),
                "submitted_evidence_hash": result.get("submitted_evidence_hash"),
                "conflict": True,
            },
        )

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

    # --- Canonical registration (Fix 4) --------------------------------------
    # GET /{id}/verify, the integrity summary, the QR target and the forensic PDF
    # all read the canonical Merkle store. Create it here so ONE /register call
    # yields ONE canonical snapshot per evidence_id (idempotent per id).
    _ensure_canonical_registration(db, result)
    return result


def _ensure_canonical_registration(db: Session, result: dict[str, Any]) -> None:
    """Register the canonical Merkle commitment for a just-registered snapshot.

    Idempotent per ``evidence_id``, so repeated export clicks cannot create
    duplicate Merkle packages. Best-effort by design (a canonical failure never
    fails the legacy registration), but never silent: the outcome is reported in
    ``result["canonical"]`` and logged.
    """
    evidence_id = result.get("evidence_id")
    # The service returns the exact stored canonical snapshot; it is consumed
    # here (and dropped from the HTTP response) so both stores commit the SAME
    # bytes and can never derive divergent hashes.
    canonical_payload = result.pop("canonical_payload", None)
    if not evidence_id or canonical_payload is None:
        return

    from app.services.evidence_verification import ensure_canonical_merkle_package

    try:
        canonical = ensure_canonical_merkle_package(
            db,
            evidence_id=evidence_id,
            canonical_payload=canonical_payload,
        )
    except Exception:
        logger.exception(
            "Canonical evidence registration failed (evidence_id=%s)", evidence_id
        )
        result["canonical"] = {"status": "error", "evidence_id": evidence_id}
        return

    result["canonical"] = {
        "status": canonical.get("status"),
        "duplicate": bool(canonical.get("duplicate")),
        "package_hash": canonical.get("package_hash"),
        "merkle_root": canonical.get("merkle_root"),
        "leaf_count": canonical.get("leaf_count"),
    }
    if canonical.get("queue_status") is not None:
        result["canonical"]["queue_status"] = canonical["queue_status"]
    # Surface the CANONICAL anchor outcome (anchorEvidence on the Merkle root)
    # at the response level so legacy consumers keep a truthful anchor_status
    # instead of the retired flat-root placeholder. Unavailable/disabled stays
    # as the legacy registration reported it.
    anchor_info = canonical.get("anchor")
    if isinstance(anchor_info, dict):
        result["canonical"]["anchor"] = anchor_info
        if anchor_info.get("status") in {"anchored", "failed", "dry_run"}:
            result["anchor_status"] = anchor_info["status"]
            if anchor_info.get("failure_reason"):
                result["failure_reason"] = anchor_info["failure_reason"]


def _verification_response(
    db: Session, evidence_id: str, verify_on_chain: bool
) -> dict[str, Any]:
    """The ONE verification implementation behind GET and POST ``/verify``.

    Both verbs call this, so they cannot return contradictory results. The
    result is the canonical verification envelope (canonical identities plus
    legacy-compatible aliases and the QR/verification URL block).
    """
    from app.services.evidence_verification import (
        EvidenceNotFound,
        verify_canonical_evidence,
    )
    from app.services.forensic_report import build_verification_url, verification_api_path

    try:
        result = verify_canonical_evidence(db, evidence_id, verify_on_chain=verify_on_chain)
    except (EvidenceNotFound, ValueError):
        raise HTTPException(
            status_code=404,
            detail=f"Evidence package '{evidence_id}' was not found.",
        )
    except Exception:
        logger.exception(
            "Unexpected error during evidence verification (evidence_id=%s)", evidence_id
        )
        raise HTTPException(
            status_code=500,
            detail="Evidence verification failed unexpectedly.",
        )

    result["verification"] = {
        "url": build_verification_url(evidence_id),
        "api_path": verification_api_path(evidence_id),
    }
    return result


@router.post("/{evidence_id}/verify")
def verify_evidence(
    evidence_id: str,
    verify_on_chain: bool = True,
    db: Session = Depends(get_db),
):
    """Independently verify an evidence package's integrity.

    Compatibility verb: this is the SAME canonical verification as
    ``GET /{evidence_id}/verify`` (one implementation, one result). All fields
    are server-derived; no client-supplied 'verified' claim is trusted.
    """
    return _verification_response(db, evidence_id, verify_on_chain)


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
    if result.get("status") == "conflict":
        # Same evidence_id registered with DIFFERENT content: registered
        # evidence is immutable — never overwritten, always a stable 409.
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": result.get("error_code", EVIDENCE_ID_CONFLICT),
                "message": result.get(
                    "error", "Evidence id already registered with different content."
                ),
                "evidence_id": result.get("evidence_id"),
                "existing_package_hash": result.get("existing_package_hash"),
                "submitted_package_hash": result.get("submitted_package_hash"),
                "conflict": True,
            },
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


@router.get("/{evidence_id}/verify")
def verify_evidence_integrity(
    evidence_id: str,
    verify_on_chain: bool = True,
    db: Session = Depends(get_db),
):
    """The canonical read path for verification (PDF QR, integrity panel, public).

    Served by the SAME implementation as ``POST /{evidence_id}/verify`` — the
    canonical verification envelope derived entirely from stored evidence
    (nothing is regenerated, no fresh timestamps are injected).
    """
    _validate_evidence_id(evidence_id)
    return _verification_response(db, evidence_id, verify_on_chain)


@router.get("/merkle/{evidence_id}/report.pdf")
def get_merkle_report_pdf(
    evidence_id: str,
    verify_on_chain: bool = True,
    db: Session = Depends(get_db),
):
    """Render the authoritative five-page forensic PDF and register its hash.

    Phase 7: the PDF is rendered from the frozen stored package, hashed after
    rendering, and the digest is persisted (evidence_report_records) — the PDF
    never contains its own hash.
    """
    _validate_evidence_id(evidence_id)
    from app.services.evidence_package import build_integrity_summary
    from app.services.forensic_report import render_and_register_report
    from app.services.merkle_evidence import MerkleEvidenceError

    service = MerkleEvidenceService(db)
    try:
        verification = service.verify_merkle_package(
            evidence_id, verify_on_chain=verify_on_chain
        )
        integrity = build_integrity_summary(db, evidence_id)
    except MerkleEvidenceError:
        raise HTTPException(
            status_code=404,
            detail=f"Merkle evidence package '{evidence_id}' was not found.",
        )

    rendered = render_and_register_report(
        db, evidence_id=evidence_id, verification=verification, integrity=integrity
    )
    return Response(
        content=rendered["pdf"],
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="satyavoice-evidence-{evidence_id}.pdf"',
            "X-Report-SHA256": rendered["report_sha256"],
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
