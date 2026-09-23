"""Forensic PDF report smoke tests (Phases 6-9).

The PDF is a forensic deliverable, not debug output, so these tests render the
real bytes with ``build_forensic_report_pdf`` and then *read the delivered file
back* with pypdf -- page count, extracted text, headings, hashes, forbidden
strings. A 200 response is never treated as proof that the PDF is correct.

Covered:
  - 5-page structure (cover / detection / integrity / anchor / verification)
  - required headings present on the correct pages
  - the exact evidence id, Merkle root and package hash appear in full
  - hashes are never truncated (the whole 64-hex digest is extractable)
  - forbidden strings ("null"/"None"/"NaN"/"Infinity"/"undefined") never appear
  - missing values render as an explicit fallback, never as "null"/"None"
  - NaN / Infinity never render
  - no empty cryptographic field is presented as valid
  - DRY_RUN is rendered SIMULATED, never as a confirmed anchor
  - the report never claims legal admissibility / tamper-proofness
  - identical frozen evidence -> identical logical content and identical hash
  - modified evidence -> different report hash
  - the QR payload is a deterministic, PII-free verification URL
  - the PDF file opens successfully and is a valid PDF
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-pdf-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.forensic_report import (  # noqa: E402
    FORBIDDEN_STRINGS,
    REPORT_FORMAT,
    build_forensic_report_pdf,
    build_verification_url,
    report_identifier,
    verification_api_path,
)

EVIDENCE_ID = "SV-PDF-SMOKE-0001"
SESSION_ID = "call-pdf-smoke-0001"

# Deterministic 64-hex fixtures so the "renders in full" assertion is exact.
PACKAGE_HASH = "a" * 64
MERKLE_ROOT = "b" * 64
LEDGER_HEAD = "c" * 64
TX_HASH = "0x" + "d" * 64

# Strings that must never leak into the deliverable.
#   "null"/"None" -> serialization leaks;  the rest are claimed capabilities.
STRING_LEAKS = ("null", "None", "NaN", "Infinity", "undefined")
LEGAL_CLAIMS = (
    "court admissible",
    "legally certified",
    "tamper-proof",
    "tamper proof",
    "legally immutable",
    "IT Act 65B",
    "BSA Section 63",
)


# ---------------------------------------------------------------------------
# Fixtures: a frozen evidence snapshot (never live queries)
# ---------------------------------------------------------------------------


def _verification(**overrides):
    """A frozen Merkle-service verification dict (shape of verify_merkle_package)."""
    data = {
        "evidence_id": EVIDENCE_ID,
        "session_id": SESSION_ID,
        "valid": True,
        "package_hash_integrity": True,
        "merkle_root_integrity": True,
        "items_all_verified": True,
        "on_chain_verified": False,
        "merkle_root": MERKLE_ROOT,
        "package_hash": PACKAGE_HASH,
        "leaf_count": 3,
        "leaf_names": ["acoustic_result", "audio_digest", "risk_stream"],
        "created_at": "2026-03-01T12:00:00+00:00",
        "completed_at": "2026-03-01T12:05:30+00:00",
        "schema_version": "phase10-v1",
        "detection": {
            "risk_score": 0.88,
            "risk_status": "LOCK_VERIFY",
            "model_score": 0.93,
            "model_status": "SYNTHETIC",
            "speaker_match": "NOT_MATCHED",
            "contextual": "urgency, otp_request",
            "confidence": 0.91,
        },
        "model_metadata": {
            "detector_mode": "remote",
            "model_id": "nii-yamagishilab/mms-300m-anti-deepfake",
            "model_version": "300m",
            "sample_rate": 16000,
            "window_config": "4.0 s window / 0.5 s hop",
        },
        "artifacts": [
            {
                "artifact_id": "audio_original",
                "role": "original_audio",
                "media_type": "audio/wav",
                "byte_length": 34,
                "sha256": "e" * 64,
            },
            {
                "artifact_id": "acoustic_result",
                "role": "inference_result",
                "media_type": "application/json",
                "byte_length": 128,
                "sha256": "f" * 64,
            },
        ],
        "anchor_status": "unavailable",
        "blockchain_network": None,
        "contract_address": None,
        "tx_hash": None,
        "block_number": None,
        "anchor_timestamp": None,
    }
    data.update(overrides)
    return data


def _integrity(**overrides):
    """A frozen EvidenceIntegritySummary-shaped dict."""
    data = {
        "evidence_id": EVIDENCE_ID,
        "schema_version": "phase10-v1",
        "package_sha256": PACKAGE_HASH,
        "merkle_root": MERKLE_ROOT,
        "ledger_head": LEDGER_HEAD,
        "ledger": {
            "valid": True,
            "entries_checked": 3,
            "first_invalid_sequence": None,
            "expected_hash": None,
            "actual_hash": None,
            "reason": None,
        },
        "report": {"sha256": None, "generated_at": None, "schema_version": None},
        "blockchain": {
            "status": "unavailable",
            "confirmed": False,
            "simulated": False,
            "network": None,
            "contract": None,
            "tx_hash": None,
            "block_number": None,
            "anchored_at": None,
            "note": None,
        },
    }
    data.update(overrides)
    return data


def _render(verification=None, integrity=None, **kwargs):
    return build_forensic_report_pdf(
        evidence_id=EVIDENCE_ID,
        verification=verification if verification is not None else _verification(),
        integrity=integrity if integrity is not None else _integrity(),
        session_id=SESSION_ID,
        **kwargs,
    )


def _pdf_pages(pdf_bytes: bytes) -> list[str]:
    """Extract the text of every page from the delivered PDF bytes."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    return [page.extract_text() or "" for page in reader.pages]


