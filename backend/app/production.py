"""Reservation/local-commit/confirmation protocol; never grants grading clearance."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.cards import Config, Db
from app.inspection_commercial import commercial_provider
from app.inspection_eligibility import eligibility
from app.inspection_models import Inspection
from app.intake import Payload, audit, detail, router, staff, submission, validate_complete
from app.intake_models import PhysicalCard, StaffMembership
from app.intake_voids import active_card
from app.production_models import ProductionCard, ProductionOrder

Commerce = Annotated[object, Depends(commercial_provider)]


def binding(db, sid):
    order = db.get(ProductionOrder, sid)
    if order is None:
        return None
    return {
        "registry_id": order.registry_id,
        "local_order_id": order.local_order_id,
        "mode": order.mode,
        "cards": {
            str(c.physical_card_id): c.local_card_id
            for c in db.scalars(select(ProductionCard).where(ProductionCard.submission_id == sid))
        },
    }


def snapshot(db, item, actor, provider):
    data = detail(db, item)
    data['voided_cards'] = [c for c in data['cards'] if c['status'] == 'voided']
    data['cards'] = [c for c in data['cards'] if c['status'] != 'voided']
    reasons = []
    if data["status"] != "reconciled":
        reasons.append("intake_not_reconciled")
    else:
        try:
            validate_complete(db, item.id)
        except HTTPException as exc:
            reasons.append(exc.detail)
    cards = list(db.scalars(select(PhysicalCard).where(PhysicalCard.submission_id == item.id, active_card())))
    if not cards:
        reasons.append("no_received_cards")
    if any(c.grading_card_id is not None for c in cards):
        reasons.append("backend_grading_link_requires_review")
    checks = {}
    for card in cards:
        dossier = db.scalar(select(Inspection).where(Inspection.physical_card_id == card.id))
        checks[str(card.id)] = eligibility(db, card, provider, "start", dossier)
        for issue in checks[str(card.id)]["reasons"]:
            if issue["code"] in {
                "association_invalid",
                "discrepancy_block",
                "customer_copy_returned",
            }:
                reasons.append(issue["code"])
    return {
        "submission": data,
        "actor": {"id": actor.id, "role": db.get(StaffMembership, actor.id).role},
        "preparation": {"eligible": not reasons, "reasons": sorted(set(reasons))},
        "inspection": checks,
        "binding": binding(db, item.id),
    }


@router.get("/submissions/{sid}/production")
def production_view(sid: UUID, request: Request, db: Db, settings: Config, provider: Commerce):
    actor = staff(request, db, settings)
    return snapshot(db, submission(db, sid), actor, provider)


class Reservation(Payload):
    registry_id: UUID
    mode: Literal["create", "adopt"]
    reason: str = Field(min_length=1, max_length=1000)


class Pair(Payload):
    physical_card_id: UUID
    local_card_id: str = Field(pattern=r"^SLB-C-[0-9]{6,}$", max_length=40)


class Confirmation(Payload):
    registry_id: UUID
    local_order_id: str = Field(pattern=r"^ORD-[0-9]{6,}$", max_length=40)
    cards: list[Pair] = Field(min_length=1, max_length=10000)
    reason: str = Field(min_length=1, max_length=1000)


def check_owner(order, registry_id):
    if order and order.registry_id != registry_id:
        raise HTTPException(409, "production_owned_by_other_registry")


def check_admin(db, actor, mode):
    if mode == "adopt" and db.get(StaffMembership, actor.id).role != "admin":
        raise HTTPException(403, "administrator_required")


@router.post("/submissions/{sid}/production/reserve")
def reserve(
    sid: UUID,
    payload: Reservation,
    request: Request,
    db: Db,
    settings: Config,
    provider: Commerce,
):
    actor = staff(request, db, settings)
    item = submission(db, sid)
    order = db.get(ProductionOrder, sid)
    check_owner(order, payload.registry_id)
    check_admin(db, actor, payload.mode)
    if order and order.mode != payload.mode:
        raise HTTPException(409, "production_mode_conflict")
    result = snapshot(db, item, actor, provider)
    if not result["preparation"]["eligible"]:
        raise HTTPException(409, "production_not_eligible")
    if order is None:
        db.add(
            ProductionOrder(
                submission_id=sid,
                registry_id=payload.registry_id,
                mode=payload.mode,
                actor_id=actor.id,
                reason=payload.reason,
            )
        )
        audit(
            db,
            actor,
            sid,
            "production_reserved",
            sid,
            {"registry_id": str(payload.registry_id), "mode": payload.mode},
            payload.reason,
        )
        db.commit()
    return snapshot(db, item, actor, provider)


@router.post("/submissions/{sid}/production/confirm")
def confirm(
    sid: UUID,
    payload: Confirmation,
    request: Request,
    db: Db,
    settings: Config,
    provider: Commerce,
):
    actor = staff(request, db, settings)
    item = submission(db, sid)
    order = db.get(ProductionOrder, sid)
    check_owner(order, payload.registry_id)
    if order is None:
        raise HTTPException(409, "production_reservation_required")
    check_admin(db, actor, order.mode)
    pairs = {str(c.physical_card_id): c.local_card_id for c in payload.cards}
    if len(pairs) != len(payload.cards) or len(set(pairs.values())) != len(pairs):
        raise HTTPException(409, "production_duplicate_pair")
    previous = binding(db, sid)
    if order.local_order_id is not None:
        if order.local_order_id != payload.local_order_id or previous["cards"] != pairs:
            raise HTTPException(409, "production_mapping_conflict")
        return snapshot(db, item, actor, provider)
    result = snapshot(db, item, actor, provider)
    if not result["preparation"]["eligible"]:
        raise HTTPException(409, "production_not_eligible")
    if set(pairs) != {str(c["id"]) for c in result["submission"]["cards"]}:
        raise HTTPException(409, "production_manifest_changed")
    order.local_order_id = payload.local_order_id
    db.add_all(
        [
            ProductionCard(
                physical_card_id=UUID(pc),
                submission_id=sid,
                registry_id=payload.registry_id,
                local_card_id=local,
            )
            for pc, local in pairs.items()
        ]
    )
    audit(
        db,
        actor,
        sid,
        "production_confirmed",
        sid,
        {
            "registry_id": str(payload.registry_id),
            "local_order_id": payload.local_order_id,
            "cards": pairs,
            "mode": order.mode,
        },
        payload.reason,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "production_mapping_conflict") from None
    return snapshot(db, item, actor, provider)
