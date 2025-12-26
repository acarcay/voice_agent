"""
SQLAlchemy ORM Models for Voice Agent

Production-grade data models with:
- Async SQLAlchemy 2.0 support
- Proper indexing for query performance  
- Audit timestamps for all entities
- Type-safe enum for appointment status
"""

from datetime import datetime, date, time as time_type
from typing import List, Optional
import enum

from sqlalchemy import (
    Column, Integer, String, DateTime, Date, Time,
    Boolean, Text, ForeignKey, Enum, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all ORM models"""
    pass


class AppointmentStatus(enum.Enum):
    """Valid appointment statuses"""
    PENDING = "Beklemede"
    CONFIRMED = "Onaylandı"
    CANCELLED = "İptal Edildi"
    RESCHEDULED = "Ertelendi"
    COMPLETED = "Tamamlandı"


class Appointment(Base):
    """
    Appointment entity - represents a scheduled customer visit.
    
    Indexed on:
    - appointment_id (unique, primary lookup)
    - appointment_date (for daily batch queries)
    - status (for filtering pending appointments)
    """
    __tablename__ = "appointments"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Business key (external reference)
    appointment_id: Mapped[str] = mapped_column(
        String(50), 
        unique=True, 
        nullable=False,
        index=True
    )
    
    # Customer information
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Appointment details
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    appointment_time: Mapped[time_type] = mapped_column(Time, nullable=False)
    
    # Status tracking
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus),
        default=AppointmentStatus.PENDING,
        nullable=False
    )
    
    # Audit timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime, 
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime,
        onupdate=func.now(),
        nullable=True
    )
    
    # Relationships
    call_logs: Mapped[List["CallLog"]] = relationship(
        "CallLog",
        back_populates="appointment",
        cascade="all, delete-orphan"
    )
    status_changes: Mapped[List["AppointmentChange"]] = relationship(
        "AppointmentChange",
        back_populates="appointment",
        cascade="all, delete-orphan"
    )
    
    # Composite index for common query pattern
    __table_args__ = (
        Index('idx_appointment_date_status', 'appointment_date', 'status'),
    )
    
    def __repr__(self) -> str:
        return f"<Appointment(id={self.appointment_id}, customer={self.customer_name}, status={self.status.value})>"


class CallLog(Base):
    """
    Call attempt log - tracks every outbound call made by the agent.
    
    Records:
    - Which appointment the call was for
    - LiveKit room details
    - Call outcome (success/failure)
    - Duration and retry attempts
    """
    __tablename__ = "call_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key to appointment
    appointment_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # LiveKit room tracking
    room_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Call result
    call_status: Mapped[str] = mapped_column(
        String(20), 
        nullable=False
    )  # completed, failed, no_answer, busy
    
    call_duration: Mapped[int] = mapped_column(
        Integer, 
        default=0,
        nullable=False
    )  # seconds
    
    attempts: Mapped[int] = mapped_column(
        Integer, 
        default=1,
        nullable=False
    )
    
    success: Mapped[bool] = mapped_column(
        Boolean, 
        default=False,
        nullable=False
    )
    
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    appointment: Mapped["Appointment"] = relationship(
        "Appointment",
        back_populates="call_logs"
    )
    transcripts: Mapped[List["ConversationTranscript"]] = relationship(
        "ConversationTranscript",
        back_populates="call_log",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<CallLog(id={self.id}, room={self.room_name}, success={self.success})>"


class ConversationTranscript(Base):
    """
    Speech-to-text transcript storage.
    
    Stores each utterance from the conversation with:
    - Speaker identification (agent/customer)  
    - Timestamp for ordering
    - Full text content
    """
    __tablename__ = "conversation_transcripts"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key to call log
    call_log_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("call_logs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Speaker identification
    speaker: Mapped[str] = mapped_column(
        String(20),
        nullable=False
    )  # 'agent' or 'customer'
    
    # Transcript content
    text: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Timing
    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    call_log: Mapped["CallLog"] = relationship(
        "CallLog",
        back_populates="transcripts"
    )
    
    def __repr__(self) -> str:
        return f"<Transcript(speaker={self.speaker}, text={self.text[:30]}...)>"


class AppointmentChange(Base):
    """
    Audit trail for appointment status changes.
    
    Captures:
    - Who made the change (agent, customer, admin)
    - What changed (old → new status)
    - When it happened
    """
    __tablename__ = "appointment_changes"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign key to appointment
    appointment_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("appointments.appointment_id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Change details
    old_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    new_status: Mapped[str] = mapped_column(String(50), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Notes (optional, e.g., reschedule reason)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    appointment: Mapped["Appointment"] = relationship(
        "Appointment",
        back_populates="status_changes"
    )
    
    def __repr__(self) -> str:
        return f"<AppointmentChange({self.old_status} → {self.new_status} by {self.changed_by})>"
