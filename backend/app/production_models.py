"""Cross-registry ownership, independent of backend grading UUIDs."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProductionOrder(Base):
    __tablename__ = "production_orders"
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_submissions.id"), primary_key=True
    )
    registry_id: Mapped[UUID]
    mode: Mapped[str] = mapped_column(String(8))
    local_order_id: Mapped[str | None] = mapped_column(String(40))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint("mode IN ('create','adopt')"),
        CheckConstraint("local_order_id ~ '^ORD-[0-9]{6,}$'"),
        CheckConstraint("length(trim(reason)) > 0"),
        UniqueConstraint("registry_id", "local_order_id"),
        UniqueConstraint("submission_id", "registry_id"),
    )


class ProductionCard(Base):
    __tablename__ = "production_cards"
    physical_card_id: Mapped[UUID] = mapped_column(primary_key=True)
    submission_id: Mapped[UUID]
    registry_id: Mapped[UUID]
    local_card_id: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        CheckConstraint("local_card_id ~ '^SLB-C-[0-9]{6,}$'"),
        ForeignKeyConstraint(
            ["submission_id", "registry_id"],
            ["production_orders.submission_id", "production_orders.registry_id"],
        ),
        ForeignKeyConstraint(
            ["physical_card_id", "submission_id"],
            ["physical_cards.id", "physical_cards.submission_id"],
        ),
        UniqueConstraint("registry_id", "local_card_id"),
    )