def _pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(_pdf_pages(pdf_bytes))


def _pdf_pages_raw(pdf_bytes: bytes):
    """The raw pypdf page objects (for resource/image inspection)."""
    from pypdf import PdfReader

    return list(PdfReader(io.BytesIO(pdf_bytes)).pages)


@pytest.fixture(scope="module")
def report_bytes() -> bytes:
    return _render()


# ---------------------------------------------------------------------------
# Phase 8 (visual/structural smoke): page count, headings, validity
# ---------------------------------------------------------------------------


def test_pdf_opens_successfully(report_bytes):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(report_bytes))
    assert report_bytes.startswith(b"%PDF-"), "not a PDF file"
    assert len(reader.pages) > 0
    assert report_bytes.rstrip().endswith(b"%%EOF")


def test_report_has_exactly_five_pages(report_bytes):
    from pypdf import PdfReader

    assert len(PdfReader(io.BytesIO(report_bytes)).pages) == 5


def test_every_page_has_content_and_no_blank_page(report_bytes):
    """A forensic deliverable must not contain an accidental blank page."""
    for index, text in enumerate(_pdf_pages(report_bytes), start=1):
        assert text.strip(), f"page {index} is blank"


def test_required_headings_appear_on_the_right_pages(report_bytes):
    pages = _pdf_pages(report_bytes)
    expected = {
        1: ["SATYAVOICE", "FORENSIC VOICE ANALYSIS REPORT", "Evidence ID", "Schema version"],
        2: ["DETECTION SUMMARY", "Anti-spoof model score", "Speaker verification"],
        3: ["INTEGRITY", "Canonical package SHA-256", "Merkle root", "Ledger head hash"],
        4: ["BLOCKCHAIN ANCHOR", "Status"],
        5: ["VERIFICATION", "Merkle root", "Package hash", "Evidence ID"],
    }
    for page_number, headings in expected.items():
        page_text = pages[page_number - 1]
        for heading in headings:
            assert heading in page_text, f"page {page_number} missing {heading!r}"


def test_footer_on_every_page_has_schema_version_report_id_and_page_numbers(report_bytes):
    for page_number, text in enumerate(_pdf_pages(report_bytes), start=1):
        assert "evidence schema version" in text
        assert "Report identifier" in text
        assert f"Page {page_number} of 5" in text
        assert report_identifier(EVIDENCE_ID) in text


def test_evidence_id_and_hashes_render_in_full(report_bytes):
    """Hashes must be complete, never ellipsized or clipped."""
    text = _pdf_text(report_bytes)
    assert EVIDENCE_ID in text
    for digest in (PACKAGE_HASH, MERKLE_ROOT, LEDGER_HEAD):
        assert digest in text.replace("\n", ""), "hash was truncated or wrapped mid-digest"


