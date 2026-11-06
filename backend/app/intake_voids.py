"""Historical registrations are retained; a void is an immutable lifecycle fact."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, exists, func, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.intake_models import Discrepancy, IntakeAudit, PhysicalCard


class PhysicalCardVoid(Base):
    __tablename__ = "physical_card_voids"
    physical_card_id: Mapped[UUID] = mapped_column(
        ForeignKey("physical_cards.id"), primary_key=True
    )
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("customers.id"))
    reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def active_card():
    return ~exists().where(PhysicalCardVoid.physical_card_id == PhysicalCard.id)


def void_blockers(db, card, state):
    from app.inspection_models import Inspection
    from app.production_models import ProductionCard, ProductionOrder

    reasons = []
    if state != "reconciliation_pending":
        return ["begin_reconciliation_required"]
    if card.entry_id is not None or card.status != "unidentified":
        return ["card_not_unidentified"]
    if card.grading_card_id is not None:
        reasons.append("grading_link_exists")
    if db.get(ProductionOrder, card.submission_id) or db.get(ProductionCard, card.id):
        reasons.append("production_link_exists")
    if db.scalar(select(Inspection.id).where(Inspection.physical_card_id == card.id)):
        reasons.append("inspection_link_exists")
    if db.scalar(select(Discrepancy.id).where(Discrepancy.card_id == card.id)):
        reasons.append("discrepancy_history_exists")
    if db.scalar(
        select(IntakeAudit.id)
        .where(
            IntakeAudit.submission_id == card.submission_id,
            IntakeAudit.action != "physical_card_created",
            or_(
                IntakeAudit.entity_id == card.id,
                IntakeAudit.data["physical_card_id"].astext == str(card.id),
            ),
        )
        .limit(1)
    ):
        reasons.append("custody_history_exists")
    return reasons
