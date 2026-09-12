"""Forensics evidence registration, verification, and report API.

Endpoints:
  POST /forensics/register            — register a canonical evidence package
                                        (idempotent; duplicates return the
                                        original registration)
  POST /forensics/{evidence_id}/verify — verify one package (hash + chain)
  POST /forensics/chain/verify        — independently verify the ENTIRE ledger
  GET  /forensics/{evidence_id}/package — the immutable stored package (no
                                        embeddings/audio; hashes only)
  GET  /forensics/{evidence_id}/report.pdf — deterministic PDF rendered from
                                        the immutable stored package
"""
from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.auth import AuthContext, require_auth
from app.db import models as db_models
from app.db.database import get_db
from app.services import evidence_package as pkg_schema
from app.services.evidence_anchor import EvidenceAnchorService
from app.services.forensic_pdf import generate_forensic_pdf_for_package

router = APIRouter(prefix="/forensics", tags=["forensics"])


class EvidenceRegistrationRequest(BaseModel):
    evidence_id: str | None = None
    payload: dict[str, Any]


@router.post("/register")
def register_evidence(
    payload: EvidenceRegistrationRequest,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    """Register a forensic evidence package.

    Accepts either a canonical ``EvidencePackageInput`` (preferred — the
    package is validated and completed with backend-derived data) or a legacy
    free-form payload (registered as-is for backward compatibility).
    """
    try:
        service = EvidenceAnchorService(db)
        try:
            canonical = pkg_schema.EvidencePackageInput.model_validate(payload.payload)
            body = canonical.model_dump(mode="json")
        except ValidationError:
            # Legacy free-form payloads remain registrable.
            body = payload.payload
        return service.register_evidence_package(body, payload.evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/chain/verify")
def verify_full_chain(db: Session = Depends(get_db), auth: AuthContext = Depends(require_auth)):
    """Independently walk the entire ledger from GENESIS."""
    return EvidenceAnchorService(db).verify_full_chain()


@router.post("/{evidence_id}/verify")
def verify_evidence(
    evidence_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    try:
        service = EvidenceAnchorService(db)
        return service.verify_evidence_package(evidence_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{evidence_id}/package")
def get_evidence_package(
    evidence_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    """The immutable stored package (hashes/derived evidence only)."""
    package = (
        db.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )
    if package is None:
        raise HTTPException(status_code=404, detail=f"Evidence package '{evidence_id}' was not found.")
    return {
        "evidence_id": package.evidence_id,
        "evidence_hash": package.evidence_hash,
        "schema_version": package.schema_version,
        "package_format": package.package_format,
        "package_payload": package.package_payload,
        "status": package.status,
        "local_chain_root": package.local_chain_root,
        "local_chain_status": package.local_chain_status,
        "anchor_status": package.anchor_status,
        "blockchain_network": package.blockchain_network,
        "contract_address": package.contract_address,
        "tx_hash": package.anchor_tx_hash,
        "anchor_timestamp": package.anchor_timestamp.isoformat() if package.anchor_timestamp else None,
        "created_at": package.created_at.isoformat() if package.created_at else None,
    }


@router.get("/{evidence_id}/report.pdf")
def get_evidence_report_pdf(
    evidence_id: str,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(require_auth),
):
    """Deterministic PDF rendered from the immutable stored package."""
    package = (
        db.query(db_models.EvidencePackage)
        .filter(db_models.EvidencePackage.evidence_id == evidence_id)
        .first()
    )
    if package is None:
        raise HTTPException(status_code=404, detail=f"Evidence package '{evidence_id}' was not found.")

    pdf_bytes = generate_forensic_pdf_for_package(
        package_payload_json=package.package_payload,
        evidence_hash=package.evidence_hash,
        evidence_id=package.evidence_id,
        db=db,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="satyavoice-forensic-report-{package.evidence_id}.pdf"',
            # Advisory integrity header: the PDF's own SHA-256 so an operator
            # can confirm the download matches what the server rendered.
            "X-Evidence-Pdf-Sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        },
    )
