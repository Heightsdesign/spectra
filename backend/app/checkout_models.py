"""Personal delivery data is separate from immutable card and quote records."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CustomerAddress(Base):
    __tablename__ = "customer_addresses"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    customer_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    recipient: Mapped[str] = mapped_column(String(200))
    line1: Mapped[str] = mapped_column(String(200))
    line2: Mapped[str] = mapped_column(String(200), default="")
    postal_code: Mapped[str] = mapped_column(String(32), default="")
    city: Mapped[str] = mapped_column(String(100))
    country: Mapped[str] = mapped_column(String(2))
    phone: Mapped[str] = mapped_column(String(32), default="")
    instructions: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubmissionDelivery(Base):
    __tablename__ = "submission_deliveries"
    submission_id: Mapped[UUID] = mapped_column(ForeignKey("customer_submissions.id", ondelete="CASCADE"), primary_key=True)
    address_id: Mapped[UUID | None] = mapped_column(ForeignKey("customer_addresses.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    declared_value_minor: Mapped[int | None] = mapped_column(Integer)
    service_id: Mapped[str | None] = mapped_column(String(64))
    parcel: Mapped[dict] = mapped_column(JSONB, default=dict)


class ShippingConfiguration(Base):
    __tablename__ = "shipping_configurations"
    version: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ShippingState(Base):
    __tablename__ = "shipping_state"
    id: Mapped[int] = mapped_column(primary_key=True)
    current_version: Mapped[UUID | None] = mapped_column(ForeignKey("shipping_configurations.version"))
