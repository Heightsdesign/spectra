"""Versioned catalogs and immutable quote/acceptance snapshots."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PricingCatalog(Base):
    __tablename__ = "pricing_catalogs"
    version: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PricingState(Base):
    __tablename__ = "pricing_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_pricing_state_singleton"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    current_version: Mapped[UUID | None] = mapped_column(ForeignKey("pricing_catalogs.version"))


class SubmissionQuote(Base):
    __tablename__ = "submission_quotes"
    __table_args__ = (CheckConstraint("expires_at > created_at", name="ck_quote_expiry"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("customer_submissions.id", ondelete="CASCADE"), index=True)
    pricing_revision: Mapped[int]
    catalog_version: Mapped[UUID] = mapped_column(ForeignKey("pricing_catalogs.version"))
    snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuoteAcceptance(Base):
    __tablename__ = "quote_acceptances"
    # One immutable commercial agreement per submission, separate from confirmation.
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("customer_submissions.id", ondelete="CASCADE"), primary_key=True)
    quote_id: Mapped[UUID] = mapped_column(ForeignKey("submission_quotes.id"), unique=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
