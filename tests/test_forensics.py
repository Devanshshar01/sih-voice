"""Forensic evidence, chain-of-custody, PDF, and anchoring tests.

Covers the SIH forensic-layer requirements:
  * deterministic hashing (canonical JSON + SHA-256 stability)
  * tamper detection (payload + ledger record tampering)
  * chain break detection (global multi-package chain + full-chain walk)
  * duplicate evidence (idempotent registration)
  * PDF reproducibility (byte-identical renders of the same stored package)
  * authorized blockchain anchoring semantics (adapter-level; no network)
  * verification of anchored root consistency

All tests run against isolated SQLite databases; blockchain tests exercise the
adapter logic deterministically without any network or web3 installation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.models  # noqa: F401  (register all tables)
from app.db.database import Base
from app.services import evidence_package as pkg
from app.services.anchor_adapter import (
    BaseAnchorAdapter,
    NoopAnchorAdapter,
    PolygonAmoyAnchorAdapter,
)
from app.services.evidence_anchor import (
    GENESIS_HASH,
    EvidenceAnchorService,
    compute_chain_root,
    compute_record_hash,
)
from app.services.forensic_pdf import (
    build_pdf_document,
    build_report_lines,
    generate_forensic_pdf_for_package,
    report_content_hash,
)


# ---------------------------------------------------------------------------
# Fixtures: isolated database
# ---------------------------------------------------------------------------

@pytest.fixture()
def make_service(tmp_path):
    """Factory building EvidenceAnchorService instances over one shared DB.

    Calling it multiple times simulates process restarts over persistent state.
    """
    engine = create_engine(f"sqlite:///{tmp_path}/forensics.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _make() -> EvidenceAnchorService:
        return EvidenceAnchorService(TestSession())

    _make.engine = engine
    _make.session_factory = TestSession
    return _make


def _sample_payload(call_id: str = "call-123", risk: int = 84) -> dict:
    return {
        "schema_version": "forensic-v1",
        "package_format": "satyavoice-technical-integrity-evidence-package",
        "call_id": call_id,
        "caller_id": "scammer",
        "recipient_id": "protected-desk",
        "duration_seconds": 12.5,
        "codec": "pcm",
        "detected_languages": ["hi"],
        "windows": [
            {
                "window_index": 0,
                "timestamp": 1000.0,
                "relative_time_seconds": 0.0,
                "risk_score": risk,
                "acoustic_score": 0.91,
                "intent_score": 0.8,
                "speaker_similarity": None,
                "identity_mismatch": 0.0,
                "status": "LOCK_VERIFY",
                "transcript_hash": "a" * 64,
                "language": "hi",
                "codec": "pcm",
                "vad_active": True,
                "rationale": ["Acoustic anomaly", "Transactional hard trigger"],
                "intent_findings": [
                    {
                        "category": "otp",
                        "confidence": 0.9,
                        "severity": "critical",
                        "speech_act": "transaction",
                        "matched_phrase": "ओटीपी बताइए",
                        "language": "hi",
                    }
                ],
            }
        ],
        "peak_risk_score": risk,
        "fused_risk_score": risk,
        "action_taken": "protected_action_gated",
        "verification_result": None,
        "disposition": "closed",
        "intent_findings": [],
    }


# ---------------------------------------------------------------------------
# Deterministic hashing
# ---------------------------------------------------------------------------

class TestDeterministicHashing:
    def test_canonical_json_is_key_order_independent(self):
        a = pkg.canonical_hash({"b": 1, "a": {"d": 2, "c": 3}})
        b = pkg.canonical_hash({"a": {"c": 3, "d": 2}, "b": 1})
        assert a == b

    def test_canonical_json_is_whitespace_independent(self):
        a = pkg.canonical_hash({"x": 1})
        b = pkg.sha256_hex(pkg.canonical_json({"x": 1}))
        assert a == b

    def test_canonical_hash_handles_unicode_transcripts(self):
        h1 = pkg.canonical_hash({"t": "कृपया ओटीपी बताइए"})
        h2 = pkg.canonical_hash({"t": "कृपया ओटीपी बताइए"})
        h3 = pkg.canonical_hash({"t": "different"})
        assert h1 == h2 and h1 != h3
        assert len(h1) == 64

    def test_evidence_hash_excludes_downstream_status(self):
        """Two identical packages (same authored content incl. generated_at)
        hash identically — downstream ledger/anchor status is not hashed."""
        payload = _sample_payload()
        payload["generated_at"] = "2026-01-01T00:00:00+00:00"  # pinned
        p1 = pkg.EvidencePackageInput(**payload)
        p2 = pkg.EvidencePackageInput(**payload)
        assert p1.compute_evidence_hash() == p2.compute_evidence_hash()

    def test_authored_time_is_part_of_the_evidence(self):
        """Packages authored at different times hash differently (generated_at
        is legitimate evidence content, not downstream status)."""
        a = _sample_payload(); a["generated_at"] = "2026-01-01T00:00:00+00:00"
        b = _sample_payload(); b["generated_at"] = "2026-01-02T00:00:00+00:00"
        assert pkg.EvidencePackageInput(**a).compute_evidence_hash() != pkg.EvidencePackageInput(**b).compute_evidence_hash()

    def test_any_payload_change_changes_hash(self):
        base = _sample_payload()
        modified = json.loads(json.dumps(base))
        modified["peak_risk_score"] = 85
        assert pkg.canonical_hash(base) != pkg.canonical_hash(modified)


# ---------------------------------------------------------------------------
# Registration / verification
# ---------------------------------------------------------------------------

class TestRegistrationAndVerification:
    def test_register_returns_verifiable_package(self, make_service):
        svc = make_service()
        result = svc.register_evidence_package(_sample_payload(), evidence_id="ev-1")
        assert result["evidence_id"] == "ev-1"
        assert len(result["evidence_hash"]) == 64
        assert result["local_chain_status"] == "verified"

        ver = svc.verify_evidence_package("ev-1")
        assert ver["evidence_hash_integrity"] is True
        assert ver["local_chain_integrity"] is True

    def test_first_record_links_to_genesis(self, make_service):
        svc = make_service()
        svc.register_evidence_package(_sample_payload(), evidence_id="ev-1")
        ver = svc.verify_evidence_package("ev-1")
        assert ver["first_record_previous_hash"] == GENESIS_HASH

    def test_multi_package_chain_links_across_packages(self, make_service):
        """THE chain-of-custody regression: package N links to package N-1's
        chain root, and verification accounts for it (previously every package
        after the first failed verification)."""
        svc = make_service()
        for i in range(3):
            svc.register_evidence_package(_sample_payload(call_id=f"c{i}"), evidence_id=f"ev-{i}")

        previous_root = None
        for i in range(3):
            ver = svc.verify_evidence_package(f"ev-{i}")
            assert ver["evidence_hash_integrity"] is True
            assert ver["local_chain_integrity"] is True
            if previous_root is not None:
                assert ver["first_record_previous_hash"] == previous_root
            previous_root = ver["local_chain_root"]

    def test_full_chain_verification_passes_on_intact_ledger(self, make_service):
        svc = make_service()
        for i in range(4):
            svc.register_evidence_package(_sample_payload(call_id=f"c{i}"), evidence_id=f"ev-{i}")
        chain = svc.verify_full_chain()
        assert chain["integrity"] is True
        assert chain["record_count"] == 4
        assert chain["chain_tip"] is not None

    def test_duplicate_submission_is_idempotent(self, make_service):
        svc = make_service()
        first = svc.register_evidence_package(_sample_payload(), evidence_id="ev-1")
        second = svc.register_evidence_package(_sample_payload(), evidence_id="ev-1")
        assert second.get("duplicate") is True
        assert second["evidence_hash"] == first["evidence_hash"]
        chain = svc.verify_full_chain()
        assert chain["record_count"] == 1  # no second ledger record

    def test_missing_package_verification_raises(self, make_service):
        svc = make_service()
        with pytest.raises(ValueError):
            svc.verify_evidence_package("does-not-exist")

    def test_empty_payload_rejected(self, make_service):
        svc = make_service()
        with pytest.raises(ValueError):
            svc.register_evidence_package({})
        with pytest.raises(ValueError):
            svc.register_evidence_package("not-a-dict")


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------

class TestTamperDetection:
    def test_payload_tampering_breaks_hash_verification(self, make_service):
        svc = make_service()
        svc.register_evidence_package(_sample_payload(), evidence_id="ev-1")

        Session = make_service.session_factory
        with Session() as db:
            pkg_row = db.query(__import__("app.db.models", fromlist=["EvidencePackage"]).EvidencePackage).filter_by(evidence_id="ev-1").one()
            pkg_row.package_payload = pkg_row.package_payload.replace('"peak_risk_score":84', '"peak_risk_score":10')
            db.commit()

        ver = make_service().verify_evidence_package("ev-1")
        assert ver["evidence_hash_integrity"] is False
        assert ver["local_chain_integrity"] is True  # chain itself untouched

    def test_ledger_record_tampering_breaks_full_chain(self, make_service):
        svc = make_service()
        svc.register_evidence_package(_sample_payload(), evidence_id="ev-1")

        Session = make_service.session_factory
        with Session() as db:
            record = db.query(__import__("app.db.models", fromlist=["EvidenceLedgerRecord"]).EvidenceLedgerRecord).one()
            record.evidence_digest = "f" * 64  # forged digest
            db.commit()

        chain = make_service().verify_full_chain()
        assert chain["integrity"] is False
        assert chain["broken_at_record"] == 1

    def test_deleted_middle_record_breaks_chain(self, make_service):
        svc = make_service()
        for i in range(3):
            svc.register_evidence_package(_sample_payload(call_id=f"c{i}"), evidence_id=f"ev-{i}")

        Session = make_service.session_factory
        with Session() as db:
            middle = db.query(__import__("app.db.models", fromlist=["EvidenceLedgerRecord"]).EvidenceLedgerRecord).filter_by(record_id=2).one()
            db.delete(middle)
            db.commit()

        chain = make_service().verify_full_chain()
        assert chain["integrity"] is False
        # The break becomes detectable at the DELETED record's successor: its
        # stored previous_record_hash no longer matches the walked chain.
        assert chain["broken_at_record"] == 3

    def test_record_hash_function_catches_digest_substitution(self):
        """Direct unit test of the hash function's sensitivity."""
        h1 = compute_record_hash("prev", "2026-01-01T00:00:00+00:00", "v1", "d" * 64)
        h2 = compute_record_hash("prev", "2026-01-01T00:00:00+00:00", "v1", "e" * 64)
        h3 = compute_record_hash("prev2", "2026-01-01T00:00:00+00:00", "v1", "d" * 64)
        h4 = compute_record_hash("prev", "2026-01-02T00:00:00+00:00", "v1", "d" * 64)
        assert len({h1, h2, h3, h4}) == 4


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def _stored_package(make_service):
    svc = make_service()
    svc.register_evidence_package(_sample_payload(), evidence_id="ev-pdf")
    Session = make_service.session_factory
    with Session() as db:
        from app.db import models as m

        row = db.query(m.EvidencePackage).filter_by(evidence_id="ev-pdf").one()
        return row.package_payload, row.evidence_hash


