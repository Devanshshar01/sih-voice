"""Server-side forensic report (PDF) with a Blockchain Integrity section + QR.

WHY SERVER-SIDE?
  The browser already builds a client-side PDF (``src/lib/forensicPdf.ts``) for
  instant analyst download. This module produces the *authoritative* report on
  the server, where it can read the persisted Merkle package and anchor metadata
  directly, and where it can attach a QR code that points at the public
  verification portal.

BLOCKCHAIN INTEGRITY SECTION
  The report renders the exact fields a verifier needs to independently confirm
  the evidence — evidence id, Merkle root, network, contract, transaction hash,
  block, confirmations and a plain-language verification verdict. When the device
  is offline (no transaction yet) the section explicitly shows
  "OFFLINE — pending anchor" rather than inventing transaction details.

QR CODE
  The QR encodes ``{PUBLIC_VERIFY_BASE_URL}?evidence=<id>`` — an opaque case id
  only. No PII, no raw evidence, no hashes of raw data travel in the URL.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from app import config

logger = logging.getLogger("satyavoice.report")


def build_verification_url(evidence_id: str) -> str:
    """Return the public QR/verification URL for an evidence id."""
    base = config.PUBLIC_VERIFY_BASE_URL.rstrip("/")
    return f"{base}?evidence={evidence_id}"


def _qr_png_bytes(payload: str) -> bytes | None:
    """Render *payload* as a PNG QR code. Returns None if qrcode is unavailable."""
    try:
        import qrcode

        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:  # pragma: no cover - optional dependency
        logger.warning("QR generation unavailable: %s", type(exc).__name__)
        return None


def _verdict(verification: dict[str, Any] | None) -> str:
    if not verification:
        return "UNVERIFIED"
    if verification.get("valid") is True:
        return "VALID"
    if verification.get("valid") is False:
        return "TAMPERED / MISMATCH"
    return "UNVERIFIED"


def build_forensic_report_pdf(
    *,
    evidence_id: str,
    verification: dict[str, Any] | None = None,
    session_id: str | None = None,
    title: str = "SatyaVoice Forensic Evidence Report",
) -> bytes:
    """Render the forensic PDF and return its bytes.

    ``verification`` is the dict returned by
    :meth:`MerkleEvidenceService.verify_merkle_package` (or ``None`` when the
    report is generated before verification).
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    page_w, page_h = A4
    c = canvas.Canvas(buf, pagesize=A4)

    y = page_h - 20 * mm
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, title)
    y -= 10 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, "Technical integrity evidence package for analyst/verifier review.")
    y -= 4 * mm
    c.drawString(
        20 * mm, y,
        "This is a cryptographic integrity record, not a legal certification.",
    )
    y -= 10 * mm

    # --- Case metadata -------------------------------------------------------
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Case")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    rows = [("Evidence ID", evidence_id)]
    if session_id:
        rows.append(("Session ID", session_id))
    for label, value in rows:
        c.drawString(20 * mm, y, f"{label}:")
        c.setFont("Courier", 8)
        c.drawString(60 * mm, y, str(value))
        c.setFont("Helvetica", 9)
        y -= 6 * mm
    y -= 4 * mm

    # --- Blockchain integrity ------------------------------------------------
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, y, "Blockchain Integrity Verification")
    y -= 6 * mm
    c.setFont("Helvetica", 9)

    v = verification or {}
    anchor_status = v.get("anchor_status") or "unavailable"
    lines = [
        ("Evidence Root (Merkle)", v.get("merkle_root") or "—"),
        ("Blockchain Status", str(anchor_status).upper()),
        ("Verification", _verdict(verification)),
        ("Network", v.get("blockchain_network") or config.BLOCKCHAIN_DISPLAY_NAME),
        ("Contract", v.get("contract_address") or "—"),
        ("Transaction", v.get("tx_hash") or "—"),
        ("Block", str(v.get("block_number")) if v.get("block_number") is not None else "—"),
        ("Anchored at", v.get("anchor_timestamp") or "—"),
        ("Leaves (items)", str(v.get("leaf_count")) if v.get("leaf_count") is not None else "—"),
    ]
    if anchor_status in {"unavailable", "offline"} and not v.get("tx_hash"):
        lines.insert(1, ("Note", "OFFLINE — pending anchor (local ledger only)"))

    for label, value in lines:
        c.setFont("Helvetica", 9)
        c.drawString(20 * mm, y, f"{label}:")
        c.setFont("Courier", 8)
        text = str(value)
        # Wrap very long hex values so they stay on the page.
        c.drawString(65 * mm, y, text[:70])
        y -= 5.5 * mm
        if len(text) > 70:
            c.drawString(65 * mm, y, text[70:140])
            y -= 5.5 * mm

    # --- QR code -------------------------------------------------------------
    url = build_verification_url(evidence_id)
    png = _qr_png_bytes(url)
    if png is not None:
        try:
            from reportlab.lib.utils import ImageReader

            qr_size = 38 * mm
            c.drawImage(
                ImageReader(io.BytesIO(png)),
                20 * mm,
                y - qr_size,
                width=qr_size,
                height=qr_size,
            )
            c.setFont("Helvetica", 7)
            c.drawString(
                20 * mm,
                y - qr_size - 4 * mm,
                "Scan to verify independently:",
            )
            c.setFont("Courier", 7)
            c.drawString(20 * mm, y - qr_size - 8 * mm, url)
        except Exception as exc:  # pragma: no cover - image embedding optional
            logger.warning("QR embed failed: %s", type(exc).__name__)

    c.setFont("Helvetica-Oblique", 7)
    c.drawString(
        20 * mm,
        12 * mm,
        "Any verifier can recompute the SHA-256 Merkle root from the evidence items "
        "and compare it to the anchored commitment. No trust in this document is required.",
    )

    c.showPage()
    c.save()
    return buf.getvalue()