def test_no_forbidden_strings_anywhere(report_bytes):
    text = _pdf_text(report_bytes)
    for forbidden in STRING_LEAKS:
        assert not re.search(rf"\b{re.escape(forbidden)}\b", text), forbidden
    for forbidden in FORBIDDEN_STRINGS:
        assert forbidden not in text, forbidden



# ---------------------------------------------------------------------------
# Phase 7 (report hashing): deterministic content, non-circular hash
# ---------------------------------------------------------------------------


def test_identical_frozen_evidence_yields_identical_report_bytes():
    """Rendering twice from the same snapshot must be byte-identical.

    This is what makes ``report_sha256`` reproducible: an independent verifier
    re-rendering the same frozen snapshot must obtain the same digest.
    """
    first = _render()
    second = _render()
    assert first == second
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_pdf_metadata_carries_no_wallclock_timestamp():
    """``invariant=1`` pins reportlab's metadata date instead of stamping now()."""
    pdf = _render()
    assert b"/CreationDate (D:20000101000000+00'00')" in pdf
    assert b"/ModDate (D:20000101000000+00'00')" in pdf


def test_modified_evidence_changes_the_report_hash():
    ok = _render(verification=_verification(valid=False, merkle_root_integrity=False))
    assert hashlib.sha256(ok).hexdigest() != hashlib.sha256(_render()).hexdigest()


def test_report_never_contains_its_own_byte_hash():
    """Phase 7: no circular hashing — the PDF cannot carry its own digest."""
    pdf = _render()
    own = hashlib.sha256(pdf).hexdigest()
    text = _pdf_text(pdf).replace("\n", "")
    assert own not in text
    assert "report_sha256" not in _pdf_text(pdf)
    assert "Report SHA-256" not in _pdf_text(pdf)


def test_verification_page_links_to_the_verification_endpoint(report_bytes):
    """The verification page must expose the canonical API path verbatim."""
    page_text = _pdf_pages(report_bytes)[4].replace("\n", "")
    assert verification_api_path(EVIDENCE_ID) in page_text
    assert EVIDENCE_ID in page_text


def test_qr_is_present_with_a_caption(report_bytes):
    """The QR image must be embedded and captioned on the verification page."""
    assert any("/Image" in str(page.get("/Resources", "")) for page in _pdf_pages_raw(report_bytes))
    assert "Scan to verify" in _pdf_pages(report_bytes)[4]


def test_verification_url_contains_no_pii_and_carries_no_payload():
    url = build_verification_url(EVIDENCE_ID)
    assert EVIDENCE_ID in url
    for leaked in ("+91", "phone", "caller", "transcript", "token="):
        assert leaked not in url
    assert len(url) < 200, "QR payload must stay compact"


def test_report_format_is_versioned():
    assert REPORT_FORMAT == "satyavoice-forensic-report-v1"


# ---------------------------------------------------------------------------
# Missing / hostile values: never render as null/None/NaN, never look valid
# ---------------------------------------------------------------------------


def test_empty_snapshot_renders_explicit_fallbacks_not_nulls():
    pdf = build_forensic_report_pdf(evidence_id=EVIDENCE_ID, verification=None, integrity=None)
    text = _pdf_text(pdf)
    assert "Not available" in text
    for forbidden in STRING_LEAKS:
        assert not re.search(rf"\b{re.escape(forbidden)}\b", text), forbidden