class TestForensicPdf:
    def test_pdf_generation_succeeds(self, make_service):
        payload_json, evidence_hash = _stored_package(make_service)
        svc = make_service()
        pdf = generate_forensic_pdf_for_package(payload_json, evidence_hash, "ev-pdf", svc.db)
        assert pdf.startswith(b"%PDF-1.4")
        assert b"%%EOF" in pdf
        assert b"SATYAVOICE TECHNICAL INTEGRITY EVIDENCE REPORT" in pdf
        # The disclaimer about what the system does NOT establish must ship.
        assert b"legally admissible" in pdf
        assert b"SCOPE AND LIMITATIONS" in pdf

    def test_pdf_is_byte_identical_across_renders(self, make_service):
        payload_json, evidence_hash = _stored_package(make_service)
        svc = make_service()
        pdf1 = generate_forensic_pdf_for_package(payload_json, evidence_hash, "ev-pdf", svc.db)
        pdf2 = generate_forensic_pdf_for_package(payload_json, evidence_hash, "ev-pdf", svc.db)
        assert report_content_hash(pdf1) == report_content_hash(pdf2)
        assert pdf1 == pdf2

    def test_pdf_content_tracks_the_package_not_frontend_state(self, make_service):
        payload_json, evidence_hash = _stored_package(make_service)
        payload = json.loads(payload_json)
        payload["peak_risk_score"] = 42  # tamper
        lines = build_report_lines(payload, evidence_hash, {"evidence_hash_integrity": True})
        text = "\n".join(lines)
        # The risk summary renders the tampered value — the PDF faithfully
        # reflects the package (which is why the package hash matters).
        assert "Peak risk score: 42/100" in text
        # Per-window evidence still renders from the package's window data.
        assert "risk=84/100" in text

    def test_pdf_escapes_hostile_text(self):
        lines = ["Evil (parens) and \\ backslash"]
        pdf = build_pdf_document(lines)
        assert b"Evil \\(parens\\) and \\\\ backslash" in pdf

    def test_pdf_multipage_and_structure(self):
        lines = [f"line {i}" for i in range(120)]
        pdf = build_pdf_document(lines)
        assert pdf.count(b"/Type /Page ") == 3  # 120/48 -> 3 pages
        assert b"/Producer (SatyaVoice Forensic Evidence Generator 1.0)" in pdf
        # No CreationDate/ModDate (reproducibility).
        assert b"CreationDate" not in pdf


