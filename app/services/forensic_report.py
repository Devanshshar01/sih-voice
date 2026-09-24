"""Server-side forensic PDF report (integrity-hardened, five pages).

WHY SERVER-SIDE?
    The browser builds a client-side PDF (``src/lib/forensicPdf.ts``) for instant
    analyst download. This module produces the *authoritative* report from the
    frozen evidence package (the stored canonical manifest + verification
    record), where Merkle package and anchor metadata can be read directly and
    where a QR code can point at the public verification portal.

ONE AUTHORITATIVE REPRESENTATION (Phase 6)
    The report is generated from a FROZEN evidence snapshot (the verification
    dict + integrity summary), never from live mutable queries.

PDF HASHING (Phase 7 — no circular hashing)
    The PDF contains the package hash, Merkle root, ledger head and anchor
    data, but NEVER its own final byte hash. The caller hashes the rendered
    bytes and stores ``report_sha256`` (see ``render_and_register_report``).

QUALITY CONTRACT (Phase 8, verified by tests/test_forensic_pdf.py)
    - no "null"/"None"/"NaN"/"Infinity"/"undefined" strings
    - no raw Python objects
    - long hashes render fully in monospace (wrapped, never clipped)
    - page numbers, report identifier, and schema version on every page
    - DRY_RUN anchors are rendered as SIMULATED, never as confirmed
    - NO legal-admissibility claims of any kind

TERMINOLOGY
    "cryptographically verifiable / tamper-evident / integrity-verifiable /
    hash-linked / blockchain-anchored (when actually confirmed)" — nothing
    stronger.
"""
from __future__ import annotations

import hashlib
import io
import logging
from typing import Any

from app import config

logger = logging.getLogger("satyavoice.report")

REPORT_FORMAT = "satyavoice-forensic-report-v1"

# Strings that must never appear in a rendered report (claimed capability or
# serialization leak). Enforced by tests/test_forensic_pdf.py.
FORBIDDEN_STRINGS = ("NaN", "Infinity", "undefined", "tamper-proof", "tamper proof")

_VERIFICATION_PATH = "/api/v1/forensics/{evidence_id}/verify"

# Layout constants (single source of truth for margins/typography).
_MARGIN_MM = 18
_BODY_FONT = "Helvetica"
_BODY_SIZE = 9
_MONO_FONT = "Courier"
_MONO_SIZE = 7.5
# A4 content box width in points (210mm page minus both 18mm margins). Every
# table must sum to at most this width or its right edge clips past the margin
# (a Phase 8 visual-regression defect: 500pt tables in a 493.23pt frame).
_CONTENT_WIDTH_PT = (210 - 2 * _MARGIN_MM) * 2.83465

# Rendered in place of a hash that is genuinely not available. Never a synthetic
# digest, never "null"/"None".
_HASH_ABSENT = "NOT AVAILABLE"


def build_verification_url(evidence_id: str) -> str:
    """Public QR/verification URL: carries ONLY the opaque evidence id (no PII)."""
    base = config.PUBLIC_VERIFY_BASE_URL.rstrip("/")
    return f"{base}?evidence={evidence_id}"


def verification_api_path(evidence_id: str) -> str:
    """Backend verification endpoint path embedded in the report."""
    return _VERIFICATION_PATH.format(evidence_id=evidence_id)


def report_identifier(evidence_id: str) -> str:
    """Stable, non-PII report identifier (derived from the evidence id)."""
    digest = hashlib.sha256(evidence_id.encode("utf-8")).hexdigest()[:16].upper()
    return f"SVR-{digest}"


def _qr_png_bytes(payload: str) -> bytes | None:
    """Render *payload* as a PNG QR code. Returns None if qrcode is unavailable."""
    try:
        import qrcode

        img = qrcode.make(payload)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as exc:
        logger.warning("QR generation unavailable: %s", type(exc).__name__)
        return None


