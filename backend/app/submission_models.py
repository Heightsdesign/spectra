from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, String, CheckConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from app.database import Base

class Submission(Base):
    __tablename__ = 'customer_submissions'
    __table_args__ = (CheckConstraint('version >= 1', name='ck_submission_version'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey('customers.id'), index=True)
    status: Mapped[str] = mapped_column(String(32), default='draft')
    notes: Mapped[str] = mapped_column(String(2000), default='')
    version: Mapped[int] = mapped_column(default=1)
    pricing_revision: Mapped[int] = mapped_column(default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class SubmissionEntry(Base):
    __tablename__ = 'customer_submission_entries'
    __table_args__ = (CheckConstraint('quantity BETWEEN 1 AND 100', name='ck_entry_quantity'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey('customer_submissions.id', ondelete='CASCADE'), index=True)
    game: Mapped[str] = mapped_column(String(64))
    card_name: Mapped[str] = mapped_column(String(200))
    expansion: Mapped[str] = mapped_column(String(200))
    card_number: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(default=1)
    processing_tier: Mapped[str] = mapped_column(String(64), default="standard", server_default="standard")
    upgrade_ids: Mapped[list[str]] = mapped_column(JSONB, default=lambda: ["classic"], server_default='["classic"]')
    notes: Mapped[str] = mapped_column(String(2000), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