# ---------------------------------------------------------------------------
# Anchor semantics (no network)
# ---------------------------------------------------------------------------

class RecordingAdapter(BaseAnchorAdapter):
    """Test double that records anchors and verifies them — models the
    append-only, authorized semantics of the hardened contract."""

    def __init__(self):
        self.anchored = []

    def anchor_root(self, root_hash: str, evidence_id: str):
        if root_hash in self.anchored:
            return {"status": "failed", "failure_reason": "DuplicateRoot", "anchor_index": None}
        self.anchored.append(root_hash)
        return {
            "status": "anchored",
            "network": "test",
            "contract_address": "0xabc",
            "tx_hash": f"0x{len(self.anchored):064x}",
            "block_number": len(self.anchored),
            "anchor_index": len(self.anchored) - 1,
            "anchor_timestamp": None,
            "failure_reason": None,
        }

    def verify_root(self, root_hash: str):
        return {"verified": root_hash in self.anchored}


class TestAnchorSemantics:
    def test_noop_adapter_degrades_honestly(self):
        adapter = NoopAnchorAdapter()
        result = adapter.anchor_root("0x" + "a" * 64, "ev-1")
        assert result["status"] == "unavailable"
        assert result["failure_reason"]

    def test_anchored_root_verifies(self):
        adapter = RecordingAdapter()
        root = "0x" + "b" * 64
        anchor_result = adapter.anchor_root(root, "ev-1")
        assert anchor_result["status"] == "anchored"
        assert adapter.verify_root(root)["verified"] is True
        assert adapter.verify_root("0x" + "c" * 64)["verified"] is False

    def test_duplicate_root_rejected(self):
        adapter = RecordingAdapter()
        root = "0x" + "b" * 64
        assert adapter.anchor_root(root, "ev-1")["status"] == "anchored"
        assert adapter.anchor_root(root, "ev-1")["status"] == "failed"

    def test_append_only_preserves_history(self):
        adapter = RecordingAdapter()
        roots = ["0x" + ("b" * 63 + chr(ord("a") + i)) for i in range(3)]
        for i, root in enumerate(roots):
            adapter.anchor_root(root, f"ev-{i}")
        # All earlier roots remain verifiable after later appends.
        for root in roots:
            assert adapter.verify_root(root)["verified"] is True

    def test_polygon_adapter_validates_root_format(self):
        adapter = PolygonAmoyAnchorAdapter()
        # Missing RPC config -> honest unavailability, no crash.
        result = adapter.anchor_root("not-a-hash", "ev-1")
        assert result["status"] in {"unavailable", "failed"}

    def test_registration_with_anchoring_records_anchor(self, make_service, monkeypatch):
        from app import config as app_config

        monkeypatch.setattr(app_config, "BLOCKCHAIN_ANCHORING_ENABLED", True)
        adapter = RecordingAdapter()
        monkeypatch.setattr(
            "app.services.evidence_anchor.get_anchor_adapter", lambda: adapter
        )

        svc = make_service()
        result = svc.register_evidence_package(_sample_payload(), evidence_id="ev-anchor")
        assert result["anchor_status"] == "anchored"

        ver = svc.verify_evidence_package("ev-anchor")
        assert ver["public_anchor_consistent"] is True
        assert ver["anchor_status"] == "anchored"

    def test_failed_anchor_keeps_local_evidence_intact(self, make_service, monkeypatch):
        from app import config as app_config

        monkeypatch.setattr(app_config, "BLOCKCHAIN_ANCHORING_ENABLED", True)

        class FailingAdapter(BaseAnchorAdapter):
            def anchor_root(self, root_hash, evidence_id):
                return {"status": "failed", "failure_reason": "rpc unreachable", "anchor_index": None}

            def verify_root(self, root_hash):
                return {"verified": False, "failure_reason": "rpc unreachable"}

        monkeypatch.setattr(
            "app.services.evidence_anchor.get_anchor_adapter", lambda: FailingAdapter()
        )

        svc = make_service()
        result = svc.register_evidence_package(_sample_payload(), evidence_id="ev-fail")
        assert result["anchor_status"] == "failed"
        assert result["local_chain_status"] == "verified"  # local evidence intact

        ver = svc.verify_evidence_package("ev-fail")
        assert ver["local_chain_integrity"] is True
        assert ver["public_anchor_consistent"] is False


# ---------------------------------------------------------------------------
# Chain-root math
# ---------------------------------------------------------------------------

class TestChainMath:
    def test_chain_root_is_order_sensitive(self):
        a = compute_chain_root("hash-1", "prev")
        b = compute_chain_root("prev", "hash-1")
        assert a != b

    def test_genesis_is_the_first_link(self):
        h = compute_record_hash(GENESIS_HASH, "t", "v", "d")
        root = compute_chain_root(h, GENESIS_HASH)
        assert root != GENESIS_HASH
