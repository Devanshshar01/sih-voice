"""Deterministic server-side forensic PDF generation.

The report is rendered EXCLUSIVELY from the immutable evidence package stored
in the database (EvidencePackage.package_payload) — never from ad-hoc frontend
state. Reproducibility property: the same stored package always renders
byte-identical PDFs (no render-time randomness, fixed metadata, content
derived by canonical serialization of the stored package).

The PDF is a minimal, dependency-free PDF 1.4 writer. Verification and
chain-of-custody sections come from the ledger/anchor services, and every
report includes the integrity disclaimer documenting what the system does and
does not establish.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.services.evidence_anchor import EvidenceAnchorService
from app.services.evidence_package import canonical_json

# Fixed producer string: identical across runs so the same package reproduces
# byte-identical documents.
PDF_PRODUCER = "SatyaVoice Forensic Evidence Generator 1.0"

_DISCLAIMER = (
    "SCOPE AND LIMITATIONS: This document is a technical integrity report of "
    "derived, hashed evidence (acoustic scores, speaker similarity, transcript "
    "digests, contextual intent findings) produced by the SatyaVoice pipeline. "
    "Raw audio and full transcripts are intentionally excluded. The evidence "
    "hash, ledger chain, and blockchain anchor demonstrate that the recorded "
    "derived evidence has not been altered after registration - they do NOT "
    "assert that the underlying analysis is correct, that the source call is "
    "authentic, or that this record is legally admissible in any jurisdiction. "
    "Admissibility determinations belong to courts and qualified legal process, "
    "not to this application."
)


def _escape_pdf_text(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", "")
        .replace("\n", " ")
    )


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        s = f"{value:.4f}".rstrip("0").rstrip(".")
        return s or "0"
    return str(value)


def _short(value: Optional[str], head: int = 16, tail: int = 12) -> str:
    if not value:
        return "pending / not available"
    if len(value) <= head + tail + 1:
        return value
    return f"{value[:head]}...{value[-tail:]}"


def build_report_lines(
    package_payload: Dict[str, Any],
    evidence_hash: str,
    verification: Dict[str, Any],
) -> List[str]:
    """Render the human-readable report content from the immutable package.

    Pure function of (package_payload, verification result) - no clock, no
    randomness - which is what makes the PDF reproducible byte-for-byte.
    """
    prov = package_payload.get("model_provenance", {}) or {}
    lines: List[str] = [
        "SATYAVOICE TECHNICAL INTEGRITY EVIDENCE REPORT",
        "Generated from the immutable stored evidence package",
        "",
        "== 1. INCIDENT OVERVIEW ==",
        f"Call / session ID: {package_payload.get('call_id', 'unknown')}",
        f"Caller: {package_payload.get('caller_id', 'unknown')}   Recipient: {package_payload.get('recipient_id', 'unknown')}",
        f"Session window: {package_payload.get('session_start') or 'unknown'} -> {package_payload.get('session_end') or 'open'}",
        f"Duration: {_fmt(float(package_payload.get('duration_seconds') or 0))} s   Codec: {_fmt(package_payload.get('codec'))}",
        f"Language(s): {', '.join(package_payload.get('detected_languages') or []) or _fmt(package_payload.get('language'))}",
        f"Registered at: {package_payload.get('generated_at', 'unknown')}",
        f"Disposition: {package_payload.get('disposition', 'closed')}   Action taken: {package_payload.get('action_taken', 'none')}",
        f"Verification result: {package_payload.get('verification_result') or 'none recorded'}",
        "",
        "== 2. MODEL / VERSION INFORMATION ==",
        f"Detector mode: {prov.get('detector_mode', 'unknown')}",
        f"Acoustic model: {prov.get('acoustic_model_id') or 'not recorded'} (rev {prov.get('acoustic_model_revision') or '-'})",
        f"ASR model: {prov.get('asr_model') or 'not recorded'}",
        f"Speaker model: {prov.get('speaker_model') or 'not recorded'} (v {prov.get('speaker_model_version') or '-'})",
        f"Artifact hashes: {canonical_json(prov.get('model_artifact_hashes') or {}) if prov.get('model_artifact_hashes') else 'none recorded'}",
        f"Risk config fingerprint: {prov.get('risk_config_fingerprint') or 'not recorded'}",
        "",
        "== 3. RISK SUMMARY ==",
        f"Peak risk score: {package_payload.get('peak_risk_score', 0)}/100   Final fused score: {package_payload.get('fused_risk_score', 0)}/100",
    ]

    findings = package_payload.get("intent_findings") or []
    if findings:
        lines.append("Contextual intent findings:")
        for f in findings:
            lines.append(
                f"  - [{f.get('severity', 'info')}] {f.get('category', '?')} ({f.get('speech_act', '?')}) "
                f"lang={f.get('language', '?')} conf={float(f.get('confidence', 0)):.2f} phrase=\"{f.get('matched_phrase', '')}\""
            )
    else:
        lines.append("Contextual intent findings: none recorded.")

    lines += [
        "",
        "== 4. DETECTION TIMELINE (per 4-second window) ==",
    ]

    windows = package_payload.get("windows") or []
    if not windows:
        lines.append("No per-window evidence recorded.")
    for w in windows:
        lines.append(
            f"Window {w.get('window_index', '?')} t=+{w.get('relative_time_seconds', 0)}s "
            f"risk={w.get('risk_score', 0)}/100 acoustic={float(w.get('acoustic_score', 0)):.4f} "
            f"intent={float(w.get('intent_score', 0)):.4f} status={w.get('status', '?')}"
        )
        lines.append(
            f"  speaker_similarity={_fmt(w.get('speaker_similarity'))} "
            f"identity_mismatch={_fmt(w.get('identity_mismatch'))} "
            f"vad_active={_fmt(w.get('vad_active'))} lang={_fmt(w.get('language'))} codec={_fmt(w.get('codec'))}"
        )
        transcript_hash = w.get("transcript_hash")
        lines.append(f"  transcript_hash={transcript_hash or 'no transcript recorded (hash omitted)'}")
        rationale = w.get("rationale") or []
        if rationale:
            lines.append(f"  rationale: {' | '.join(rationale)}")

    lines += [
        "",
        "== 5. EVIDENCE TABLE (hashes) ==",
        f"Package evidence hash (SHA-256): {evidence_hash}",
        f"Schema version: {package_payload.get('schema_version', '?')}",
    ]
    for w in windows:
        lines.append(f"  window {w.get('window_index', '?')}: transcript_hash={w.get('transcript_hash') or 'n/a'}")

    lines += [
        "",
        "== 6. INTEGRITY & CHAIN INFORMATION ==",
        f"Evidence hash integrity: {'VERIFIED' if verification.get('evidence_hash_integrity') else 'MISMATCH'}",
        f"Local chain integrity: {'VERIFIED' if verification.get('local_chain_integrity') else 'MISMATCH'}",
        f"Full ledger chain integrity: {'VERIFIED' if verification.get('full_chain_integrity') else 'MISMATCH'}",
        f"Local chain root: {verification.get('local_chain_root') or 'pending'}",
        f"Ledger records for this package: {verification.get('ledger_record_count', 0)}",
        f"Anchoring status: {verification.get('anchor_status', 'unavailable')}",
        f"Blockchain network: {verification.get('blockchain_network') or 'not configured'}",
        f"Contract address: {verification.get('contract_address') or 'not configured'}",
        f"Transaction hash: {verification.get('tx_hash') or 'not confirmed'}",
        f"Anchor timestamp: {verification.get('anchor_timestamp') or 'not confirmed'}",
        f"Public anchor consistency: {'CONFIRMED' if verification.get('public_anchor_consistent') else 'NOT CONFIRMED'}",
        "",
        "== 7. SCOPE AND LIMITATIONS ==",
        _DISCLAIMER,
    ]

    return lines


def build_pdf_document(lines: List[str]) -> bytes:
    """Minimal deterministic PDF 1.4 writer (Helvetica, 11pt, multi-page)."""
    per_page = 48
    pages: List[List[str]] = [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]

    page_width, page_height = 612, 792
    margin_x, top_y, line_height = 72, 760, 14

    objects: List[bytes] = []

    def _stream(page_lines: List[str]) -> str:
        ops = []
        y = top_y
        for line in page_lines:
            ops.append(f"BT /F1 11 Tf 1 0 0 1 {margin_x} {y} Tm ({_escape_pdf_text(line)}) Tj ET")
            y -= line_height
        return "\n".join(ops)

    page_obj_ids = []
    content_obj_ids = []
    next_id = 3
    for _ in pages:
        page_obj_ids.append(next_id)
        content_obj_ids.append(next_id + 1)
        next_id += 2

    font_obj_id = next_id

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    objects.append(f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode())

    for idx, page_lines in enumerate(pages):
        stream = _stream(page_lines)
        stream_bytes = stream.encode("latin-1", "replace")
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width} {page_height}] "
                f"/Contents {content_obj_ids[idx]} 0 R /Resources << /Font << /F1 {font_obj_id} 0 R >> >> >>"
            ).encode()
        )
        objects.append(f"<< /Length {len(stream_bytes)} >>\nstream\n".encode() + stream_bytes + b"\nendstream")

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects):
        offsets.append(len(pdf))
        pdf += f"{i + 1} 0 obj\n".encode()
        pdf += obj
        pdf += b"\nendobj\n"

    xref_start = len(pdf)
    count = len(objects) + 1
    pdf += f"xref\n0 {count}\n".encode()
    pdf += b"0000000000 65535 f \n"
    for i in range(1, count):
        pdf += f"{offsets[i]:010d} 00000 n \n".encode()

    # No CreationDate/ModDate: fixed metadata keeps output reproducible.
    pdf += (
        f"trailer\n<< /Size {count} /Root 1 0 R /Info << /Producer ({PDF_PRODUCER}) >> >>\n"
        f"startxref\n{xref_start}\n%%EOF\n"
    ).encode()
    return bytes(pdf)


def generate_forensic_pdf_for_package(
    package_payload_json: str,
    evidence_hash: str,
    evidence_id: str,
    db,  # SQLAlchemy Session for verification lookups
) -> bytes:
    """Render the report PDF for one stored package.

    Pure function of the stored package payload + current ledger/anchor
    verification state. No frontend state involved.
    """
    payload = json.loads(package_payload_json)
    verification = EvidenceAnchorService(db).verify_evidence_package(evidence_id)
    lines = build_report_lines(payload, evidence_hash, verification)
    return build_pdf_document(lines)


def report_content_hash(pdf_bytes: bytes) -> str:
    """SHA-256 of a rendered PDF (used by tests to assert reproducibility)."""
    return hashlib.sha256(pdf_bytes).hexdigest()