@pytest.mark.parametrize("hostile", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_never_render(hostile):
    pdf = _render(verification=_verification(detection={"risk_score": hostile}))
    text = _pdf_text(pdf)
    for forbidden in STRING_LEAKS:
        assert not re.search(rf"\b{re.escape(forbidden)}\b", text), forbidden


def test_hostile_object_never_renders_a_repr():
    class Boom:
        def __repr__(self) -> str:  # pragma: no cover - must not be called
            raise AssertionError("raw object was rendered into the report")

    pdf = _render(verification=_verification(detection={"risk_status": Boom()}))
    assert "Boom" not in _pdf_text(pdf)
    assert "Not available" in _pdf_text(pdf)


def test_empty_cryptographic_fields_are_not_presented_as_valid():
    """A missing hash must read as NOT AVAILABLE, never as a verified digest."""
    pdf = _render(
        verification=_verification(
            merkle_root=None,
            package_hash=None,
            valid=None,
            package_hash_integrity=None,
            merkle_root_integrity=None,
        ),
        integrity=_integrity(package_sha256=None, merkle_root=None, ledger_head=None),
    )
    text = _pdf_text(pdf)
    assert "NOT AVAILABLE" in text
    assert "0" * 64 not in text.replace("\n", "")
    assert "UNVERIFIED" in text
    # No digest-shaped string may be invented for a missing hash.
    assert not re.search(r"\b[0-9a-f]{64}\b", text.replace("\n", ""))
    # The cover must not claim a verified state.
    assert "VERIFIED" not in _pdf_pages(pdf)[0].replace("UNVERIFIED", "")


def test_tampered_evidence_is_labelled_tampered():
    """``valid: False`` from the verifier must surface as TAMPERED."""
    pdf = _render(
        verification=_verification(
            valid=False, package_hash_integrity=False, merkle_root_integrity=False
        )
    )
    text = _pdf_text(pdf)
    assert "TAMPERED" in text


def test_no_raw_python_objects(report_bytes):
    text = _pdf_text(report_bytes)
    assert "<" not in text and "object at 0x" not in text
    assert "{" not in text and "}" not in text


def test_no_legal_admissibility_claim(report_bytes):
    text = _pdf_text(report_bytes).lower()
    for claim in LEGAL_CLAIMS:
        assert claim.lower() not in text, f"legal claim leaked: {claim}"


def test_report_states_cryptographically_verifiable_capability(report_bytes):
    assert "Cryptographically verifiable forensic evidence package" in _pdf_pages(report_bytes)[0]



# ---------------------------------------------------------------------------
# Phase 12: blockchain modes must never masquerade as one another
# ---------------------------------------------------------------------------


def _anchor_blockchain(status, **overrides):
    block = {
        "status": status,
        "confirmed": status == "anchored",
        "simulated": status == "dry_run",
        "network": None,
        "contract": None,
        "tx_hash": None,
        "block_number": None,
        "anchored_at": None,
        "note": None,
    }
    block.update(overrides)
    return block


def test_disabled_mode_reports_not_anchored_and_no_tx_hash():
    pdf = _render(integrity=_integrity(blockchain=_anchor_blockchain("unavailable")))
    text = _pdf_text(pdf)
    assert "DISABLED" in text
    assert "No transaction hash exists" in text
    assert TX_HASH not in text
    assert "CONFIRMED" not in text


def test_dry_run_is_rendered_simulated_never_confirmed():
    """A DRY_RUN simulated tx hash must never read as a real confirmation."""
    pdf = _render(
        integrity=_integrity(
            blockchain=_anchor_blockchain(
                "dry_run",
                simulated=True,
                tx_hash=TX_HASH,
                network="polygon-amoy",
                contract="0xSIMULATED-CONTRACT",
                note="SIMULATED anchor (BLOCKCHAIN_MODE=DRY_RUN)",
            )
        )
    )
    text = _pdf_text(pdf)
    assert "SIMULATED" in text
    assert "CONFIRMED" not in text
    assert "SUBMITTED" not in text


def test_confirmed_anchor_renders_all_chain_facts():
    pdf = _render(
        integrity=_integrity(
            blockchain=_anchor_blockchain(
                "anchored",
                confirmed=True,
                network="polygon-amoy",
                contract="0x" + "1" * 40,
                tx_hash=TX_HASH,
                block_number=12345678,
                anchored_at="2026-03-01T12:06:00+00:00",
            )
        )
    )
    text = _pdf_text(pdf)
    assert "CONFIRMED" in text
    assert "polygon-amoy" in text
    assert TX_HASH in text.replace("\n", "")
    assert "12345678" in text


def test_failed_anchor_stays_visibly_failed():
    pdf = _render(
        integrity=_integrity(
            blockchain=_anchor_blockchain("failed", note="Contract reverted")
        )
    )
    text = _pdf_text(pdf)
    assert "FAILED" in text
    assert "CONFIRMED" not in text


def test_unanchored_evidence_still_reports_a_valid_local_integrity():
    """Anchoring is optional: local verification must stand on its own."""
    pdf = _render(integrity=_integrity(blockchain=_anchor_blockchain("unavailable")))
    text = _pdf_text(pdf)
    assert "remains valid without a chain anchor" in text
    assert "VALID" in text


def test_no_tx_hash_is_ever_invented(report_bytes):
    """A 0x-prefixed 32-byte hash may only appear when anchoring confirmed."""
    text = _pdf_text(report_bytes).replace("\n", "")
    assert TX_HASH not in text
    assert not re.search(r"0x[0-9a-fA-F]{64}", text)


# ---------------------------------------------------------------------------
# Phase 7/9: render_and_register_report — the stored report hash
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def report_db(tmp_path_factory):
    """Isolated DB so the test never modifies the developer's local evidence."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import models  # noqa: F401 - registers all models
    from app.db.database import Base

    db_path = tmp_path_factory.mktemp("forensic-pdf") / "report.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_render_and_register_report_stores_the_actual_byte_hash(report_db):
    from app.db import models as db_models
    from app.services.forensic_report import render_and_register_report

    result = render_and_register_report(
        report_db,
        evidence_id=EVIDENCE_ID,
        verification=_verification(),
        integrity=_integrity(),
        session_id=SESSION_ID,
    )
    assert hashlib.sha256(result["pdf"]).hexdigest() == result["report_sha256"]
    assert result["page_count"] == 5

    row = (
        report_db.query(db_models.EvidenceReportRecord)
        .filter(db_models.EvidenceReportRecord.evidence_id == EVIDENCE_ID)
        .one()
    )
    assert row.report_sha256 == result["report_sha256"]
    assert row.page_count == 5
    assert row.schema_version == "phase10-v1"


def test_render_and_register_report_is_idempotent_per_evidence(report_db):
    """Re-rendering the same frozen snapshot must not create a second row."""
    from app.db import models as db_models
    from app.services.forensic_report import render_and_register_report

    first = render_and_register_report(
        report_db,
        evidence_id=EVIDENCE_ID,
        verification=_verification(),
        integrity=_integrity(),
        session_id=SESSION_ID,
    )
    second = render_and_register_report(
        report_db,
        evidence_id=EVIDENCE_ID,
        verification=_verification(),
        integrity=_integrity(),
        session_id=SESSION_ID,
    )
    assert first["report_sha256"] == second["report_sha256"]
    rows = (
        report_db.query(db_models.EvidenceReportRecord)
        .filter(db_models.EvidenceReportRecord.evidence_id == EVIDENCE_ID)
        .all()
    )
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Phase 8 — right-margin geometry regression


def test_no_glyph_run_overflows_the_right_margin(report_bytes):
    """Table colWidths must fit inside the A4 content box (Phase 8 defect).

    Both report tables once declared 500pt widths inside the 493.23pt frame
    (210mm A4 minus two 18mm margins), pushing page-3 artifact SHA-256 lines
    past the right margin (right=552.5 > 544.25). Every text run in the
    rendered fixture must now end at or before the right margin edge.
    """
    from reportlab.pdfbase.pdfmetrics import stringWidth

    from pypdf import PdfReader

    a4_width = 595.276
    right_limit = a4_width - 18 * 2.83465  # same margin the renderer uses
    reader = PdfReader(io.BytesIO(report_bytes))
    worst_by_page: list[tuple[int, float]] = []

    for number, page in enumerate(reader.pages, start=1):
        worst = 0.0

        def visitor(body, cm, tm, font_dict, font_size):
            nonlocal worst
            if not body or not body.strip():
                return
            name = (font_dict or {}).get("/BaseFont", "")
            if isinstance(name, bytes):
                name = name.decode("latin-1", "replace")
            family = "Courier" if "Courier" in name else "Helvetica"
            a1, _b1, c1, _d1, e1, _f1 = cm
            a2, _b2, c2, _d2, e2, f2 = tm
            x = a1 * e2 + c1 * f2 + e1
            worst = max(worst, x + stringWidth(body.rstrip("\n"), family, float(font_size or 0)))

        page.extract_text(visitor_text=visitor)
        worst_by_page.append((number, worst))
        # 0.5pt tolerance absorbs rounding in the visitor transform math.
        assert worst <= right_limit + 0.5, (
            f"page {number} overflows the right margin: "
            f"worst right={worst:.2f} > limit {right_limit:.2f}"
        )

    assert len(worst_by_page) == 5
    # The overflow this guards against was specifically on page 3 (artifact
    # table): a 500pt declaration put its hash column at right=552.5.
    page3_worst = dict(worst_by_page)[3]
    assert page3_worst <= right_limit + 0.5

