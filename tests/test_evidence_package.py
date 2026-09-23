"""Canonical evidence package + artifact hashing + integrity summary tests.

Enforces the determinism contract declared in
``app/services/evidence_package.py``:

  CANONICALIZATION
    - same semantic package -> exactly the same canonical bytes
    - reordered dictionary -> same bytes (RFC 8785 key ordering)
    - semantically different value -> different hash
    - NaN / Infinity rejected
    - timestamps normalized (timezone-aware, second precision)
    - Unicode is consistent and explicitly UTF-8

  ARTIFACTS
    - the hash covers the ACTUAL bytes (never a label)
    - byte_length is cross-checked against real content
    - one altered byte fails verification
    - altered metadata changes the package hash
    - a replaced artifact changes the Merkle root
    - artifact ordering does not change the root

  EVIDENCE PACKAGE / INTEGRITY SUMMARY
    - schema version is explicit
    - volatile fields are absent from the hashed representation
    - the hash identities stay distinct (never collapsed)
    - an unconfirmed/dry-run anchor never exposes a tx hash as real
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-evidence-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.merkle import compute_root, hash_leaf  # noqa: E402
from app.services.evidence_package import (  # noqa: E402
    EVIDENCE_PACKAGE_SCHEMA_VERSION,
    EvidencePackageError,
    build_artifact_metadata,
    build_canonical_evidence_package,
    build_integrity_summary,
    canonical_package_bytes,
    normalize_timestamp,
    package_sha256,
    verify_artifact,
    verify_package_hash,
)

CREATED = dt.datetime(2026, 3, 1, 12, 0, 0, tzinfo=dt.timezone.utc)

# ASCII-only, deterministic fixture values (the golden-vector contract).
FIXTURE_AUDIO = b"RIFF-satyavoice-golden-audio-bytes"

# Pinned golden vectors. Any change to the canonicalizer, the artifact hashing
# scheme, or the fixture shape changes these values -- which is exactly the
# point: an independent verifier must reproduce them byte for byte.
GOLDEN_CANONICAL_JSON = (
    '{"acoustic_evidence":{"model_id":"mms-300m-anti-deepfake","score":0.93},'
    '"audio_artifacts":{"original":{"artifact_id":"audio-original","byte_length":34,'
    '"created_at":"2026-03-01T12:00:00+00:00","media_type":"audio/wav",'
    '"role":"original_audio",'
    '"sha256":"db736882dc1f34ae241506c1e00acfea7fceac2751db799702c87c85cf911d24",'
    '"source":"webrtc-capture"}},'
    '"blockchain_metadata":{"status":"unavailable"},"call_id":"call-golden",'
    '"completed_at":"2026-03-01T12:05:30+00:00",'
    '"contextual_analysis":{"indicators":["urgency","otp_request"]},'
    '"created_at":"2026-03-01T12:00:00+00:00",'
    '"detection":{"final_status":"LOCK_VERIFY","max_risk_score":88},'
    '"evidence_id":"SV-GOLDEN-0001","ledger_metadata":{"sequence_numbers":[1,2]},'
    '"merkle_metadata":{"leaf_count":1,"tree_version":"merkle-v1"},'
    '"model_metadata":{"detector_mode":"mock","schema_version":"phase10-v1"},'
    '"risk_summary":{"fused_risk":0.88,"policy":"LOCK_VERIFY"},'
    '"schema_version":"sv-evidence-v1",'
    '"speaker_verification":{"confidence":0.41,"matched":false},'
    '"verification_metadata":{"policy":"recompute-server-side"}}'
)
GOLDEN_PACKAGE_SHA256 = "f4cf8b1578fd3ec5ebfcde150997262d4ffc6fd760f178ccc7384f6569f035ec"


@pytest.fixture(scope="module")
def db_session(tmp_path_factory):
    """Isolated per-module DB (never touches local production evidence)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import models  # noqa: F401 - registers all models
    from app.db.database import Base

    db_path = tmp_path_factory.mktemp("evidence-package") / "evidence.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _package(**overrides):
    """The canonical golden fixture package (all call sites share one shape)."""
    kwargs = {
        "evidence_id": "SV-GOLDEN-0001",
        "call_id": "call-golden",
        "created_at": CREATED,
        "completed_at": dt.datetime(2026, 3, 1, 12, 5, 30, tzinfo=dt.timezone.utc),
        "detection": {"final_status": "LOCK_VERIFY", "max_risk_score": 88},
        "acoustic_evidence": {"score": 0.93, "model_id": "mms-300m-anti-deepfake"},
        "speaker_verification": {"matched": False, "confidence": 0.41},
        "contextual_analysis": {"indicators": ["urgency", "otp_request"]},
        "risk_summary": {"fused_risk": 0.88, "policy": "LOCK_VERIFY"},
        "audio_artifacts": {
            "original": build_artifact_metadata(
                artifact_id="audio-original",
                role="original_audio",
                media_type="audio/wav",
                content=FIXTURE_AUDIO,
                created_at=CREATED,
                source="webrtc-capture",
            )
        },
        "model_metadata": {"detector_mode": "mock", "schema_version": "phase10-v1"},
        "ledger_metadata": {"sequence_numbers": [1, 2]},
        "merkle_metadata": {"tree_version": "merkle-v1", "leaf_count": 1},
        "blockchain_metadata": {"status": "unavailable"},
        "verification_metadata": {"policy": "recompute-server-side"},
    }
    kwargs.update(overrides)
    return build_canonical_evidence_package(**kwargs)


