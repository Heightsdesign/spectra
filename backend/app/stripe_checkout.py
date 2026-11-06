"""TEST-only Stripe transport, linkage verification and durable financial evidence.

No redirect or browser assertion can call the trusted confirmation seam.
"""

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.auth import now
from app.commercial import ProviderConfirmation, record_provider_confirmation
from app.commercial_models import (
    PaymentObligation,
    SupplementaryAcceptance,
    VerifiedPayment,
)
from app.pricing_models import QuoteAcceptance, SubmissionQuote
from app.stripe_models import StripeAttempt, StripeEvidence
from app.submission_models import Submission


def enabled(settings):
    return (
        settings.stripe_enabled
        and settings.stripe_mode == "test"
        and settings.auth_environment != "production"
        and settings.stripe_secret_key.startswith("sk_test_")
        and settings.stripe_webhook_secret.startswith("whsec_")
        and settings.stripe_account_id.startswith("acct_")
    )


def require_enabled(settings):
    if not enabled(settings):
        raise HTTPException(503, "stripe_test_checkout_unavailable")


class StripeGateway:
    def __init__(self, settings):
        require_enabled(settings)
        self.settings = settings

    def call(self, method, path, data=None, key=None):
        headers = {"Stripe-Version": self.settings.stripe_api_version}
        if key:
            headers["Idempotency-Key"] = key
        try:
            # No redirects, configurable hosts, or request/response logging.
            response = httpx.request(
                method,
                "https://api.stripe.com/v1/" + path,
                auth=(self.settings.stripe_secret_key, ""),
                headers=headers,
                data=data,
                timeout=15,
                follow_redirects=False,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "stripe_temporarily_unavailable") from None

    def account(self):
        if self.call("GET", "account").get("id") != self.settings.stripe_account_id:
            raise HTTPException(503, "stripe_account_mismatch")

    def get(self, resource, identifier):
        if not isinstance(identifier, str) or not identifier.replace("_", "").isalnum():
            raise ValueError("Invalid Stripe identity")
        return self.call("GET", resource + "/" + identifier)


