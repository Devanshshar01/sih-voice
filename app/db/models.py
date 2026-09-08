"""
SQLAlchemy ORM models matching the audit schema in the SIH prototype
blueprint (sessions + risk_events). Only derived metadata is persisted --
raw audio is never written to disk, which is what keeps this layer
privacy-preserving by design.
"""
from sqlalchemy import (
    Column, String, Integer, Float, Text, DateTime, ForeignKey, CheckConstraint
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