# ---------------------------------------------------------------------------
# CANONICALIZATION (Phase 1)
# ---------------------------------------------------------------------------


def test_canonical_bytes_are_deterministic():
    """The same semantic package always yields exactly the same bytes."""
    first = canonical_package_bytes(_package())
    second = canonical_package_bytes(_package())
    assert first == second
    assert isinstance(first, bytes)


def test_reordered_keys_produce_identical_bytes():
    """Key insertion order must not influence the canonical bytes."""
    forward = {"a": 1, "b": {"x": 1, "y": 2}, "c": [1, 2, 3]}
    reverse = {"c": [1, 2, 3], "b": {"y": 2, "x": 1}, "a": 1}
    assert canonical_package_bytes(forward) == canonical_package_bytes(reverse)


def test_semantically_different_value_changes_the_hash():
    """A different value inside the same shape must change the digest."""
    tampered = _package(
        detection={"final_status": "ALLOW", "max_risk_score": 88}
    )
    assert package_sha256(tampered) != package_sha256(_package())


def test_package_hash_is_domain_separated_from_a_bare_sha256():
    """The package digest must not be a bare sha256 of the canonical bytes."""
    pkg = _package()
    bare = hashlib.sha256(canonical_package_bytes(pkg)).hexdigest()
    assert package_sha256(pkg) != bare


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_are_rejected(bad):
    """NaN/Infinity can never be silently serialized into evidence."""
    with pytest.raises(EvidencePackageError):
        _package(detection={"score": bad})


def test_nan_nested_inside_a_list_is_rejected():
    with pytest.raises(EvidencePackageError):
        _package(contextual_analysis={"indicators": [1, float("nan")]})


def test_timestamps_are_normalized_to_utc_seconds():
    """Microseconds and non-UTC offsets collapse to one canonical form."""
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    aware = dt.datetime(2026, 3, 1, 17, 30, 0, 499999, tzinfo=ist)
    assert normalize_timestamp(aware) == "2026-03-01T12:00:00+00:00"


def test_naive_timestamps_are_treated_as_utc():
    """A naive datetime must hash identically to the equivalent UTC one."""
    naive = dt.datetime(2026, 3, 1, 12, 0, 0)
    assert normalize_timestamp(naive) == normalize_timestamp(CREATED)
    assert package_sha256(_package(created_at=naive)) == package_sha256(_package())


def test_sub_second_jitter_does_not_change_the_hash():
    """Two packages created in the same second must hash identically."""
    early = dt.datetime(2026, 3, 1, 12, 0, 0, 1, tzinfo=dt.timezone.utc)
    late = dt.datetime(2026, 3, 1, 12, 0, 0, 999999, tzinfo=dt.timezone.utc)
    assert package_sha256(_package(created_at=early)) == package_sha256(
        _package(created_at=late)
    )


def test_unsupported_timestamp_type_is_rejected():
    with pytest.raises(EvidencePackageError):
        normalize_timestamp(object())


def test_iso_string_timestamps_are_accepted_and_normalized():
    assert normalize_timestamp("2026-03-01T12:00:00+00:00") == "2026-03-01T12:00:00+00:00"
    assert normalize_timestamp("2026-03-01T17:30:00+05:30") == "2026-03-01T12:00:00+00:00"


def test_unicode_is_consistent_and_utf8_encoded():
    """Non-ASCII evidence must round-trip deterministically as explicit UTF-8."""
    word = "\u0938\u0924\u094d\u092f"  # Devanagari "satya"
    pkg = _package(contextual_analysis={"note": word})
    raw = canonical_package_bytes(pkg)
    assert word.encode("utf-8") in raw
    assert raw == canonical_package_bytes(_package(contextual_analysis={"note": word}))


def test_schema_version_is_explicit():
    assert EVIDENCE_PACKAGE_SCHEMA_VERSION == "sv-evidence-v1"
    assert _package()["schema_version"] == EVIDENCE_PACKAGE_SCHEMA_VERSION


