"""Customer declarations of individual copies, not verified ownership or intake PCs."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomerCopy(Base):
    __tablename__ = "customer_card_copies"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"), index=True)
    catalog_card_id: Mapped[UUID | None] = mapped_column(ForeignKey("tcg_cards.id"))
    game: Mapped[str] = mapped_column(String(64))
    card_name: Mapped[str] = mapped_column(String(200))
    expansion: Mapped[str] = mapped_column(String(200), default="")
    card_number: Mapped[str] = mapped_column(String(64), default="")
    language: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(String(2000), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = (CheckConstraint("version >= 1", name="ck_copy_version"),)


class CopyAssignment(Base):
    __tablename__ = "customer_copy_assignments"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    copy_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_card_copies.id"), index=True
    )
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("customer_submissions.id"), index=True
    )
    entry_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("customer_submission_entries.id", ondelete="SET NULL"), unique=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[UUID | None] = mapped_column(ForeignKey("customers.id"))
    release_reason: Mapped[str | None] = mapped_column(String(1000))
    __table_args__ = (
        Index(
            "uq_copy_active_assignment",
            "copy_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
        ),
        CheckConstraint(
            "released_at IS NOT NULL OR entry_id IS NOT NULL",
            name="ck_copy_active_entry",
        ),
    )
