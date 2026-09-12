"""
SQLAlchemy ORM models matching the audit schema in the SIH prototype
blueprint (sessions + risk_events). Only derived metadata is persisted --
raw audio is never written to disk, which is what keeps this layer
privacy-preserving by design.
"""
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Text,
    DateTime,
    ForeignKey,
    CheckConstraint,
    Boolean,
    LargeBinary,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class Session(Base):
    __tablename__ = "sessions"

    call_id = Column(String, primary_key=True)
    caller_id = Column(String, nullable=False)
    recipient_id = Column(String, nullable=False)
    # Owning tenant (from the API key that created the call) — BOLA defense.
    tenant_id = Column(String, nullable=False, default="default", server_default="default", index=True)
    start_time = Column(DateTime(timezone=True), server_default=func.now())
    end_time = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="ACTIVE")
    max_risk_score = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','COMPLETED','TERMINATED_RISK')",
            name="ck_session_status",
        ),
    )

    risk_events = relationship(
        "RiskEvent", back_populates="session", cascade="all, delete-orphan"
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    call_id = Column(String, ForeignKey("sessions.call_id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    acoustic_score = Column(Float, nullable=False)
    intent_score = Column(Float, nullable=False)
    combined_risk_score = Column(Integer, nullable=False)
    triggered_rule = Column(Text, nullable=True)

    session = relationship("Session", back_populates="risk_events")


class SpeakerIdentity(Base):
    """A persistent, versioned speaker enrollment (ECAPA-TDNN).

    Privacy: only DERIVED embeddings and metadata are stored here — raw voice
    recordings are never persisted. The ``centroid_embedding`` column keeps
    the aggregated enrollment representation; per-sample embeddings live in
    ``SpeakerEnrollmentSample``.

    PostgreSQL/pgvector path: ``centroid_embedding`` and sample embeddings are
    float32 byte blobs (BYTEA on PostgreSQL). A later migration can add a
    ``vector(192)`` generated/managed column (or a separate pgvector table)
    without touching any other schema contract — the byte layout is exactly
    what pgvector's binary format expects, so ``pgvector`` adoption is a
    schema addition, not a data rewrite.
    """

    __tablename__ = "speaker_identities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Logical identity: (tenant_id, speaker_id) is unique.
    speaker_id = Column(String, nullable=False)
    tenant_id = Column(String, nullable=False, default="default")
    display_name = Column(String, nullable=True)

    # Provenance of the stored representation — every embedding knows exactly
    # which encoder, version, and normalization produced it.
    model_identifier = Column(String, nullable=False)   # e.g. speechbrain/spkrec-ecapa-voxceleb
    model_version = Column(String, nullable=False)      # e.g. ecapa-voxceleb-v1
    normalization = Column(String, nullable=False)      # e.g. l2
    embedding_dimension = Column(Integer, nullable=False)

    # Aggregated enrollment representation (float32 bytes, L2-normalized).
    centroid_embedding = Column(LargeBinary, nullable=False)
    enrollment_sample_count = Column(Integer, nullable=False, default=1)
    # Bumped every time the enrollment representation changes.
    enrollment_version = Column(Integer, nullable=False, default=1)

    # Soft delete / revocation support (privacy: reversible deletion keeps an
    # audit trail; the embedding remains but the identity is never matched).
    is_active = Column(Boolean, nullable=False, default=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    samples = relationship(
        "SpeakerEnrollmentSample",
        back_populates="identity",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        # SQLite/PostgreSQL-compatible composite uniqueness (partial-unique
        # semantics for active rows are enforced in the vault layer, which
        # must respect soft-deleted rows when re-creating a speaker_id).
        Index("uq_speaker_identity", "tenant_id", "speaker_id", unique=True),
        Index("ix_speaker_identity_active", "is_active"),
    )


class SpeakerEnrollmentSample(Base):
    """One individual enrollment embedding (never raw audio)."""

    __tablename__ = "speaker_enrollment_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    identity_id = Column(
        Integer, ForeignKey("speaker_identities.id"), nullable=False
    )
    embedding = Column(LargeBinary, nullable=False)  # float32 bytes
    embedding_dimension = Column(Integer, nullable=False)
    model_version = Column(String, nullable=False)
    # Signal-quality metadata only (RMS/peak); never the waveform itself.
    rms = Column(Float, nullable=True)
    peak = Column(Float, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    identity = relationship("SpeakerIdentity", back_populates="samples")

    __table_args__ = (
        Index("ix_speaker_sample_identity", "identity_id", "is_active"),
    )


class EvidencePackage(Base):
    __tablename__ = "evidence_packages"

    evidence_id = Column(String, primary_key=True)
    evidence_hash = Column(String, nullable=False, unique=True)
    evidence_digest = Column(String, nullable=False)
    schema_version = Column(String, nullable=False, default="phase7-v1")
    package_format = Column(String, nullable=False, default="technical-integrity-evidence-package")
    package_payload = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, nullable=False, default="registered")
    local_chain_root = Column(String, nullable=True)
    local_chain_status = Column(String, nullable=False, default="pending")
    blockchain_network = Column(String, nullable=True)
    contract_address = Column(String, nullable=True)
    anchor_tx_hash = Column(String, nullable=True)
    anchor_block_number = Column(Integer, nullable=True)
    anchor_timestamp = Column(DateTime(timezone=True), nullable=True)
    anchor_status = Column(String, nullable=False, default="unavailable")
    failure_reason = Column(Text, nullable=True)

    ledger_records = relationship(
        "EvidenceLedgerRecord",
        back_populates="evidence_package",
        cascade="all, delete-orphan",
    )
    anchors = relationship(
        "EvidenceAnchor",
        back_populates="evidence_package",
        cascade="all, delete-orphan",
    )


class EvidenceLedgerRecord(Base):
    __tablename__ = "evidence_ledger_records"

    record_id = Column(Integer, primary_key=True, autoincrement=True)
    evidence_id = Column(String, ForeignKey("evidence_packages.evidence_id"), nullable=False)
    record_hash = Column(String, nullable=False)
    previous_record_hash = Column(String, nullable=False)
    # Verbatim timestamp string exactly as included in record_hash. Stored
    # alongside the parsed ``timestamp`` because SQLite (and some PostgreSQL
    # modes) normalize datetimes on round-trip — re-deriving the hashed
    # string from the parsed value breaks verification. See migrations 0002.
    timestamp_hashed = Column(String, nullable=False, default="")
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    schema_version = Column(String, nullable=False, default="phase7-v1")
    evidence_digest = Column(String, nullable=False)
    chain_root_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    evidence_package = relationship("EvidencePackage", back_populates="ledger_records")


class EvidenceAnchor(Base):
    __tablename__ = "evidence_anchors"

    anchor_id = Column(Integer, primary_key=True, autoincrement=True)
    evidence_id = Column(String, ForeignKey("evidence_packages.evidence_id"), nullable=False)
    root_hash = Column(String, nullable=False)
    blockchain_network = Column(String, nullable=False, default="polygon-amoy")
    contract_address = Column(String, nullable=True)
    tx_hash = Column(String, nullable=True)
    block_number = Column(Integer, nullable=True)
    anchor_timestamp = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="pending")
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    evidence_package = relationship("EvidencePackage", back_populates="anchors")