def _text(value: Any, fallback: str = "Not available") -> str:
    """Render any value safely: None/empty -> explicit fallback, never 'None'.

    Only JSON primitives are rendered. Any other type (a stray ORM object, a
    custom class) yields the fallback instead of its ``repr``/``str``: a raw
    Python object must never reach the deliverable, and calling ``str()`` on an
    arbitrary object can also execute attacker-controlled ``__repr__`` code.
    """
    if value is None:
        return fallback
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return fallback  # NaN / +-Infinity never render
        return f"{value:.4f}".rstrip("0").rstrip(".") if value % 1 else str(int(value))
    if not isinstance(value, (str, int, bool)):
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _hash_lines(hex_hash: str) -> list[str]:
    """Split a hex hash into wrapped monospace lines (never clipped)."""
    text = _text(hex_hash, _HASH_ABSENT)
    if text == _HASH_ABSENT:
        return [text]
    return [text[i : i + 64] for i in range(0, len(text), 64)]


def _verdict(verification: dict[str, Any] | None) -> str:
    if not verification:
        return "UNVERIFIED"
    if verification.get("valid") is True:
        return "VALID"
    if verification.get("valid") is False:
        return "TAMPERED / MISMATCH"
    return "UNVERIFIED"


def _anchor_display_status(anchor_status: str | None) -> str:
    """Map the internal anchor status onto the report's status vocabulary."""
    normalized = (anchor_status or "disabled").lower()
    if normalized == "anchored":
        return "CONFIRMED"
    if normalized == "dry_run":
        return "SIMULATED (DRY RUN)"
    if normalized in {"pending", "submitted"}:
        return "SUBMITTED"
    if normalized == "failed":
        return "FAILED"
    if normalized == "unavailable":
        return "DISABLED"
    return normalized.upper()


def _build_styles() -> dict[str, Any]:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle

    ink = colors.HexColor("#0f172a")
    muted = colors.HexColor("#475569")
    heading = ParagraphStyle(
        "heading", fontName="Helvetica-Bold", fontSize=13, textColor=ink,
        spaceBefore=6, spaceAfter=6, alignment=TA_LEFT,
    )
    sub = ParagraphStyle(
        "sub", fontName="Helvetica-Bold", fontSize=10, textColor=ink, spaceBefore=4, spaceAfter=3
    )
    body = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=_BODY_SIZE, textColor=ink,
        leading=12, spaceAfter=2,
    )
    note = ParagraphStyle(
        "note", fontName="Helvetica-Oblique", fontSize=8, textColor=muted, leading=10
    )
    return {"heading": heading, "sub": sub, "body": body, "note": note, "ink": ink}


