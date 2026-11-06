"""Existing-order commerce APIs. No payment-success, charging or refund route."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, Field
from sqlalchemy import select

from app.auth import now, write_guard
from app.auth_schemas import Payload
from app.cards import Config, Db
from app.checkout import shipping_amounts, shipping_config
from app.checkout_schemas import Parcel as ReturnParcel
from app.commercial import (
    assign_entitlement,
    card_commercial_state,
    event,
    obligation_for,
    state,
)
from app.commercial_models import (
    EntitlementAssignment,
    ShipmentDeclaration,
    SupplementaryAcceptance,
    VerifiedPayment,
)
from app.intake import staff, submission
from app.intake_models import Discrepancy, PhysicalCard
from app.intake_voids import PhysicalCardVoid
from app.pricing import calculate, current_catalog, validate_options
from app.pricing_models import QuoteAcceptance, SubmissionQuote
from app.pricing_schemas import Identifier, Minor
from app.submission_schemas import Text
from app.submissions import owned

router = APIRouter(dependencies=[Depends(write_guard)])


class ShipmentInput(Payload):
    request_key: UUID
    declared_dispatch_at: AwareDatetime | None = None
    carrier: str = Field(default="", max_length=100, pattern=r"^[^\x00-\x1f\x7f]*$")
    tracking: str = Field(default="", max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")


@router.get("/api/submissions/{identifier}/commercial-state")
def commercial_state(identifier: UUID, request: Request, db: Db, settings: Config):
    from app.stripe_checkout import accepted_obligation, enabled
    result = state(db, owned(identifier, request, db, settings),
        approaching_days=settings.dispatch_reminder_lead_days)
    if enabled(settings) and result["accepted_quote_id"]:
        try:
            accepted_obligation(db, identifier, result["accepted_quote_id"], settings)
            result["charging_enabled"] = result["payment_status"] not in {"verified", "restricted"} and not result["payment_review_required"]
        except HTTPException:
            pass
    return result


@router.post("/api/submissions/{identifier}/shipment-declarations", status_code=201)
def declare_shipment(
    identifier: UUID, payload: ShipmentInput, request: Request, db: Db, settings: Config
):
    item = owned(identifier, request, db, settings)
    accepted = db.get(QuoteAcceptance, item.id)
    if not accepted or not db.get(VerifiedPayment, accepted.quote_id):
        raise HTTPException(409, "verified_payment_required_before_dispatch")
    old = db.scalar(
        select(ShipmentDeclaration).where(
            ShipmentDeclaration.submission_id == item.id,
            ShipmentDeclaration.request_key == payload.request_key,
        )
    )
    if old:
        if any(
            getattr(old, key) != value
            for key, value in payload.model_dump(exclude={"request_key"}).items()
        ):
            raise HTTPException(409, "idempotency_conflict")
    else:
        # owned() holds the same submission row lock as Stripe webhook processing.
        # Historical replays above remain valid even after a financial restriction.
        from app.stripe_checkout import restricted

        if restricted(db, accepted.quote_id):
            raise HTTPException(409, "payment_financial_restriction")
        if payload.declared_dispatch_at and payload.declared_dispatch_at > now():
            raise HTTPException(422, "future_dispatch_declaration")
        old = ShipmentDeclaration(
            submission_id=item.id,
            declared_by=item.customer_id,
            recorded_at=now(),
            **payload.model_dump(),
        )
        db.add(old)
        db.flush()
        event(
            db,
            item.id,
            "customer_shipment_declared",
            {"declaration_id": str(old.id), "verification": "customer_declared_only"},
            item.customer_id,
        )
    db.flush()
    result = state(db, item, approaching_days=settings.dispatch_reminder_lead_days)
    db.commit()
    return result


class DispatchReview(Payload):
    manual_review_required: bool = Field(strict=True)
    reason: Text


@router.post(
    "/internal/intake/submissions/{identifier}/dispatch-review", include_in_schema=False
)
def review_dispatch(
    identifier: UUID,
    payload: DispatchReview,
    request: Request,
    db: Db,
    settings: Config,
):
    actor = staff(request, db, settings)
    item = submission(db, identifier)
    current = state(db, item, approaching_days=settings.dispatch_reminder_lead_days)
    event(
        db,
        item.id,
        "dispatch_review",
        {
            "required": payload.manual_review_required,
            "observed_indicators": current["indicators"],
        },
        actor.id,
        payload.reason,
    )
    db.flush()
    result = state(db, item, approaching_days=settings.dispatch_reminder_lead_days)
    db.commit()
    return result


class SupplementInput(Payload):
    physical_card_id: UUID
    processing_tier: Identifier
    upgrade_ids: list[Identifier] = Field(
        default_factory=lambda: ["classic"], min_length=1, max_length=16
    )
    shipping_service_id: Identifier
    declared_value_minor: Minor
    parcel: ReturnParcel
    reason: Text


def prior_supplements(db, sid):
    return db.scalars(
        select(SupplementaryAcceptance)
        .join(SubmissionQuote, SubmissionQuote.id == SupplementaryAcceptance.quote_id)
        .where(SubmissionQuote.submission_id == sid)
        .order_by(SupplementaryAcceptance.quote_id)
    ).all()


def supplement_context(db, sid):
    record, _ = shipping_config(db)
    return {
        "shipping_version": str(record.version) if record else None,
        "accepted_supplement_quote_ids": [
            str(a.quote_id) for a in prior_supplements(db, sid)
        ],
    }


def supplementary_status(db, quote, settings):
    if db.get(SupplementaryAcceptance, quote.id):
        return "accepted"
    if db.scalar(
        select(SupplementaryAcceptance.quote_id).where(
            SupplementaryAcceptance.physical_card_id == quote.physical_card_id
        )
    ):
        return "superseded"
    if quote.expires_at <= now():
        return "expired"
    record, _ = current_catalog(db, settings)
    if record.version != quote.catalog_version:
        return "catalog_changed"
    if quote.snapshot["supplement_context"] != supplement_context(
        db, quote.submission_id
    ):
        return "invalidated"
    card = db.get(PhysicalCard, quote.physical_card_id)
    if (
        db.get(PhysicalCardVoid, card.id)
        or db.get(EntitlementAssignment, card.id)
        or card.grading_card_id
    ):
        return "invalidated"
    return "valid"


def supplementary_public(db, quote, settings):
    accepted = db.get(SupplementaryAcceptance, quote.id)
    from app.stripe_checkout import enabled, financial_restrictions, payment_state, payment_review_required
    review_required = bool(accepted and payment_review_required(db, quote.id))
    return {
        "charging_enabled": bool(accepted and enabled(settings) and payment_state(db, quote.id) not in {"verified", "restricted"} and not review_required),
        "payment_review_required": review_required,
        "id": quote.id,
        "physical_card_id": quote.physical_card_id,
        "created_at": quote.created_at,
        "expires_at": quote.expires_at,
        "status": supplementary_status(db, quote, settings),
        "accepted_at": accepted.accepted_at if accepted else None,
        "financial_restrictions": financial_restrictions(db, quote.id) if accepted else [],
        "snapshot": quote.snapshot,
        "payment_status": payment_state(db, quote.id) if accepted else "not_accepted",
    }


@router.post(
    "/internal/intake/submissions/{identifier}/supplementary-quotes",
    status_code=201,
    include_in_schema=False,
)
def supplementary_quote(
    identifier: UUID,
    payload: SupplementInput,
    request: Request,
    db: Db,
    settings: Config,
):
    actor = staff(request, db, settings)
    item = submission(db, identifier)
    accepted = db.get(QuoteAcceptance, item.id)
    if not accepted:
        raise HTTPException(409, "original_quote_acceptance_required")
    original = db.get(SubmissionQuote, accepted.quote_id)
    original_checkout = original.snapshot.get("checkout", {})
    destination = original_checkout.get("return_address")
    if not destination or not original_checkout.get("readiness", {}).get("ready"):
        raise HTTPException(409, "original_shipping_snapshot_required")
    card = db.get(PhysicalCard, payload.physical_card_id)
    unexpected = db.scalar(
        select(Discrepancy.id).where(
            Discrepancy.submission_id == item.id,
            Discrepancy.card_id == payload.physical_card_id,
            Discrepancy.kind == "unexpected",
        )
    )
    if (
        not card
        or card.submission_id != item.id
        or db.get(PhysicalCardVoid, card.id)
        or card.grading_card_id
        or db.get(EntitlementAssignment, card.id)
        or not unexpected
    ):
        raise HTTPException(409, "documented_additional_card_required")
    if db.scalar(
        select(SupplementaryAcceptance.quote_id).where(
            SupplementaryAcceptance.physical_card_id == card.id
        )
    ):
        raise HTTPException(409, "supplement_already_accepted")
    record, config = current_catalog(db, settings)
    validate_options(config, payload.processing_tier, payload.upgrade_ids)
    # Synthetic pricing input represents this already-received PC, not a new entry or identity.
    pricing_card = SimpleNamespace(
        id=card.id,
        quantity=1,
        processing_tier=payload.processing_tier,
        upgrade_ids=payload.upgrade_ids,
        card_name=card.reference,
        game="",
        expansion="",
        card_number="",
        language="",
        notes="",
    )
    grading = calculate(config, [pricing_card])
    if (
        grading["development_only"]
        or not config.commercial_terms_version
        or any(
            line["tax_mode"] == "pending" or not line["tax_validation_reference"]
            for line in grading["lines"]
        )
    ):
        raise HTTPException(409, "commercial_configuration_pending")
    grading["lines"][0]["card_keys"] = [str(card.id)]
    shipping_record, shipping = shipping_config(db)
    service = shipping.services.get(payload.shipping_service_id)
    if payload.shipping_service_id != original_checkout.get("shipping", {}).get(
        "service", {}
    ).get("id"):
        raise HTTPException(409, "supplement_shipping_change_requires_review")
    prior = prior_supplements(db, item.id)
    declared_total = (
        original_checkout["delivery"]["declared_value_minor"]
        + payload.declared_value_minor
        + sum(
            db.get(SubmissionQuote, a.quote_id).snapshot["supplement_inputs"][
                "additional_declared_value_minor"
            ]
            for a in prior
        )
    )
    quantity = original_checkout["quantity"] + len(prior) + 1
    if (
        not service
        or not service.available
        or service.additional_card_charge_minor is None
        or destination["country"] not in shipping.supported_destinations
        or destination["country"] not in service.countries
        or not service.tracked
        or not service.trading_cards_coverage_verified
        or not service.coverage_reference
        or declared_total > service.coverage_minor
        or quantity < service.min_cards
        or (service.max_cards is not None and quantity > service.max_cards)
        or (service.phone_required and not destination.get("phone"))
    ):
        raise HTTPException(409, "supplement_shipping_rate_required")
    parcel = payload.parcel.model_dump()
    for field in ("weight_g", "length_mm", "width_mm", "height_mm"):
        maximum = getattr(service, "max_" + field)
        if maximum is not None and (not parcel[field] or parcel[field] > maximum):
            raise HTTPException(409, "supplement_shipping_rate_required")
    cost = shipping_amounts(
        service.additional_card_charge_minor, service.tax_mode, service.tax_rate_bps
    )
    shipping_line = {
        "kind": "return_shipping_adjustment",
        **cost,
        "service": {"id": payload.shipping_service_id, **service.model_dump()},
        "tax_mode": service.tax_mode,
        "tax_rate_bps": service.tax_rate_bps,
    }
    inputs = {
        "additional_declared_value_minor": payload.declared_value_minor,
        "aggregate_declared_value_minor": declared_total,
        "aggregate_card_count": quantity,
        "parcel": parcel,
        "destination_country": destination["country"],
    }
    timestamp = now()
    snapshot = {
        **grading,
        "pricing_version": str(record.version),
        "purpose": "additional_card",
        "physical_card_id": str(card.id),
        "supplement_context": supplement_context(db, item.id),
        "supplement_inputs": inputs,
        "checkout": {
            "currency": "EUR",
            "return_address": destination,
            "shipping": shipping_line,
            "shipping_configuration_version": str(shipping_record.version),
            "shipping_pricing_inputs": inputs,
            "final_payable_minor": grading["total_minor"] + cost["charge_minor"],
            "net_total_minor": grading["net_minor"] + cost["net_minor"],
            "tax_total_minor": grading["tax_minor"] + cost["tax_minor"],
            "commercial_terms_version": config.commercial_terms_version,
            "adjustments_minor": 0,
            "line_items": [{"kind": "grading", **line} for line in grading["lines"]]
            + [shipping_line],
            "readiness": {"ready": True, "states": ["ready_for_checkout"]},
            "payment": {"charging_enabled": False, "status": "unavailable"},
        },
    }
    quote = SubmissionQuote(
        submission_id=item.id,
        physical_card_id=card.id,
        pricing_revision=item.pricing_revision,
        catalog_version=record.version,
        snapshot=snapshot,
        created_at=timestamp,
        expires_at=timestamp + timedelta(seconds=config.quote_lifetime_seconds),
    )
    db.add(quote)
    db.flush()
    event(
        db,
        item.id,
        "supplementary_quote_prepared",
        {"quote_id": str(quote.id), "physical_card_id": str(card.id)},
        actor.id,
        payload.reason,
    )
    result = supplementary_public(db, quote, settings)
    db.commit()
    return result


@router.get("/api/submissions/{identifier}/supplementary-quotes")
def supplementary_list(identifier: UUID, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    quotes = db.scalars(
        select(SubmissionQuote)
        .where(
            SubmissionQuote.submission_id == item.id,
            SubmissionQuote.physical_card_id.is_not(None),
        )
        .order_by(SubmissionQuote.created_at.desc())
        .limit(100)
    ).all()
    return [supplementary_public(db, q, settings) for q in quotes]


class SupplementConsent(Payload):
    accept_terms: bool = Field(strict=True)


@router.post("/api/submissions/{identifier}/supplementary-quotes/{quote_id}/accept")
def supplementary_accept(
    identifier: UUID,
    quote_id: UUID,
    payload: SupplementConsent,
    request: Request,
    db: Db,
    settings: Config,
):
    item = owned(identifier, request, db, settings)
    quote = db.scalar(
        select(SubmissionQuote).where(
            SubmissionQuote.id == quote_id,
            SubmissionQuote.submission_id == item.id,
            SubmissionQuote.physical_card_id.is_not(None),
        )
    )
    if not quote:
        raise HTTPException(404, "quote_not_found")
    if not payload.accept_terms:
        raise HTTPException(422, "explicit_terms_required")
    if db.get(SupplementaryAcceptance, quote.id):
        return supplementary_public(db, quote, settings)
    if supplementary_status(db, quote, settings) != "valid":
        raise HTTPException(409, "quote_stale")
    timestamp = now()
    db.add(
        SupplementaryAcceptance(
            quote_id=quote.id,
            physical_card_id=quote.physical_card_id,
            accepted_at=timestamp,
        )
    )
    obligation_for(db, quote, timestamp)
    db.flush()
    result = supplementary_public(db, quote, settings)
    db.commit()
    return result


class EntitlementInput(Payload):
    physical_card_id: UUID
    quote_id: UUID
    card_key: str = Field(min_length=1, max_length=80)
    reason: Text


@router.post(
    "/internal/intake/submissions/{identifier}/commercial-assignment",
    include_in_schema=False,
)
def commercial_assignment(
    identifier: UUID,
    payload: EntitlementInput,
    request: Request,
    db: Db,
    settings: Config,
):
    actor = staff(request, db, settings)
    item = submission(db, identifier)
    card = db.get(PhysicalCard, payload.physical_card_id)
    quote = db.get(SubmissionQuote, payload.quote_id)
    if (
        not card
        or not quote
        or card.submission_id != item.id
        or quote.submission_id != item.id
    ):
        raise HTTPException(404, "card_or_quote_not_found")
    assign_entitlement(db, card, quote, payload.card_key, actor.id, payload.reason)
    result = card_commercial_state(db, card)
    db.commit()
    return result
