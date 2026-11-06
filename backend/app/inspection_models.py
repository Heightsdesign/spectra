from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, String, CheckConstraint, UniqueConstraint, Index, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Inspection(Base):
    __tablename__ = 'inspections'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    physical_card_id: Mapped[UUID] = mapped_column(ForeignKey('physical_cards.id'), unique=True)
    started_by: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    status: Mapped[str] = mapped_column(String(20), default='in_progress')
    location: Mapped[str] = mapped_column(String(40), default='inspection_workstation')
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    transitioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("status IN ('in_progress','paused')", name='ck_inspection_status'),
        CheckConstraint("(status = 'in_progress' AND location = 'inspection_workstation') OR (status = 'paused' AND location = 'inspection_hold_storage')", name='ck_inspection_location'),
        CheckConstraint('version > 0', name='ck_inspection_version'),
    )

class CustodyEvent(Base):
    __tablename__ = 'inspection_custody_events'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    inspection_id: Mapped[UUID] = mapped_column(ForeignKey('inspections.id'), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    request_key: Mapped[UUID]
    action: Mapped[str] = mapped_column(String(16))
    previous_state: Mapped[str] = mapped_column(String(20))
    new_state: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(40))
    destination: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint('inspection_id', 'request_key'),
        Index('ix_inspection_custody_history', 'inspection_id', 'created_at', 'id'),
        CheckConstraint("(action = 'start' AND previous_state = 'not_started' AND new_state = 'in_progress' AND source = 'secure_intake_storage' AND destination = 'inspection_workstation') OR (action = 'pause' AND previous_state = 'in_progress' AND new_state = 'paused' AND source = 'inspection_workstation' AND destination = 'inspection_hold_storage') OR (action = 'resume' AND previous_state = 'paused' AND new_state = 'in_progress' AND source = 'inspection_hold_storage' AND destination = 'inspection_workstation')", name='ck_custody_transition'),
    )

class InspectionImage(Base):
    __tablename__ = 'inspection_images'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    inspection_id: Mapped[UUID] = mapped_column(ForeignKey('inspections.id'), index=True)
    side: Mapped[str] = mapped_column(String(5))
    version: Mapped[int]
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    reason: Mapped[str] = mapped_column(String(1000))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('inspection_id','side','version'), CheckConstraint("side IN ('front','back')", name='ck_inspection_image_side'), CheckConstraint('version > 0 AND file_size > 0', name='ck_inspection_image_size'))