def _kv_table(rows: list[tuple[str, Any]], styles: dict[str, Any]) -> Any:
    """Two-column label/value table; monospace values wrap, never clip."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    mono_cell = ParagraphStyle(
        "mono_cell", fontName=_MONO_FONT, fontSize=_MONO_SIZE, leading=9.5,
        textColor=styles["ink"],
    )
    data = []
    for label, value in rows:
        data.append(
            [
                Paragraph(f"<b>{label}</b>", styles["body"]),
                Paragraph(str(value), mono_cell),
            ]
        )
    table = Table(data, colWidths=[150, _CONTENT_WIDTH_PT - 150], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, styles["ink"], None, (0.9, 0.9)),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return table


def _page1(story: list, *, data: dict[str, Any], styles: dict[str, Any]) -> None:
    """Cover: identity + status + explicit integrity (not legal) statement."""
    from reportlab.platypus import Paragraph, Spacer

    story.extend(
        [
            Paragraph("SATYAVOICE", styles["heading"]),
            Paragraph("FORENSIC VOICE ANALYSIS REPORT", styles["heading"]),
            Spacer(1, 4),
            _kv_table(
                [
                    ("Evidence ID", _text(data.get("evidence_id"))),
                    ("Call ID", _text(data.get("session_id"))),
                    ("Report status", _text(data.get("report_status"), "REGISTERED")),
                    ("Created at", _text(data.get("created_at"))),
                    ("Completed at", _text(data.get("completed_at"))),
                    ("Schema version", _text(data.get("schema_version"))),
                    ("Report identifier", _text(data.get("report_identifier"))),
                ],
                styles,
            ),
            Spacer(1, 8),
            Paragraph(
                "Cryptographically verifiable forensic evidence package. This "
                "document is a cryptographically verifiable, tamper-evident "
                "integrity record: every claimed value can be recomputed "
                "independently from the stored evidence commitments.",
                styles["body"],
            ),
            Spacer(1, 3),
            Paragraph(
                "Scope: integrity verification only. This report is not a legal "
                "certification and makes no claim of courtroom admissibility.",
                styles["note"],
            ),
        ]
    )


def _page2(story: list, *, data: dict[str, Any], styles: dict[str, Any]) -> None:
    """Detection summary: model score vs fused risk vs confidence vs status."""
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    story.extend([PageBreak(), Paragraph("DETECTION SUMMARY", styles["heading"]), Spacer(1, 4)])
    detection = data.get("detection") or {}
    story.append(
        _kv_table(
            [
                ("Overall risk (fused)", _text(detection.get("risk_score"))),
                ("Risk status", _text(detection.get("risk_status"))),
                ("Anti-spoof model score", _text(detection.get("model_score"))),
                ("Anti-spoof status", _text(detection.get("model_status"))),
                ("Speaker verification", _text(detection.get("speaker_match"))),
                ("Contextual indicators", _text(detection.get("contextual"))),
                ("Confidence", _text(detection.get("confidence"))),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Score semantics: the anti-spoof MODEL SCORE is the raw detector "
            "output; the fused risk score is the weighted combination across "
            "acoustic, intent and identity evidence; confidence describes the "
            "evidence quality backing the status.",
            styles["note"],
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("Models and audio configuration", styles["sub"]))
    models = data.get("model_metadata") or {}
    story.append(
        _kv_table(
            [
                ("Detector mode", _text(models.get("detector_mode"))),
                ("Model identifier", _text(models.get("model_id") or models.get("detector"))),
                ("Model version", _text(models.get("model_version"))),
                ("Audio sample rate", _text(models.get("sample_rate"), "16000 Hz")),
                (
                    "Window configuration",
                    _text(models.get("window_config"), "4.0 s window / 0.5 s hop"),
                ),
                ("Evidence created at", _text(data.get("created_at"))),
            ],
            styles,
        )
    )


def _page3(story: list, *, data: dict[str, Any], styles: dict[str, Any]) -> None:
    """Integrity: artifact digests + the three package-level identities."""
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle

    story.extend([PageBreak(), Paragraph("INTEGRITY", styles["heading"]), Spacer(1, 4)])
    story.append(Paragraph("Evidence artifacts (SHA-256 of actual bytes)", styles["sub"]))

    mono_cell = ParagraphStyle(
        "artifact_mono", fontName=_MONO_FONT, fontSize=_MONO_SIZE, leading=9.5,
        textColor=styles["ink"],
    )
    body_cell = ParagraphStyle(
        "artifact_body", fontName="Helvetica", fontSize=8.5, leading=10,
        textColor=styles["ink"],
    )
    artifact_rows = data.get("artifacts") or []
    header = [
        Paragraph(f"<b>{h}</b>", body_cell)
        for h in ("Artifact", "Media type", "Size (B)", "SHA-256")
    ]
    rows = [header]
    for artifact in artifact_rows:
        digest = _text(artifact.get("sha256"), "—")
        digest_cell = "<br/>".join(_hash_lines(digest)) if digest != "—" else "—"
        rows.append(
            [
                Paragraph(_text(artifact.get("artifact_id") or artifact.get("role")), body_cell),
                Paragraph(_text(artifact.get("media_type")), body_cell),
                Paragraph(_text(artifact.get("byte_length")), body_cell),
                Paragraph(digest_cell, mono_cell),
            ]
        )
    if len(rows) == 1:
        rows.append(
            [
                Paragraph("No artifacts recorded", body_cell),
                Paragraph("—", body_cell),
                Paragraph("—", body_cell),
                Paragraph("—", mono_cell),
            ]
        )
    table = Table(
        rows, colWidths=[110, 80, 45, _CONTENT_WIDTH_PT - 235], hAlign="LEFT", repeatRows=1
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.25, styles["ink"], None, (0.9, 0.9)),
                ("BACKGROUND", (0, 0), (-1, 0), styles["ink"]),
                ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(Paragraph("Package identities", styles["sub"]))
    story.append(
        _kv_table(
            [
                ("Canonical package SHA-256", "<br/>".join(_hash_lines(data.get("package_hash")))),
                ("Ledger head hash", "<br/>".join(_hash_lines(data.get("ledger_head")))),
                ("Merkle root", "<br/>".join(_hash_lines(data.get("merkle_root")))),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Artifact, package, ledger and Merkle hashes are DISTINCT identities "
            "and are never collapsed into one field. A verifier recomputes each "
            "of them independently.",
            styles["note"],
        )
    )


def _page4(story: list, *, data: dict[str, Any], styles: dict[str, Any]) -> None:
    """Blockchain anchor: explicit status; DRY_RUN is SIMULATED, never confirmed."""
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    story.extend([PageBreak(), Paragraph("BLOCKCHAIN ANCHOR", styles["heading"]), Spacer(1, 4)])
    anchor = data.get("blockchain") or {}
    display = _anchor_display_status(anchor.get("status"))
    rows: list[tuple[str, Any]] = [("Status", display)]
    if display == "CONFIRMED":
        rows += [
            ("Network", _text(anchor.get("network"))),
            ("Chain ID", _text(anchor.get("chain_id"))),
            ("Contract address", _text(anchor.get("contract"))),
            ("Transaction hash", "<br/>".join(_hash_lines(anchor.get("tx_hash")))),
            ("Block number", _text(anchor.get("block_number"))),
            ("Anchored at", _text(anchor.get("anchored_at"))),
            ("Anchored Merkle root", "<br/>".join(_hash_lines(anchor.get("merkle_root")))),
        ]
    elif display == "SIMULATED (DRY RUN)":
        rows += [
            ("Network (label only)", _text(anchor.get("network"))),
            (
                "Note",
                _text(
                    anchor.get("note"),
                    "SIMULATED anchor (dry run): no transaction was submitted "
                    "to any blockchain.",
                ),
            ),
        ]
    else:
        rows += [
            (
                "Note",
                _text(
                    anchor.get("note"),
                    "Not anchored: blockchain anchoring is disabled or not "
                    "confirmed for this evidence. No transaction hash exists.",
                ),
            ),
        ]
    if anchor.get("failure_reason"):
        rows.append(("Failure reason", _text(anchor.get("failure_reason"))))
    story.append(_kv_table(rows, styles))
    story.append(Spacer(1, 4))
    if display != "CONFIRMED":
        story.append(
            Paragraph(
                "Local integrity verification is independent of blockchain "
                "anchoring: this evidence remains valid without a chain anchor.",
                styles["note"],
            )
        )
    else:
        story.append(
            Paragraph(
                "The anchored commitment is the Merkle root above; anyone can "
                "re-derive it from the evidence items and compare it against "
                "the on-chain commitment.",
                styles["note"],
            )
        )


def _page5(story: list, *, data: dict[str, Any], styles: dict[str, Any]) -> None:
    """Verification: endpoint, statuses, and the QR (URL only, no PII)."""
    from reportlab.platypus import PageBreak, Paragraph, Spacer

    story.extend([PageBreak(), Paragraph("VERIFICATION", styles["heading"]), Spacer(1, 4)])
    evidence_id = _text(data.get("evidence_id"))
    verification_url = data.get("verification_url") or build_verification_url(evidence_id)
    anchor = data.get("blockchain") or {}
    ledger = data.get("ledger") or {}
    ledger_display = (
        "VALID" if ledger.get("valid") is True
        else "INVALID" if ledger.get("valid") is False
        else "NOT APPLICABLE"
    )
    story.append(
        _kv_table(
            [
                ("Verification endpoint", verification_api_path(evidence_id)),
                ("Verification URL", verification_url),
                ("Evidence ID", evidence_id),
                ("Merkle root", "<br/>".join(_hash_lines(data.get("merkle_root")))),
                ("Package hash", "<br/>".join(_hash_lines(data.get("package_hash")))),
                ("Ledger verification", ledger_display),
                ("Blockchain verification", _anchor_display_status(anchor.get("status"))),
                ("Local package integrity", _text(data.get("package_integrity"), "UNVERIFIED")),
            ],
            styles,
        )
    )
    story.append(Spacer(1, 10))
    png = _qr_png_bytes(verification_url)
    if png is not None:
        from reportlab.platypus import Image

        story.append(Image(io.BytesIO(png), width=34 * 2.83, height=34 * 2.83))
        story.append(Spacer(1, 3))
        story.append(
            Paragraph(
                "Scan to verify independently. The QR encodes the verification "
                "URL only — the opaque evidence id; never PII, transcripts or "
                "raw evidence.",
                styles["note"],
            )
        )
    else:
        story.append(
            Paragraph(
                "QR generation unavailable on this host; use the verification "
                "URL above instead.",
                styles["note"],
            )
        )


def _assemble_report_data(
    *,
    evidence_id: str,
    verification: dict[str, Any] | None,
    integrity: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Freeze everything the report will show (Phase 6: no live queries).

    ``verification`` is the Merkle-service verification dict; ``integrity`` the
    EvidenceIntegritySummary. Either may be absent (report rendered before
    verification) — every missing field renders as an explicit "Not available",
    never as "null"/"None".
    """
    v = verification or {}
    s = integrity or {}
    anchor = s.get("blockchain") or {}
    ledger = s.get("ledger") or {}

    return {
        "evidence_id": evidence_id,
        "session_id": session_id or v.get("session_id"),
        "report_status": (
            "VERIFIED" if v.get("valid") is True
            else "TAMPERED" if v.get("valid") is False
            else "REGISTERED"
        ),
        "created_at": v.get("created_at") or s.get("created_at"),
        "completed_at": v.get("completed_at"),
        "schema_version": s.get("schema_version") or v.get("schema_version") or "phase10-v1",
        "report_identifier": report_identifier(evidence_id),
        "package_hash": s.get("package_sha256") or v.get("package_hash"),
        "merkle_root": s.get("merkle_root") or v.get("merkle_root"),
        "ledger_head": s.get("ledger_head"),
        "ledger": ledger
        or {
            "valid": bool(v.get("package_hash_integrity") and v.get("merkle_root_integrity"))
        },
        "package_integrity": (
            "VERIFIED" if (v.get("package_hash_integrity") and v.get("merkle_root_integrity"))
            else "MISMATCH" if v.get("valid") is False
            else "UNVERIFIED"
        ),
        "detection": v.get("detection") or {},
        "model_metadata": v.get("model_metadata") or {},
        "artifacts": v.get("artifacts") or [],
        "blockchain": anchor
        or {
            "status": v.get("anchor_status") or "unavailable",
            "network": v.get("blockchain_network"),
            "contract": v.get("contract_address"),
            "tx_hash": v.get("tx_hash"),
            "block_number": v.get("block_number"),
            "anchored_at": v.get("anchor_timestamp"),
            "merkle_root": v.get("merkle_root"),
            "failure_reason": v.get("failure_reason"),
        },
        "verification_url": build_verification_url(evidence_id),
    }


