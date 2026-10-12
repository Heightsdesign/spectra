from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint("game IN ('pokemon')", name="ck_cards_game"),
        CheckConstraint("status IN ('registered')", name="ck_cards_status"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    game: Mapped[str] = mapped_column(String(32))
    card_name: Mapped[str] = mapped_column(String(200))
    set_name: Mapped[str] = mapped_column(String(200))
    collector_number: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(32), default="registered")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CardImage(Base):
    __tablename__ = "card_images"
    __table_args__ = (
        UniqueConstraint("card_id", "side", name="uq_card_images_card_side"),
        CheckConstraint("side IN ('front', 'back')", name="ck_card_images_side"),
        CheckConstraint("file_size > 0", name="ck_card_images_size"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    card_id: Mapped[UUID] = mapped_column(ForeignKey("cards.id"), index=True)
    side: Mapped[str] = mapped_column(String(5))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(32))
    sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int]
    storage_key: Mapped[str] = mapped_column(String(32), unique=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