def test_no_volatile_fields_in_the_hashed_representation():
    """Request ids / PDF timestamps / random UUIDs must never be injected."""
    import re

    canonical = canonical_package_bytes(_package()).decode("utf-8")
    for forbidden in ("request_id", "generated_at", "pdf_sha256", "receipt", "nonce"):
        assert forbidden not in canonical
    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", canonical
    )


def test_verify_package_hash_roundtrip_and_tamper():
    pkg = _package()
    assert verify_package_hash(pkg, package_sha256(pkg)) is True
    assert verify_package_hash(pkg, "0" * 64) is False


def test_golden_vector_bytes_and_package_hash():
    """Pin the golden vector: an independent verifier must reproduce it exactly."""
    assert canonical_package_bytes(_package()).decode("utf-8") == GOLDEN_CANONICAL_JSON
    assert package_sha256(_package()) == GOLDEN_PACKAGE_SHA256


# ---------------------------------------------------------------------------
# ARTIFACTS (Phase 2)
# ---------------------------------------------------------------------------


def _artifact(content: bytes = FIXTURE_AUDIO, **overrides):
    kwargs = {
        "artifact_id": "audio-original",
        "role": "original_audio",
        "media_type": "audio/wav",
        "content": content,
        "created_at": CREATED,
        "source": "unit-test",
    }
    kwargs.update(overrides)
    return build_artifact_metadata(**kwargs)


def test_artifact_hash_covers_the_actual_bytes():
    """The digest is over the real bytes and is domain-separated."""
    meta = _artifact()
    assert verify_artifact(meta, FIXTURE_AUDIO) is True
    # Domain separation: not a bare sha256 of the content.
    assert meta["sha256"] != hashlib.sha256(FIXTURE_AUDIO).hexdigest()


def test_artifact_byte_length_matches_content():
    assert _artifact()["byte_length"] == len(FIXTURE_AUDIO)


def test_artifact_metadata_shape_is_complete():
    meta = _artifact()
    for key in (
        "artifact_id",
        "role",
        "media_type",
        "byte_length",
        "sha256",
        "created_at",
        "source",
    ):
        assert key in meta
    assert meta["created_at"] == "2026-03-01T12:00:00+00:00"


def test_artifact_sequence_is_recorded_when_given():
    assert _artifact(sequence=3)["sequence"] == 3
    assert "sequence" not in _artifact()  # omitted, never serialized as null


def test_one_altered_byte_fails_artifact_verification():
    meta = _artifact()
    tampered = bytearray(FIXTURE_AUDIO)
    tampered[5] ^= 0x01  # flip exactly one bit
    assert verify_artifact(meta, bytes(tampered)) is False


def test_artifact_verification_rejects_wrong_length():
    assert verify_artifact(_artifact(), FIXTURE_AUDIO + b"x") is False


def test_non_bytes_artifact_content_is_rejected():
    with pytest.raises(EvidencePackageError):
        _artifact(content="not bytes")  # type: ignore[arg-type]


def test_altering_metadata_changes_the_package_hash():
    """Modified artifact metadata must invalidate the package hash."""
    original = _package()
    tampered_artifact = dict(original["audio_artifacts"]["original"])
    tampered_artifact["sha256"] = "f" * 64
    tampered = _package(audio_artifacts={"original": tampered_artifact})
    assert package_sha256(tampered) != package_sha256(original)


def test_replacing_an_artifact_changes_the_merkle_root():
    """A different artifact set must produce a different Merkle root."""

    def root_for(content: bytes) -> bytes:
        meta = _artifact(content)
        return compute_root([hash_leaf(bytes.fromhex(meta["sha256"]))])

    assert root_for(FIXTURE_AUDIO) != root_for(b"different audio entirely")


def test_artifact_order_does_not_change_the_root():
    """The tree sorts its leaves, so artifact order is not part of the root."""
    digests = [
        _artifact(content, artifact_id=name)["sha256"]
        for name, content in (("w1", b"one"), ("w2", b"two"), ("w3", b"three"))
    ]
    leaves = [hash_leaf(bytes.fromhex(digest)) for digest in digests]
    assert compute_root(leaves) == compute_root(list(reversed(leaves)))


# ---------------------------------------------------------------------------
# EVIDENCE PACKAGE / INTEGRITY SUMMARY (Phase 5)
# ---------------------------------------------------------------------------


def test_integrity_summary_requires_a_stored_merkle_package(db_session):
    from app.services.merkle_evidence import MerkleEvidenceError

    with pytest.raises(MerkleEvidenceError):
        build_integrity_summary(db_session, "SV-DOES-NOT-EXIST")


