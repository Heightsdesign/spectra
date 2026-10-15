"""Physical custody is independent of declarations, commerce and grading."""
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, CheckConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class StaffMembership(Base):
    __tablename__ = 'staff_memberships'
    customer_id: Mapped[UUID] = mapped_column(ForeignKey('customers.id'), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    __table_args__ = (CheckConstraint("role IN ('admin','operator')", name='ck_staff_role'),)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Intake(Base):
    __tablename__ = 'submission_intakes'
    submission_id: Mapped[UUID] = mapped_column(ForeignKey('customer_submissions.id'), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default='awaiting_receipt')
    override_reason: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("status IN ('awaiting_receipt','partially_received','reconciliation_pending','reconciled','on_hold')", name='ck_intake_status'),)


class Parcel(Base):
    __tablename__ = 'intake_parcels'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey('customer_submissions.id'), index=True)
    received_by: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    request_key: Mapped[UUID]
    request_data: Mapped[dict] = mapped_column(JSONB)
    carrier: Mapped[str] = mapped_column(String(100), default='')
    tracking: Mapped[str] = mapped_column(String(200), default='')
    notes: Mapped[str] = mapped_column(String(2000), default='')
    status: Mapped[str] = mapped_column(String(32), default='received')
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint('submission_id','request_key'), CheckConstraint("status IN ('received','reconciling','reconciled')", name='ck_parcel_status'))


class PhysicalCard(Base):
    __tablename__ = 'physical_cards'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(40), unique=True)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey('customer_submissions.id'), index=True)
    parcel_id: Mapped[UUID] = mapped_column(ForeignKey('intake_parcels.id'), index=True)
    entry_id: Mapped[UUID | None] = mapped_column(ForeignKey('customer_submission_entries.id'))
    grading_card_id: Mapped[UUID | None] = mapped_column(ForeignKey('cards.id'), unique=True)
    received_by: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    request_key: Mapped[UUID]
    request_data: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default='unidentified')
    notes: Mapped[str] = mapped_column(String(2000), default='')
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (UniqueConstraint('submission_id','request_key'), CheckConstraint("status IN ('unidentified','matched','questionable')", name='ck_physical_status'))


class Discrepancy(Base):
    __tablename__ = 'intake_discrepancies'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey('customer_submissions.id'), index=True)
    card_id: Mapped[UUID | None] = mapped_column(ForeignKey('physical_cards.id'))
    entry_id: Mapped[UUID | None] = mapped_column(ForeignKey('customer_submission_entries.id'))
    kind: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[int] = mapped_column(default=1)
    notes: Mapped[str] = mapped_column(String(2000))
    status: Mapped[str] = mapped_column(String(16), default='open')
    resolution: Mapped[str | None] = mapped_column(String(2000))
    created_by: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    resolved_by: Mapped[UUID | None] = mapped_column(ForeignKey('customers.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("kind IN ('missing','unexpected','mismatch','damaged','unresolved')", name='ck_discrepancy_kind'), CheckConstraint("status IN ('open','resolved','acknowledged')", name='ck_discrepancy_status'), CheckConstraint('quantity BETWEEN 1 AND 10000', name='ck_discrepancy_quantity'))


class IntakeAudit(Base):
    __tablename__ = 'intake_audit_events'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID | None] = mapped_column(ForeignKey('customer_submissions.id'), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey('customers.id'))
    action: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[UUID]
    data: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
