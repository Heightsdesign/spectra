"""Additive commercial foundations on existing submissions, quotes and PCs."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PaymentObligation(Base):
    __tablename__ = "payment_obligations"
    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("submission_quotes.id"), primary_key=True
    )
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_submissions.id"), index=True
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "amount_minor >= 0 AND currency = 'EUR'", name="ck_payment_amount"
        ),
    )


class VerifiedPayment(Base):
    __tablename__ = "verified_payments"
    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_obligations.quote_id"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    provider_event_id: Mapped[str] = mapped_column(String(200))
    provider_payment_id: Mapped[str] = mapped_column(String(200))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id"),
        UniqueConstraint("provider", "provider_payment_id"),
        CheckConstraint(
            "amount_minor >= 0 AND currency = 'EUR'", name="ck_verified_amount"
        ),
    )


class SupplementaryAcceptance(Base):
    __tablename__ = "supplementary_acceptances"
    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("submission_quotes.id"), primary_key=True
    )
    physical_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("physical_cards.id"), unique=True
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EntitlementAssignment(Base):
    __tablename__ = "commercial_entitlement_assignments"
    physical_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("physical_cards.id"), primary_key=True
    )
    quote_id: Mapped[UUID] = mapped_column(ForeignKey("payment_obligations.quote_id"))
    card_key: Mapped[str] = mapped_column(String(80))
    service_id: Mapped[str] = mapped_column(String(64))
    assigned_by: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (UniqueConstraint("quote_id", "card_key"),)


class DispatchExpectation(Base):
    __tablename__ = "dispatch_expectations"
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_submissions.id"), primary_key=True
    )
    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("verified_payments.quote_id"), unique=True
    )
    verified_payment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    dispatch_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        CheckConstraint(
            "dispatch_deadline = ((verified_payment_at AT TIME ZONE 'UTC') + interval '30 days') AT TIME ZONE 'UTC'",
            name="ck_dispatch_30_days",
        ),
    )


class ShipmentDeclaration(Base):
    __tablename__ = "customer_shipment_declarations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_submissions.id"), index=True
    )
    request_key: Mapped[UUID]
    declared_by: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    declared_dispatch_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    carrier: Mapped[str] = mapped_column(String(100))
    tracking: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (UniqueConstraint("submission_id", "request_key"),)


class CommercialEvent(Base):
    __tablename__ = "order_commercial_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_submissions.id"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"))
    kind: Mapped[str] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
