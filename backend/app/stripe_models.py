"""Stripe attempts are infrastructure for existing immutable obligations."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class StripeAttempt(Base):
    __tablename__ = "stripe_attempts"
    __table_args__ = (
        Index(
            "uq_stripe_active_attempt",
            "quote_id",
            unique=True,
            postgresql_where=text("status NOT IN ('expired', 'cancelled')"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_obligations.quote_id"), index=True
    )
    account_id: Mapped[str] = mapped_column(String(100))
    session_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    payment_intent_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="creating")
    checkout_url: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    return_origin: Mapped[str] = mapped_column(String(500))


class StripeEvidence(Base):
    __tablename__ = "stripe_evidence"
    event_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_obligations.quote_id"), index=True
    )
    kind: Mapped[str] = mapped_column(String(100))
    restricted: Mapped[bool] = mapped_column(default=False)
    data: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
