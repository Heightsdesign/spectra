from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, String, CheckConstraint, Index, func, text
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


class SubmissionPhoto(Base):
    """Customer originals, separate from intake cards and inspection evidence."""
    __tablename__ = 'customer_submission_photos'
    __table_args__ = (
        CheckConstraint('(entry_id IS NOT NULL)::int + (customer_copy_id IS NOT NULL)::int = 1', name='ck_photo_parent'),
        Index('uq_library_photo_slot', 'customer_copy_id', 'side', unique=True, postgresql_where=text('removed_at IS NULL AND customer_copy_id IS NOT NULL')),
        CheckConstraint("side IN ('front', 'back')", name='ck_submission_photo_side'),
        CheckConstraint('copy_number BETWEEN 1 AND 100', name='ck_submission_photo_copy'),
        CheckConstraint('file_size > 0', name='ck_submission_photo_size'),
        Index('uq_submission_photo_active_slot', 'entry_id', 'copy_number', 'side', unique=True,
              postgresql_where=text('removed_at IS NULL')),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    entry_id: Mapped[UUID | None] = mapped_column(ForeignKey('customer_submission_entries.id', ondelete='CASCADE'), index=True)
    customer_copy_id: Mapped[UUID | None] = mapped_column(ForeignKey('customer_card_copies.id'))
    copy_number: Mapped[int]
    side: Mapped[str] = mapped_column(String(5))
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)

class SubmissionEntry(Base):
    __tablename__ = 'customer_submission_entries'
    __table_args__ = (CheckConstraint('quantity BETWEEN 1 AND 100', name='ck_entry_quantity'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey('customer_submissions.id', ondelete='CASCADE'), index=True)
    catalog_card_id: Mapped[UUID | None] = mapped_column(ForeignKey('tcg_cards.id'))
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
