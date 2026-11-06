"""Commercial state and the dormant, trusted provider seam. No charging endpoint."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.auth import now
from app.commercial_models import (
    CommercialEvent,
    DispatchExpectation,
    EntitlementAssignment,
    PaymentObligation,
    ShipmentDeclaration,
    SupplementaryAcceptance,
    VerifiedPayment,
)
from app.intake_models import Parcel
from app.intake_voids import PhysicalCardVoid
from app.pricing_models import QuoteAcceptance, SubmissionQuote
from app.submission_models import Submission

DISPATCH_POLICY = {
    "calendar_days_after_verified_payment": 30,
    "timezone": "UTC",
    "automatic_forfeiture": False,
}


def event(db, sid, kind, data, actor=None, reason=None):
    db.add(
        CommercialEvent(
            submission_id=sid,
            kind=kind,
            data=data,
            actor_id=actor,
            reason=reason,
            created_at=now(),
        )
    )


def obligation_for(db, quote, accepted_at):
    checkout = quote.snapshot.get("checkout", {})
    total = checkout.get("final_payable_minor")
    if (
        type(total) is not int
        or total < 0
        or not checkout.get("readiness", {}).get("ready")
        or not quote.snapshot.get("commercial_terms_version")
    ):
        raise HTTPException(409, "complete_commercial_snapshot_required")
    existing = db.get(PaymentObligation, quote.id)
    if existing:
        return existing
    result = PaymentObligation(
        quote_id=quote.id,
        submission_id=quote.submission_id,
        amount_minor=total,
        currency="EUR",
        created_at=accepted_at,
    )
    db.add(result)
    event(
        db,
        quote.submission_id,
        "quote_accepted_awaiting_payment",
        {"quote_id": str(quote.id), "amount_minor": total},
    )
    return result


@dataclass(frozen=True)
class ProviderConfirmation:
    quote_id: UUID
    provider: str
    event_id: str
    payment_id: str
    amount_minor: int
    currency: str
    paid_at: datetime


class ProviderVerifier(Protocol):
    def verify(self, raw_event: bytes, signature: str) -> ProviderConfirmation:
        """Verify provider signature AND settled amount/currency/merchant/quote linkage.

        No verifier is configured or reachable through HTTP in V0.6a.
        """
        ...


def record_provider_confirmation(db, raw_event, signature, verifier: ProviderVerifier):
    confirmation = verifier.verify(raw_event, signature)
    if not isinstance(confirmation, ProviderConfirmation):
        raise ValueError("Unverified provider confirmation")
    for value, limit in (
        (confirmation.provider, 32),
        (confirmation.event_id, 200),
        (confirmation.payment_id, 200),
    ):
        if not isinstance(value, str) or not 1 <= len(value) <= limit:
            raise ValueError("Invalid provider identity")
    obligation = db.scalar(
        select(PaymentObligation)
        .where(PaymentObligation.quote_id == confirmation.quote_id)
        .with_for_update()
    )
    if not obligation:
        raise ValueError("No accepted payment obligation")
    previous = db.get(VerifiedPayment, confirmation.quote_id)
    if previous:
        if (
            previous.provider,
            previous.provider_payment_id,
            previous.amount_minor,
            previous.currency,
        ) != (
            confirmation.provider,
            confirmation.payment_id,
            confirmation.amount_minor,
            confirmation.currency,
        ):
            raise ValueError("Payment confirmation conflict")
        return previous
    if (
        type(confirmation.amount_minor) is not int
        or confirmation.amount_minor != obligation.amount_minor
        or confirmation.currency != obligation.currency
        or confirmation.paid_at.tzinfo is None
        or confirmation.paid_at < obligation.created_at
        or confirmation.paid_at > now()
    ):
        raise ValueError("Payment does not match the complete accepted quote")
    # Serialize with customer declarations/reviews and any future provider callbacks.
    db.scalar(
        select(Submission)
        .where(Submission.id == obligation.submission_id)
        .with_for_update()
    )
    payment = VerifiedPayment(
        quote_id=confirmation.quote_id,
        provider=confirmation.provider,
        provider_event_id=confirmation.event_id,
        provider_payment_id=confirmation.payment_id,
        amount_minor=confirmation.amount_minor,
        currency=confirmation.currency,
        verified_at=confirmation.paid_at,
        recorded_at=now(),
    )
    db.add(payment)
    db.flush()
    acceptance = db.get(QuoteAcceptance, obligation.submission_id)
    if acceptance and acceptance.quote_id == confirmation.quote_id:
        expectation = DispatchExpectation(
            submission_id=obligation.submission_id,
            quote_id=confirmation.quote_id,
            verified_payment_at=confirmation.paid_at,
            dispatch_deadline=dispatch_deadline(confirmation.paid_at),
            policy=DISPATCH_POLICY,
        )
        db.add(expectation)
    event(
        db,
        obligation.submission_id,
        "provider_payment_verified",
        {
            "quote_id": str(confirmation.quote_id),
            "verified_at": confirmation.paid_at.isoformat(),
            "dispatch_deadline": dispatch_deadline(confirmation.paid_at).isoformat()
            if acceptance and acceptance.quote_id == confirmation.quote_id
            else None,
            "dispatch_policy": DISPATCH_POLICY
            if acceptance and acceptance.quote_id == confirmation.quote_id
            else None,
        },
    )
    db.flush()
    return payment


def dispatch_deadline(verified_at):
    if verified_at.tzinfo is None:
        raise ValueError("An aware verified-payment timestamp is required")
    return verified_at.astimezone(timezone.utc) + timedelta(days=30)


def dispatch_indicators(
    verified_at,
    deadline,
    declarations,
    receipts,
    manual_review,
    timestamp,
    approaching_days=None,
):
    indicators = []
    if verified_at is None:
        indicators.append("awaiting_verified_payment")
    if receipts:
        indicators.append("parcel_received")
    elif verified_at is None:
        pass
    elif declarations:
        indicators.append("customer_shipment_declared")
    else:
        indicators.append("awaiting_customer_dispatch")
    if deadline and not receipts:
        if timestamp > deadline:
            indicators.append("dispatch_deadline_passed")
        elif approaching_days is not None and deadline - timestamp <= timedelta(
            days=approaching_days
        ):
            indicators.append("dispatch_deadline_approaching")
    if manual_review:
        indicators.append("manual_review_required")
    return indicators


def state(db, item, timestamp=None, approaching_days=None):
    timestamp = timestamp or now()
    expectation = db.get(DispatchExpectation, item.id)
    declarations = db.scalars(
        select(ShipmentDeclaration)
        .where(ShipmentDeclaration.submission_id == item.id)
        .order_by(ShipmentDeclaration.recorded_at, ShipmentDeclaration.id)
    ).all()
    receipts = db.scalars(
        select(Parcel)
        .where(Parcel.submission_id == item.id)
        .order_by(Parcel.received_at, Parcel.id)
    ).all()
    events = db.scalars(
        select(CommercialEvent)
        .where(CommercialEvent.submission_id == item.id)
        .order_by(CommercialEvent.created_at, CommercialEvent.id)
    ).all()
    reviews = [e for e in events if e.kind == "dispatch_review"]
    review = reviews[-1].data["required"] if reviews else False
    acceptance = db.get(QuoteAcceptance, item.id)
    from app.stripe_checkout import financial_restrictions, payment_state, payment_review_required
    return {
        "charging_enabled": False,
        "payment_review_required": payment_review_required(db, acceptance.quote_id) if acceptance else False,
        "accepted_quote_id": acceptance.quote_id if acceptance else None,
        "financial_restrictions": financial_restrictions(db, acceptance.quote_id) if acceptance else [],
        "payment_status": payment_state(db, acceptance.quote_id) if acceptance else "quote_not_accepted",
        "verified_payment_at": expectation.verified_payment_at if expectation else None,
        "dispatch_deadline": expectation.dispatch_deadline if expectation else None,
        "dispatch_policy": DISPATCH_POLICY,
        "indicators": dispatch_indicators(
            expectation.verified_payment_at if expectation else None,
            expectation.dispatch_deadline if expectation else None,
            declarations,
            receipts,
            review,
            timestamp,
            approaching_days,
        ),
        "shipment_declarations": [
            {
                "id": d.id,
                "declared_dispatch_at": d.declared_dispatch_at,
                "carrier": d.carrier,
                "tracking": d.tracking,
                "recorded_at": d.recorded_at,
                "verification": "customer_declared_only",
            }
            for d in declarations
        ],
        "parcel_receipts": [
            {"id": p.id, "reference": p.reference, "received_at": p.received_at}
            for p in receipts
        ],
        "audit": [
            {
                "id": e.id,
                "kind": e.kind,
                "data": e.data,
                "reason": e.reason,
                "created_at": e.created_at,
            }
            for e in events
        ],
    }


def notification_hooks(db, item, timestamp=None, approaching_days=None):
    """Pure candidates for a future dispatcher; no sending/scheduling or side effects."""
    current = state(db, item, timestamp, approaching_days)
    return [
        {
            "kind": kind,
            "submission_id": str(item.id),
            "deadline": current["dispatch_deadline"],
        }
        for kind in current["indicators"]
        if kind in ("dispatch_deadline_approaching", "dispatch_deadline_passed")
    ]


def assign_entitlement(db, card, quote, card_key, actor, reason):
    if (
        not reason.strip()
        or db.get(PhysicalCardVoid, card.id)
        or card.submission_id != quote.submission_id
    ):
        raise HTTPException(409, "commercial_assignment_invalid")
    obligation = db.get(PaymentObligation, quote.id)
    if not obligation:
        raise HTTPException(409, "quote_not_accepted")
    if quote.physical_card_id is not None:
        accepted = db.get(SupplementaryAcceptance, quote.id)
        if (
            not accepted
            or quote.physical_card_id != card.id
            or card_key != str(card.id)
        ):
            raise HTTPException(409, "supplementary_entitlement_required")
        line = quote.snapshot["lines"][0]
    else:
        accepted = db.get(QuoteAcceptance, card.submission_id)
        line = next(
            (
                line
                for line in quote.snapshot["lines"]
                if card_key in line.get("card_keys", [])
                and str(card.entry_id) == line["entry_id"]
            ),
            None,
        )
        from app.intake_models import Discrepancy

        unexpected = db.scalar(
            select(Discrepancy.id).where(
                Discrepancy.submission_id == card.submission_id,
                Discrepancy.kind == "unexpected",
                Discrepancy.card_id == card.id,
            )
        )
        if (
            not accepted
            or accepted.quote_id != quote.id
            or not line
            or card.status != "matched"
            or unexpected
        ):
            raise HTTPException(409, "original_entitlement_not_applicable")
    old = db.get(EntitlementAssignment, card.id)
    if old:
        if old.quote_id != quote.id or old.card_key != card_key:
            raise HTTPException(409, "entitlement_already_assigned")
        return old
    if db.scalar(
        select(EntitlementAssignment.physical_card_id).where(
            EntitlementAssignment.quote_id == quote.id,
            EntitlementAssignment.card_key == card_key,
        )
    ):
        raise HTTPException(409, "entitlement_already_assigned")
    assignment = EntitlementAssignment(
        physical_card_id=card.id,
        quote_id=quote.id,
        card_key=card_key,
        service_id=line["service_id"],
        assigned_by=actor,
    )
    db.add(assignment)
    event(
        db,
        card.submission_id,
        "entitlement_assigned",
        {
            "quote_id": str(quote.id),
            "physical_card_id": str(card.id),
            "card_key": card_key,
        },
        actor,
        reason,
    )
    db.flush()
    return assignment


def card_commercial_state(db, card):
    assignment = db.get(EntitlementAssignment, card.id)
    payment = db.get(VerifiedPayment, assignment.quote_id) if assignment else None
    reasons = []
    if assignment:
        quote = db.get(SubmissionQuote, assignment.quote_id)
        if quote.physical_card_id is not None:
            original = db.get(QuoteAcceptance, card.submission_id)
            if not original or not db.get(VerifiedPayment, original.quote_id):
                reasons.append("original_shipping_payment_required")
    if not assignment:
        reasons.append("explicit_commercial_assignment_required")
    if not payment:
        reasons.append("separately_verified_payment_required")
    if db.get(PhysicalCardVoid, card.id):
        reasons.append("card_voided")
    from app.stripe_checkout import restricted
    if assignment and restricted(db, assignment.quote_id):
        reasons.append("payment_financial_restriction")
    original = db.get(QuoteAcceptance, card.submission_id)
    if original and restricted(db, original.quote_id):
        reasons.append("original_shipping_financial_restriction")
    # This domain result is not inspection/custody authorization. The existing
    # fail-closed grading provider remains unchanged until the V0.6b handoff.
    return {
        "commercially_eligible": not reasons,
        "reasons": reasons,
        "quote_id": assignment.quote_id if assignment else None,
        "service_id": assignment.service_id if assignment else None,
    }
