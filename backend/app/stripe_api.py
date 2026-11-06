"""Authenticated Checkout initiation; raw-body signed webhook is separate."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import write_guard
from app.auth_schemas import Payload
from app.cards import Config, Db
from app.stripe_checkout import (
    StripeGateway,
    financial_restrictions,
    handle_event,
    payment_state,
    payment_review_required,
    require_enabled,
    signature_event,
    start_checkout,
)
from app.submissions import owned

router = APIRouter()


class CheckoutInput(Payload):
    quote_id: UUID


@router.post(
    "/api/submissions/{identifier}/stripe-checkout", dependencies=[Depends(write_guard)]
)
def checkout(
    identifier: UUID, payload: CheckoutInput, request: Request, db: Db, settings: Config
):
    item = owned(identifier, request, db, settings)
    try:
        return start_checkout(
            db, item, payload.quote_id, settings, StripeGateway(settings)
        )
    except ValueError:
        db.rollback()
        raise HTTPException(409, "stripe_checkout_verification_failed") from None


@router.get("/api/submissions/{identifier}/payments/{quote_id}")
def status(
    identifier: UUID, quote_id: UUID, request: Request, db: Db, settings: Config
):
    from app.commercial_models import PaymentObligation

    item = owned(identifier, request, db, settings)
    obligation = db.get(PaymentObligation, quote_id)
    if not obligation or obligation.submission_id != item.id:
        raise HTTPException(404, "payment_not_found")
    return {
        "status": payment_state(db, quote_id),
        "payment_review_required": payment_review_required(db, quote_id),
        "restrictions": financial_restrictions(db, quote_id),
    }


@router.post("/api/stripe/webhook")
async def webhook(request: Request, db: Db, settings: Config):
    require_enabled(settings)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            raise HTTPException(413, "stripe_event_too_large")
    event = signature_event(
        bytes(raw),
        request.headers.get("stripe-signature", ""),
        settings.stripe_webhook_secret,
    )
    try:
        handle_event(db, event, settings, StripeGateway(settings))
        db.commit()
    except (ValueError, KeyError, TypeError):
        db.rollback()
        raise HTTPException(400, "stripe_event_verification_failed") from None
    return {"received": True}


class HoldInput(Payload):
    quote_id: UUID
    reason: str
    request_key: UUID


@router.post(
    "/internal/intake/submissions/{identifier}/payment-hold",
    dependencies=[Depends(write_guard)],
    include_in_schema=False,
)
def hold(
    identifier: UUID, payload: HoldInput, request: Request, db: Db, settings: Config
):
    from app.commercial_models import PaymentObligation
    from app.intake import staff, submission
    from app.stripe_models import StripeEvidence

    actor = staff(request, db, settings)
    item = submission(db, identifier)
    obligation = db.get(PaymentObligation, payload.quote_id)
    if not obligation or obligation.submission_id != item.id:
        raise HTTPException(404, "payment_not_found")
    if not payload.reason.strip() or len(payload.reason) > 1000:
        raise HTTPException(422, "hold_reason_required")
    key = "hold_" + str(payload.request_key)
    data = {"actor_id": str(actor.id), "reason": payload.reason}
    old = db.get(StripeEvidence, key)
    if old and (old.quote_id != payload.quote_id or old.data != data):
        raise HTTPException(409, "idempotency_conflict")
    if not old:
        db.add(
            StripeEvidence(
                event_id=key,
                quote_id=payload.quote_id,
                kind="manual_commercial_hold",
                restricted=True,
                data=data,
            )
        )
    db.commit()
    return {"status": "restricted"}