def signature_event(raw, signature, secret, timestamp=None):
    try:
        fields = [part.split("=", 1) for part in signature.split(",")]
        stamps = [v for k, v in fields if k == "t"]
        if len(stamps) != 1:
            raise ValueError()
        stamp = stamps[0]
        if abs((time.time() if timestamp is None else timestamp) - int(stamp)) > 300:
            raise ValueError()
        expected = hmac.new(
            secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        if not any(hmac.compare_digest(expected, v) for k, v in fields if k == "v1"):
            raise ValueError()
        event = json.loads(raw)
        if not isinstance(event, dict) or not isinstance(event.get("id"), str):
            raise ValueError()
        return event
    except (ValueError, TypeError, UnicodeError):
        raise HTTPException(400, "invalid_stripe_signature") from None


def accepted_obligation(db, sid, qid, settings=None):
    obligation = db.get(PaymentObligation, qid)
    quote = db.get(SubmissionQuote, qid)
    original = db.get(QuoteAcceptance, sid)
    supplement = db.get(SupplementaryAcceptance, qid)
    if (
        not obligation
        or not quote
        or obligation.submission_id != sid
        or quote.submission_id != sid
        or not (
            (original and original.quote_id == qid and quote.physical_card_id is None)
            or (supplement and supplement.physical_card_id == quote.physical_card_id)
        )
        or obligation.currency != "EUR"
        or obligation.amount_minor <= 0
        or quote.snapshot.get("checkout", {}).get("final_payable_minor")
        != obligation.amount_minor
        or not quote.snapshot.get("checkout", {}).get("readiness", {}).get("ready")
        or not quote.snapshot.get("commercial_terms_version")
    ):
        raise HTTPException(409, "accepted_complete_obligation_required")
    from app.fictitious_checkout import require_snapshot
    if settings is None:
        from app.config import get_settings
        settings = get_settings()
    require_snapshot(quote.snapshot, settings)
    return obligation


def restricted(db, qid):
    return bool(
        db.scalar(
            select(StripeEvidence.event_id)
            .where(StripeEvidence.quote_id == qid, StripeEvidence.restricted.is_(True))
            .limit(1)
        )
    )


def metadata(attempt, obligation, item):
    return {
        "attempt_id": str(attempt.id),
        "quote_id": str(obligation.quote_id),
        "obligation_id": str(obligation.quote_id),
        "submission_id": str(item.id),
        "customer_id": str(item.customer_id),
    }


def start_checkout(db, item, qid, settings, gateway):
    require_enabled(settings)
    obligation = accepted_obligation(db, item.id, qid, settings)
    if db.get(VerifiedPayment, qid) or restricted(db, qid):
        raise HTTPException(409, "payment_already_verified_or_restricted")
    attempt = db.scalar(
        select(StripeAttempt).where(
            StripeAttempt.quote_id == qid,
            StripeAttempt.status.notin_(["expired", "cancelled"]),
        )
    )
    if not attempt:
        attempt = StripeAttempt(
            quote_id=qid,
            account_id=settings.stripe_account_id,
            return_origin=settings.auth_origin,
            created_at=now(),
        )
        db.add(attempt)
        db.flush()
        # Reserve durable identity BEFORE the network. Owner holds the order lock.
        db.commit()
    # Reacquire order lock after commit; concurrent requests reuse the same key.
    db.scalar(select(Submission).where(Submission.id == item.id).with_for_update())
    db.refresh(attempt)
    if db.get(VerifiedPayment, qid) or restricted(db, qid):
        raise HTTPException(409, "payment_already_verified_or_restricted")
    if attempt.account_id != settings.stripe_account_id:
        raise HTTPException(409, "stripe_attempt_account_mismatch")
    gateway.account()
    if attempt.session_id:
        session = gateway.get("checkout/sessions", attempt.session_id)
    else:
        # Stripe may prune idempotency keys after 24h. Ambiguous older attempts
        # require operator recovery; never create a replacement automatically.
        if now() - attempt.created_at > timedelta(hours=23):
            raise HTTPException(409, "ambiguous_attempt_requires_review")
        data = {
            "mode": "payment",
            "client_reference_id": str(attempt.id),
            "success_url": attempt.return_origin
            + "/account/submissions/"
            + str(item.id)
            + "?stripe_return=1",
            "cancel_url": attempt.return_origin
            + "/account/submissions/"
            + str(item.id)
            + "?stripe_return=1",
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": "eur",
            "line_items[0][price_data][unit_amount]": str(obligation.amount_minor),
            "line_items[0][price_data][product_data][name]": "SELBY TEST accepted order",
        }
        for k, v in metadata(attempt, obligation, item).items():
            data[f"metadata[{k}]"] = v
            data[f"payment_intent_data[metadata][{k}]"] = v
        session = gateway.call(
            "POST", "checkout/sessions", data, "selby-test-" + str(attempt.id)
        )
    validate_session(session, attempt, obligation, item)
    attempt.session_id = session["id"]
    attempt.status = "expired" if session.get("status") == "expired" else "pending"
    if (
        session.get("status") == "complete"
        and session.get("payment_status") == "unpaid"
        and session.get("payment_intent")
    ):
        pi = gateway.get("payment_intents", session["payment_intent"])
        if (
            pi.get("livemode") is not False
            or pi.get("metadata") != metadata(attempt, obligation, item)
            or pi.get("id") != session["payment_intent"]
            or pi.get("amount") != obligation.amount_minor
            or pi.get("currency") != "eur"
        ):
            raise ValueError("Retry PaymentIntent mismatch")
        if pi.get("status") in {"requires_payment_method", "canceled"}:
            # A failed async Checkout cannot be reopened. Cancel its PI before
            # allowing a fresh session, so two payable attempts cannot coexist.
            cancelled = (
                pi
                if pi.get("status") == "canceled"
                else gateway.call(
                    "POST",
                    "payment_intents/" + pi["id"] + "/cancel",
                    {},
                    "selby-test-cancel-" + str(attempt.id),
                )
            )
            if cancelled.get("id") != pi["id"] or cancelled.get("status") != "canceled":
                raise ValueError("Payment cancellation not verified")
            attempt.payment_intent_id = pi["id"]
            attempt.status = "cancelled"
            db.add(
                StripeEvidence(
                    event_id="attempt_cancel_" + str(attempt.id),
                    quote_id=qid,
                    kind="failed_checkout_intent_cancelled",
                    restricted=False,
                    data={
                        "payment_intent_id": pi["id"],
                        "session_id": attempt.session_id,
                    },
                )
            )
        elif pi.get("status") == "requires_action":
            attempt.status = "action_required"
    url = session.get("url") if session.get("status") == "open" else None
    if url and (
        urlsplit(url).scheme != "https"
        or urlsplit(url).hostname != "checkout.stripe.com"
    ):
        raise ValueError("Unexpected checkout host")
    attempt.checkout_url = url
    db.commit()
    return {
        "status": attempt.status,
        "url": url if attempt.status == "pending" else None,
        "payment_review_required": attempt.status == "action_required" and not url,
    }


def validate_session(session, attempt, obligation, item):
    if (
        session.get("livemode") is not False
        or session.get("mode") != "payment"
        or session.get("currency") != "eur"
        or type(session.get("amount_total")) is not int
        or session["amount_total"] != obligation.amount_minor
        or session.get("client_reference_id") != str(attempt.id)
        or session.get("metadata") != metadata(attempt, obligation, item)
        or (attempt.session_id and session.get("id") != attempt.session_id)
        or not str(session.get("id", "")).startswith("cs_test_")
    ):
        raise ValueError("Stripe session linkage mismatch")


class SettledVerifier:
    def __init__(self, confirmation):
        self.confirmation = confirmation

    def verify(self, raw_event, signature):
        return self.confirmation


SESSION_EVENTS = {
    "checkout.session.completed",
    "checkout.session.expired",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
}
PI_EVENTS = {
    "payment_intent.succeeded",
    "payment_intent.processing",
    "payment_intent.requires_action",
    "payment_intent.payment_failed",
    "payment_intent.canceled",
}
RESTRICTION_EVENTS = {
    "charge.refunded",
    "charge.dispute.created",
    "charge.dispute.updated",
    "charge.dispute.closed",
    "charge.dispute.funds_withdrawn",
    "charge.dispute.funds_reinstated",
    "refund.created",
    "refund.updated",
    "refund.failed",
}


def handle_event(db, event, settings, gateway):
    require_enabled(settings)
    if event.get("livemode") is not False or event.get("account") not in (
        None,
        settings.stripe_account_id,
    ):
        raise ValueError("Wrong Stripe environment/account")
    kind = event.get("type")
    if kind not in SESSION_EVENTS | PI_EVENTS | RESTRICTION_EVENTS:
        return
    gateway.account()
    obj = event["data"]["object"]
    # Resolve even refund/dispute-before-success through the PI metadata. Never
    # depend on a previous success event having populated the payment ledger.
    if kind in SESSION_EVENTS:
        session = gateway.get("checkout/sessions", obj["id"])
        aid = session.get("metadata", {}).get("attempt_id")
    else:
        if kind in PI_EVENTS:
            pi = gateway.get("payment_intents", obj["id"])
        else:
            charge_id = obj["id"] if kind == "charge.refunded" else obj.get("charge")
            if charge_id:
                charge = gateway.get("charges", charge_id)
                pi_id = charge["payment_intent"]
            else:
                pi_id = obj["payment_intent"]
            pi = gateway.get("payment_intents", pi_id)
        aid = pi.get("metadata", {}).get("attempt_id")
    try:
        attempt = db.get(StripeAttempt, UUID(aid))
    except (ValueError, TypeError):
        raise ValueError("Unknown attempt") from None
    if not attempt:
        raise ValueError("Unknown attempt")
    obligation = db.get(PaymentObligation, attempt.quote_id)
    # Match checkout's order->obligation lock order and serialize every event.
    item = db.scalar(
        select(Submission)
        .where(Submission.id == obligation.submission_id)
        .with_for_update()
    )
    db.refresh(attempt)
    previous_event = db.get(StripeEvidence, event["id"])
    digest = hashlib.sha256(
        json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if previous_event:
        if (
            previous_event.quote_id != attempt.quote_id
            or previous_event.data.get("event_digest") != digest
        ):
            raise ValueError("Provider event replay conflict")
        return
    obligation = accepted_obligation(db, item.id, attempt.quote_id, settings)
    if attempt.account_id != settings.stripe_account_id or not attempt.session_id:
        # Session creation may have reached Stripe but not our commit. Retry after
        # the durable attempt is reconciled by the same creation idempotency key.
        raise HTTPException(503, "stripe_attempt_recovery_required")
    session = gateway.get("checkout/sessions", attempt.session_id)
    validate_session(session, attempt, obligation, item)
    pi_id = session.get("payment_intent")
    if kind in PI_EVENTS | RESTRICTION_EVENTS and pi_id != pi.get("id"):
        raise ValueError("Cross-session payment")
    financial_restriction = kind in RESTRICTION_EVENTS
    charge = None
    if pi_id:
        pi = gateway.get("payment_intents", pi_id)
        if (
            pi.get("livemode") is not False
            or pi.get("metadata") != metadata(attempt, obligation, item)
            or pi.get("currency") != "eur"
            or pi.get("amount") != obligation.amount_minor
            or (attempt.payment_intent_id and attempt.payment_intent_id != pi_id)
        ):
            raise ValueError("PaymentIntent mismatch")
        attempt.payment_intent_id = pi_id
        charge = (
            gateway.get("charges", pi["latest_charge"])
            if pi.get("latest_charge")
            else None
        )
        if charge:
            if (
                charge.get("livemode") is not False
                or charge.get("payment_intent") != pi_id
                or charge.get("amount") != obligation.amount_minor
                or charge.get("currency") != "eur"
            ):
                raise ValueError("Charge mismatch")
            financial_restriction |= bool(
                charge.get("refunded")
                or charge.get("amount_refunded", 0)
                or charge.get("disputed")
            )
        settled = (
            session.get("payment_status") == "paid"
            and pi.get("status") == "succeeded"
            and pi.get("amount_received") == obligation.amount_minor
            and charge
            and charge.get("paid") is True
            and charge.get("captured") is True
        )
        if financial_restriction:
            settled = False
        if settled:
            # Retrieve the canonical succeeded event to use the provider's actual
            # success timestamp, even when an older failure event arrives later.
            existing = db.get(VerifiedPayment, attempt.quote_id)
            if not existing:
                success = (
                    event
                    if kind == "payment_intent.succeeded" and obj.get("id") == pi_id
                    else None
                )
                cursor = ""
                # Stripe Events are retained for 30 days. Failure to recover the
                # timestamp fails closed and requires operator reconciliation.
                for _ in range(20):
                    if success:
                        break
                    events = gateway.call(
                        "GET", "events?type=payment_intent.succeeded&limit=100" + cursor
                    )
                    success = next(
                        (
                            e
                            for e in events.get("data", [])
                            if e.get("livemode") is False
                            and e.get("account") in (None, settings.stripe_account_id)
                            and e.get("data", {}).get("object", {}).get("id") == pi_id
                        ),
                        None,
                    )
                    if not events.get("has_more") or not events.get("data"):
                        break
                    cursor = "&starting_after=" + events["data"][-1]["id"]
                if not success:
                    raise HTTPException(503, "stripe_settlement_timestamp_unavailable")
                confirmation = ProviderConfirmation(
                    attempt.quote_id,
                    "stripe_test",
                    success["id"],
                    pi_id,
                    obligation.amount_minor,
                    "EUR",
                    datetime.fromtimestamp(success["created"], timezone.utc),
                )
                record_provider_confirmation(db, b"", "", SettledVerifier(confirmation))
            attempt.status = "verified"
        elif not db.get(VerifiedPayment, attempt.quote_id):
            attempt.status = {
                "requires_action": "action_required",
                "requires_payment_method": "failed",
                "canceled": "cancelled",
            }.get(pi.get("status"), "pending")
            if (
                session.get("status") == "complete"
                and session.get("payment_status") == "unpaid"
                and pi.get("status") == "requires_action"
            ):
                # A completed Checkout cannot be resumed. Clear only the stale
                # navigation URL; keep financial state and confirmation unchanged.
                attempt.checkout_url = None
    elif session.get("status") == "expired":
        attempt.status = "expired"
    if financial_restriction or restricted(db, attempt.quote_id):
        attempt.status = "restricted"
    db.add(
        StripeEvidence(
            event_id=event["id"],
            quote_id=attempt.quote_id,
            kind=kind,
            restricted=financial_restriction,
            data={
                "session_id": attempt.session_id,
                "payment_intent_id": pi_id,
                "provider_created": event.get("created"),
                "event_digest": digest,
                "provider_object_id": obj.get("id"),
                "amount_refunded_minor": charge.get("amount_refunded", 0)
                if charge
                else None,
                "disputed": bool(charge and charge.get("disputed")),
                "obligation_amount_minor": obligation.amount_minor,
                "currency": obligation.currency,
            },
        )
    )
    db.flush()


def payment_state(db, qid):
    if restricted(db, qid):
        return "restricted"
    if db.get(VerifiedPayment, qid):
        return "verified"
    attempt = db.scalar(
        select(StripeAttempt)
        .where(StripeAttempt.quote_id == qid)
        .order_by(StripeAttempt.created_at.desc())
        .limit(1)
    )
    return attempt.status if attempt else "awaiting_payment"


def payment_review_required(db, qid):
    """Presentation hint, never a financial hold or a new payment status.

    Completed requires_action Checkouts lose their navigation URL at reconciliation.
    Conservatively require review whenever an action has no stored resume URL.
    Verified/restricted payments retain their existing presentation and handling.
    """
    if payment_state(db, qid) != "action_required":
        return False
    attempt = db.scalar(
        select(StripeAttempt)
        .where(StripeAttempt.quote_id == qid)
        .order_by(StripeAttempt.created_at.desc())
        .limit(1)
    )
    return bool(attempt and not attempt.checkout_url)


def financial_restrictions(db, qid):
    """Customer-safe labels; retain full evidence internally without exposing staff notes."""
    rows = db.scalars(
        select(StripeEvidence).where(
            StripeEvidence.quote_id == qid, StripeEvidence.restricted.is_(True)
        )
    ).all()
    labels = set()
    for evidence in rows:
        amount = evidence.data.get("amount_refunded_minor") or 0
        total = evidence.data.get("obligation_amount_minor") or 0
        if amount:
            labels.add(
                "refunded" if total and amount >= total else "partially_refunded"
            )
        if evidence.kind == "manual_commercial_hold":
            labels.add("commercial_hold")
        elif "dispute" in evidence.kind or evidence.data.get("disputed"):
            labels.add("dispute_review")
        elif not amount:
            labels.add("financial_review")
    # A later full refund subsumes earlier partial-refund observations.
    if "refunded" in labels:
        labels.discard("partially_refunded")
    return sorted(labels)