def _draw_footer_with_total(canvas_obj: Any, doc: Any) -> None:
    """Footer callback: brand, schema version, report id, page X of Y."""
    data = getattr(doc, "_report_data", {})
    total = data.get("_total_pages") or 5
    mm = 2.83465
    canvas_obj.saveState()
    canvas_obj.setFont("Helvetica", 7)
    canvas_obj.drawString(
        _MARGIN_MM * mm,
        10 * mm,
        f"SatyaVoice — evidence schema version: {data.get('schema_version', 'unknown')}",
    )
    canvas_obj.drawCentredString(
        105 * mm, 10 * mm, f"Report identifier: {data.get('report_identifier', 'unknown')}"
    )
    canvas_obj.drawRightString(
        (210 - _MARGIN_MM) * mm,
        10 * mm,
        f"Page {canvas_obj.getPageNumber()} of {total}",
    )
    canvas_obj.restoreState()


def build_forensic_report_pdf(
    *,
    evidence_id: str,
    verification: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
    session_id: str | None = None,
    payload: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    title: str = "Forensic Voice Analysis Report",
) -> bytes:
    """Render the five-page forensic PDF and return its bytes.

    Page structure (Phase 6):
        1 cover/status  2 detection summary  3 integrity
        4 blockchain anchor  5 verification + QR

    The PDF never contains its own byte hash (Phase 7). Use
    ``render_and_register_report`` to hash the result and persist it.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate

    data = _assemble_report_data(
        evidence_id=evidence_id,
        verification=verification,
        integrity=integrity,
        session_id=session_id,
        payload=payload,
        artifacts=artifacts,
    )
    styles = _build_styles()

    # Two-pass build so the footer knows the real total page count.
    buf = io.BytesIO()
    for pass_index in (1, 2):
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=_MARGIN_MM * 2.83465,
            rightMargin=_MARGIN_MM * 2.83465,
            topMargin=16 * 2.83465,
            bottomMargin=16 * 2.83465,
            title=f"SatyaVoice {title} — {evidence_id}",
            author="SatyaVoice",
            subject="Cryptographically verifiable forensic evidence package",
            # Phase 7 (no circular hashing / reproducible digest): reportlab
            # normally stamps /CreationDate, /ModDate and a random /ID, which
            # would make two renders of the SAME frozen snapshot hash
            # differently. ``invariant=1`` derives those from the document
            # content instead, so report_sha256 is reproducible and an
            # independent verifier can re-render and match it exactly.
            invariant=1,
        )
        doc._report_data = data  # footer state
        story: list = []
        _page1(story, data=data, styles=styles)
        _page2(story, data=data, styles=styles)
        _page3(story, data=data, styles=styles)
        _page4(story, data=data, styles=styles)
        _page5(story, data=data, styles=styles)
        doc.build(
            story, onFirstPage=_draw_footer_with_total, onLaterPages=_draw_footer_with_total
        )
        if pass_index == 1:
            # Count pages from the first pass so pass-2 footers are correct.
            from pypdf import PdfReader

            data["_total_pages"] = len(PdfReader(io.BytesIO(buf.getvalue())).pages)

    return buf.getvalue()


def render_and_register_report(
    db: Any,
    *,
    evidence_id: str,
    verification: dict[str, Any] | None = None,
    integrity: dict[str, Any] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Render the PDF, hash the actual bytes, persist report_sha256 (Phase 7).

    Returns {"pdf": bytes, "report_sha256": hex, "page_count": N}.
    """
    from app.db import models as db_models

    # --- Frozen payload + real artifacts (stored bytes only, never invented) --
    payload: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = []
    try:
        legacy_row = (
            db.query(db_models.EvidencePackage)
            .filter(db_models.EvidencePackage.evidence_id == evidence_id)
            .first()
        )
        if legacy_row is not None and legacy_row.package_payload:
            import json as _json

            payload_bytes = legacy_row.package_payload.encode("utf-8")
            payload = _json.loads(legacy_row.package_payload)
            artifacts.append(
                {
                    "artifact_id": "evidence_package_payload",
                    "role": "canonical_evidence_snapshot",
                    "media_type": "application/json",
                    "byte_length": len(payload_bytes),
                    "sha256": hashlib.sha256(payload_bytes).hexdigest(),
                }
            )
        merkle_row = (
            db.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .first()
        )
        if merkle_row is not None and merkle_row.canonical_package:
            manifest_bytes = merkle_row.canonical_package.encode("utf-8")
            artifacts.append(
                {
                    "artifact_id": "canonical_manifest",
                    "role": "evidence_manifest",
                    "media_type": "application/json",
                    "byte_length": len(manifest_bytes),
                    "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                }
            )
    except Exception:
        # A decode failure must never break report generation: the report then
        # falls back to the verification/integrity fields it does have.
        logger.warning("Frozen payload unavailable for report (evidence_id=%s)", evidence_id)

    pdf = build_forensic_report_pdf(
        evidence_id=evidence_id,
        verification=verification,
        integrity=integrity,
        session_id=session_id,
        payload=payload,
        artifacts=artifacts or None,
    )
    from pypdf import PdfReader

    page_count = len(PdfReader(io.BytesIO(pdf)).pages)
    report_sha256 = hashlib.sha256(pdf).hexdigest()

    schema_version = (
        (integrity or {}).get("schema_version")
        or (verification or {}).get("schema_version")
        or "phase10-v1"
    )
    row = (
        db.query(db_models.EvidenceReportRecord)
        .filter(db_models.EvidenceReportRecord.evidence_id == evidence_id)
        .first()
    )
    if row is None:
        row = db_models.EvidenceReportRecord(evidence_id=evidence_id)
        db.add(row)
    row.report_sha256 = report_sha256
    row.schema_version = schema_version
    row.page_count = page_count
    db.commit()

    return {"pdf": pdf, "report_sha256": report_sha256, "page_count": page_count}