def test_integrity_summary_keeps_hash_identities_distinct(db_session):
    from app.services.merkle_evidence import MerkleEvidenceService

    evidence_id = "SV-SUMMARY-0001"
    MerkleEvidenceService(db_session).register_merkle_package(
        evidence_id=evidence_id,
        items={"audio": b"summary-audio", "transcript": b"summary transcript"},
        anchor=False,
    )
    summary = build_integrity_summary(db_session, evidence_id)

    assert summary["evidence_id"] == evidence_id
    assert summary["schema_version"] == "phase10-v1"
    assert summary["package_sha256"]
    assert summary["merkle_root"]
    # Distinct identities: the package hash is NOT the Merkle root.
    assert summary["package_sha256"] != summary["merkle_root"]
    for key in ("package_sha256", "merkle_root", "ledger_head", "ledger", "report", "blockchain"):
        assert key in summary
    assert summary["report"]["sha256"] is None  # no PDF rendered yet
    assert "tx_hash" not in summary  # tx hash lives under blockchain, never top-level


def test_integrity_summary_hides_tx_hash_until_confirmed(db_session):
    """An unanchored package must never report a transaction hash."""
    from app.services.merkle_evidence import MerkleEvidenceService

    evidence_id = "SV-SUMMARY-0002"
    MerkleEvidenceService(db_session).register_merkle_package(
        evidence_id=evidence_id,
        items={"audio": b"summary-audio-2"},
        anchor=False,
    )
    summary = build_integrity_summary(db_session, evidence_id)
    assert summary["blockchain"]["status"] == "unavailable"
    assert summary["blockchain"]["confirmed"] is False
    assert summary["blockchain"]["tx_hash"] is None
    assert summary["blockchain"]["block_number"] is None


def test_integrity_summary_is_derived_from_stored_rows_only(db_session):
    """No freshly generated timestamps: repeated reads must be identical."""
    from app.services.merkle_evidence import MerkleEvidenceService

    evidence_id = "SV-SUMMARY-0003"
    MerkleEvidenceService(db_session).register_merkle_package(
        evidence_id=evidence_id,
        items={"audio": b"summary-audio-3"},
        anchor=False,
    )
    assert build_integrity_summary(db_session, evidence_id) == build_integrity_summary(
        db_session, evidence_id
    )



# ---------------------------------------------------------------------------
# MERKLE METADATA (Phase 4)
# ---------------------------------------------------------------------------


def test_integrity_summary_exposes_complete_merkle_metadata(db_session):
    """Phase 4 requires tree_version / leaf_count / leaf_order_rule / root /
    generated_at / evidence_id — all present and self-consistent."""
    from app.services.evidence_package import build_integrity_summary
    from app.services.merkle_evidence import (
        LEAF_ORDER_RULE,
        TREE_VERSION,
        MerkleEvidenceService,
    )

    evidence_id = "SV-MERKLE-META-0001"
    MerkleEvidenceService(db_session).register_merkle_package(
        evidence_id=evidence_id,
        items={"audio": b"meta-audio", "transcript": "meta transcript"},
        anchor=False,
    )
    merkle = build_integrity_summary(db_session, evidence_id)["merkle"]

    assert merkle["tree_version"] == TREE_VERSION
    assert merkle["leaf_order_rule"] == LEAF_ORDER_RULE
    assert merkle["leaf_count"] == 2
    assert len(merkle["root"]) == 64
    assert merkle["evidence_id"] == evidence_id
    assert merkle["generated_at"]  # derived from the stored row, never "now()"


def test_merkle_metadata_is_derived_not_stored(db_session):
    """tree_version / leaf_order_rule come from module constants.

    A stored copy could be tampered with; a constant cannot. Verified by
    checking the values are exactly the code constants and that they match on
    ``verify_merkle_package`` too.
    """
    from app.services.evidence_package import build_integrity_summary
    from app.services.merkle_evidence import (
        LEAF_ORDER_RULE,
        TREE_VERSION,
        MerkleEvidenceService,
    )

    evidence_id = "SV-MERKLE-META-0002"
    service = MerkleEvidenceService(db_session)
    service.register_merkle_package(
        evidence_id=evidence_id, items={"audio": b"meta-audio-2"}, anchor=False
    )

    verification = service.verify_merkle_package(evidence_id, verify_on_chain=False)
    integrity = build_integrity_summary(db_session, evidence_id)

    assert verification["tree_version"] == TREE_VERSION
    assert verification["leaf_order_rule"] == LEAF_ORDER_RULE
    assert integrity["merkle"]["tree_version"] == verification["tree_version"]
    assert integrity["merkle"]["leaf_order_rule"] == verification["leaf_order_rule"]
    # The reported root is the stored one, and the metadata block never
    # introduces a second, competing root field.
    assert integrity["merkle"]["root"] == verification["merkle_root"]

