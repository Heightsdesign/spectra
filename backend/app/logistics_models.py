"""Additive C1 foundations, separate from financial and historical shipping tables."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LogisticsCatalog(Base):
    __tablename__ = 'logistics_catalogs'
    version: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document: Mapped[dict] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LogisticsPublication(Base):
    __tablename__ = 'logistics_catalog_publications'
    __table_args__ = (UniqueConstraint('catalog_version', 'sequence'),
                     CheckConstraint("status IN ('validated','published_test','withdrawn')", name='ck_logistics_publication_status'),
                     CheckConstraint('sequence > 0', name='ck_logistics_publication_sequence'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    catalog_version: Mapped[UUID] = mapped_column(ForeignKey('logistics_catalogs.version'), index=True)
    sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(32))
    actor_reference: Mapped[str] = mapped_column(String(500))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LogisticsState(Base):
    __tablename__ = 'logistics_state'
    __table_args__ = (CheckConstraint('id = 1', name='ck_logistics_state_singleton'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    current_version: Mapped[UUID | None] = mapped_column(ForeignKey('logistics_catalogs.version'))


class SubmissionLogisticsSelection(Base):
    __tablename__ = 'submission_logistics_selections'
    __table_args__ = (UniqueConstraint('submission_id', 'version'),
                     CheckConstraint('version > 0', name='ck_logistics_selection_version'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey('customer_submissions.id'), index=True)
    version: Mapped[int]
    catalog_version: Mapped[UUID | None] = mapped_column(ForeignKey('logistics_catalogs.version'))
    document: Mapped[dict] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
