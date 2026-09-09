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
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.db.database import Base


class Session(Base):
    __tablename__ = "sessions"

    call_id = Column(String, primary_key=True)
    caller_id = Column(String, nullable=False)
    recipient_id = Column(String, nullable=False)
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
