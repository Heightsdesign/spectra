"""Synthetic Stripe transport only; guarded PostgreSQL fixtures."""

# ruff: noqa: F401,F811
import hashlib
import hmac
import json
import time
from copy import deepcopy
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from app.auth import now
from app.commercial import card_commercial_state
from app.commercial_models import (
    DispatchExpectation,
    PaymentObligation,
    VerifiedPayment,
)
from app.config import Settings
from app.pricing_models import QuoteAcceptance
from app.stripe_checkout import (
    handle_event,
    metadata,
    payment_state,
    signature_event,
    start_checkout,
)
from app.stripe_models import StripeAttempt, StripeEvidence
from app.submission_models import Submission
from fastapi import HTTPException
from sqlalchemy import func, select
from test_paid_order_foundation import additional, foundation, service_document
from test_pricing import pricing_api
from test_submissions import BASE, submissions_api


def configure(settings):
    settings.stripe_enabled = True
    settings.stripe_secret_key = "sk_test_SYNTHETIC"
    settings.stripe_webhook_secret = "whsec_SYNTHETIC"
    settings.stripe_account_id = "acct_SYNTHETIC"


class Gateway:
    def __init__(self, db):
        self.db = db
        self.objects = {}
        self.creates = []
        self.success = None
        self.wrong_account = False

    def account(self):
        if self.wrong_account:
            raise HTTPException(503, "stripe_account_mismatch")

    def get(self, resource, identifier):
        return deepcopy(self.objects[(resource, identifier)])

    def call(self, method, path, data=None, key=None):
        if method == "GET":
            return {"data": [self.success] if self.success else [], "has_more": False}
        self.creates.append((key, deepcopy(data)))
        attempt = self.db.scalar(
            select(StripeAttempt).where(StripeAttempt.status == "creating")
        )
        meta = {k[9:-1]: v for k, v in data.items() if k.startswith("metadata[")}
        session = {
            "id": "cs_test_" + attempt.id.hex,
            "livemode": False,
            "mode": "payment",
            "currency": "eur",
            "amount_total": int(data["line_items[0][price_data][unit_amount]"]),
            "client_reference_id": str(attempt.id),
            "metadata": meta,
            "status": "open",
            "payment_status": "unpaid",
            "payment_intent": None,
            "url": "https://checkout.stripe.com/c/pay/TEST",
        }
        self.objects[("checkout/sessions", session["id"])] = session
        return deepcopy(session)


def setup(foundation):
    client, db, settings, item, quote, actor = foundation
    configure(settings)
    gateway = Gateway(db)
    order = db.get(Submission, UUID(item["id"]))
    start_checkout(db, order, UUID(quote["id"]), settings, gateway)
    attempt = db.scalar(
        select(StripeAttempt).where(StripeAttempt.quote_id == UUID(quote["id"]))
    )
    return client, db, settings, item, quote, gateway, attempt


def outcome(gateway, attempt, status="succeeded"):
    session = gateway.objects[("checkout/sessions", attempt.session_id)]
    pi_id = "pi_" + attempt.id.hex
    session["payment_intent"] = pi_id
    session["status"] = "complete"
    session["payment_status"] = "paid" if status == "succeeded" else "unpaid"
    pi = {
        "id": pi_id,
        "livemode": False,
        "metadata": session["metadata"],
        "currency": "eur",
        "amount": session["amount_total"],
        "amount_received": session["amount_total"] if status == "succeeded" else 0,
        "status": status,
        "latest_charge": "ch_" + attempt.id.hex,
    }
    gateway.objects[("payment_intents", pi_id)] = pi
    gateway.objects[("charges", pi["latest_charge"])] = {
        "id": pi["latest_charge"],
        "livemode": False,
        "payment_intent": pi_id,
        "amount": pi["amount"],
        "currency": "eur",
        "paid": status == "succeeded",
        "captured": status == "succeeded",
        "amount_refunded": 0,
        "disputed": False,
    }
    gateway.success = event("payment_intent.succeeded", pi)
    # Timestamp must follow acceptance and not be in the future.
    return session, pi


def event(kind, obj):
    return {
        "id": "evt_" + uuid4().hex,
        "type": kind,
        "livemode": False,
        "created": int(time.time()),
        "data": {"object": deepcopy(obj)},
    }


def test_signature_raw_body_and_replay_window():
    raw = b'{"id":"evt_test", "livemode":false}'
    stamp = str(int(time.time()))
    digest = hmac.new(
        b"whsec_TEST", stamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    sig = f"t={stamp},v1={digest}"
    assert signature_event(raw, sig, "whsec_TEST")["id"] == "evt_test"
    for body, signature, secret in [
        (raw + b" ", sig, "whsec_TEST"),
        (raw, sig, "wrong"),
        (raw, "", "whsec_TEST"),
    ]:
        with pytest.raises(HTTPException):
            signature_event(body, signature, secret)
    with pytest.raises(HTTPException):
        signature_event(raw, sig, "whsec_TEST", timestamp=int(stamp) + 301)


def test_live_and_production_gate():
    with pytest.raises(ValueError):
        Settings(stripe_enabled=True, stripe_mode="live")
    with pytest.raises(ValueError):
        Settings(
            stripe_enabled=True,
            auth_environment="production",
            auth_origin="https://example.invalid",
        )


def test_creation_reuses_attempt_and_full_server_amount(foundation):
    client, db, settings, item, q, g, a = setup(foundation)
    order = db.get(Submission, UUID(item["id"]))
    start_checkout(db, order, UUID(q["id"]), settings, g)
    assert len(g.creates) == 1
    assert g.creates[0][1]["line_items[0][price_data][unit_amount]"] == str(
        q["snapshot"]["checkout"]["final_payable_minor"]
    )
    assert g.creates[0][0] == "selby-test-" + str(a.id)
    assert not db.get(VerifiedPayment, a.quote_id)
    assert not db.get(DispatchExpectation, order.id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount_total", 1),
        ("currency", "usd"),
        ("livemode", True),
        ("client_reference_id", "wrong"),
        ("metadata", {"quote_id": str(uuid4())}),
    ],
)
def test_wrong_session_fails_closed(foundation, field, value):
    client, db, s, item, q, g, a = setup(foundation)
    session, pi = outcome(g, a)
    session[field] = value
    with pytest.raises(ValueError):
        handle_event(db, event("checkout.session.completed", session), s, g)
    assert not db.get(VerifiedPayment, a.quote_id)


@pytest.mark.parametrize(
    "field,value",
    [("amount", 1), ("currency", "usd"), ("livemode", True), ("metadata", {})],
)
def test_wrong_pi_fails_closed(foundation, field, value):
    client, db, s, item, q, g, a = setup(foundation)
    session, pi = outcome(g, a)
    pi[field] = value
    with pytest.raises(ValueError):
        handle_event(db, event("checkout.session.completed", session), s, g)
    assert not db.get(VerifiedPayment, a.quote_id)


def test_async_failure_action_success_duplicate_out_of_order(foundation):
    client, db, s, item, q, g, a = setup(foundation)
    session, pi = outcome(g, a, "processing")
    handle_event(db, event("checkout.session.completed", session), s, g)
    assert payment_state(db, a.quote_id) == "pending"
    assert not db.get(VerifiedPayment, a.quote_id)
    pi["status"] = "requires_action"
    handle_event(db, event("payment_intent.requires_action", pi), s, g)
    assert payment_state(db, a.quote_id) == "action_required"
    pi["status"] = "requires_payment_method"
    failure = event("checkout.session.async_payment_failed", session)
    handle_event(db, failure, s, g)
    assert payment_state(db, a.quote_id) == "failed"
    session, pi = outcome(g, a)
    # Avoid second-truncation preceding same-second acceptance in synthetic data.
    g.success["created"] = now().timestamp()
    success = event("checkout.session.async_payment_succeeded", session)
    handle_event(db, success, s, g)
    handle_event(db, success, s, g)
    handle_event(db, failure, s, g)
    assert payment_state(db, a.quote_id) == "verified"
    assert db.scalar(select(func.count()).select_from(VerifiedPayment)) == 1
    assert db.scalar(select(func.count()).select_from(DispatchExpectation)) == 1


@pytest.mark.parametrize(
    "kind", ["charge.refunded", "charge.dispute.created", "refund.created"]
)
def test_restriction_before_success_never_cleared(foundation, kind):
    client, db, s, item, q, g, a = setup(foundation)
    session, pi = outcome(g, a)
    charge = g.objects[("charges", pi["latest_charge"])]
    obj = (
        charge
        if kind == "charge.refunded"
        else {"id": "re_TEST", "charge": charge["id"]}
    )
    handle_event(db, event(kind, obj), s, g)
    assert payment_state(db, a.quote_id) == "restricted"
    g.success["created"] = now().timestamp()
    handle_event(db, event("checkout.session.completed", session), s, g)
    assert payment_state(db, a.quote_id) == "restricted"
    with pytest.raises(HTTPException):
        start_checkout(db, db.get(Submission, UUID(item["id"])), a.quote_id, s, g)


def test_wrong_event_environment_and_account(foundation):
    client, db, s, item, q, g, a = setup(foundation)
    for change in ({"livemode": True}, {"account": "acct_WRONG"}):
        e = event("checkout.session.completed", {"id": a.session_id})
        e.update(change)
        with pytest.raises(ValueError):
            handle_event(db, e, s, g)
    g.wrong_account = True
    with pytest.raises(HTTPException):
        handle_event(
            db, event("checkout.session.completed", {"id": a.session_id}), s, g
        )


def test_http_tampering_ownership_status_and_hold(foundation, monkeypatch):
    client, db, s, item, q, g, a = setup(foundation)
    monkeypatch.setattr("app.stripe_api.StripeGateway", lambda settings: g)
    path = f"{BASE}/{item['id']}/stripe-checkout"
    for extra in ({"amount_minor": 1}, {"paid": True}, {"currency": "usd"}):
        assert client.post(path, json={"quote_id": q["id"], **extra}).status_code == 422
    assert client.post(path, json={"quote_id": str(uuid4())}).status_code == 409
    assert (
        client.post(
            f"{BASE}/{uuid4()}/stripe-checkout", json={"quote_id": q["id"]}
        ).status_code
        == 404
    )
    assert client.get(f"{BASE}/{uuid4()}/payments/{q['id']}").status_code == 404
    assert (
        client.post(
            "/api/stripe/webhook", content=b"{}", headers={"stripe-signature": "bad"}
        ).status_code
        == 400
    )
    hold = {"quote_id": q["id"], "reason": "TEST review", "request_key": str(uuid4())}
    route = f"/internal/intake/submissions/{item['id']}/payment-hold"
    assert client.post(route, json=hold).status_code == 200
    assert client.post(route, json=hold).status_code == 200
    assert (
        client.get(f"{BASE}/{item['id']}/commercial-state").json()["payment_status"]
        == "restricted"
    )


def test_expiry_requires_next_click_and_ambiguous_retry_blocks(foundation):
    client, db, s, item, q, g, a = setup(foundation)
    session = g.objects[("checkout/sessions", a.session_id)]
    session["status"] = "expired"
    handle_event(db, event("checkout.session.expired", session), s, g)
    assert payment_state(db, a.quote_id) == "expired"
    assert db.scalar(select(func.count()).select_from(StripeAttempt)) == 1


@pytest.fixture
def stripe_schema(test_engine, monkeypatch):
    """Private schema for independently committed race/migration tests."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from app.config import get_settings
    from sqlalchemy import create_engine, text

    schema = "stripe_test_" + uuid4().hex
    assert test_engine.url.database.endswith("_test")
    with test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    target = test_engine.url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(target)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        with monkeypatch.context() as env:
            env.setenv("DATABASE_URL", target.render_as_string(hide_password=False))
            get_settings.cache_clear()
            command.upgrade(config, "head")
            yield engine, config
    finally:
        get_settings.cache_clear()
        engine.dispose()
        with test_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def seed_order(engine):
    from app.customer_models import Customer
    from app.pricing_models import PricingCatalog, SubmissionQuote
    from sqlalchemy.orm import Session

    with Session(engine) as db:
        customer = Customer(
            email=uuid4().hex + "@example.invalid",
            password_hash="unused",
            first_name="TEST",
            last_name="Race",
            email_verified=True,
        )
        catalog = PricingCatalog(document={"synthetic_test_only": True})
        db.add_all([customer, catalog])
        db.flush()
        order = Submission(
            customer_id=customer.id,
            reference="SP-" + uuid4().hex.upper(),
            status="submitted",
        )
        db.add(order)
        db.flush()
        q = SubmissionQuote(
            submission_id=order.id,
            pricing_revision=1,
            catalog_version=catalog.version,
            snapshot={
                "commercial_terms_version": "TEST-ONLY",
                "checkout": {"final_payable_minor": 1234, "readiness": {"ready": True}},
            },
            created_at=now() - timedelta(minutes=2),
            expires_at=now() + timedelta(minutes=20),
        )
        db.add(q)
        db.flush()
        db.add(
            QuoteAcceptance(
                submission_id=order.id,
                quote_id=q.id,
                accepted_at=now() - timedelta(minutes=1),
            )
        )
        db.add(
            PaymentObligation(
                quote_id=q.id,
                submission_id=order.id,
                amount_minor=1234,
                currency="EUR",
                created_at=now() - timedelta(minutes=1),
            )
        )
        db.commit()
        return order.id, q.id


def test_concurrent_checkout_and_duplicate_webhook_connections(stripe_schema):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.orm import Session

    engine, config = stripe_schema
    sid, qid = seed_order(engine)
    settings = Settings()
    configure(settings)
    objects = {}
    creates = []
    barrier = Barrier(2)

    def checkout():
        with Session(engine) as db:
            gateway = Gateway(db)
            gateway.objects = objects
            gateway.creates = creates
            barrier.wait(timeout=10)
            order = db.scalar(
                select(Submission).where(Submission.id == sid).with_for_update()
            )
            return start_checkout(db, order, qid, settings, gateway)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: checkout(), range(2)))
    assert all(result["url"] for result in results)
    assert len(creates) == 1
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(StripeAttempt)) == 1
        a = db.scalar(select(StripeAttempt))
        gateway = Gateway(db)
        gateway.objects = objects
        session, pi = outcome(gateway, a)
        success = event("payment_intent.succeeded", pi)
    barrier = Barrier(2)

    def webhook():
        with Session(engine) as db:
            gateway = Gateway(db)
            gateway.objects = objects
            barrier.wait(timeout=10)
            handle_event(db, success, settings, gateway)
            db.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: webhook(), range(2)))
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(VerifiedPayment)) == 1
        assert db.scalar(select(func.count()).select_from(DispatchExpectation)) == 1
        assert db.scalar(select(func.count()).select_from(StripeEvidence)) == 1
        # Nonempty infrastructure downgrade must refuse destructive rollback.
        from alembic import command

        with pytest.raises(RuntimeError, match="financial history"):
            command.downgrade(config, "0014")


def test_ambiguous_network_retry_keeps_same_idempotency_key(foundation):
    client, db, s, item, q, actor = foundation
    configure(s)
    gateway = Gateway(db)
    original_call = gateway.call
    calls = []

    def uncertain(method, path, data=None, key=None):
        original_call(method, path, data, key)
        calls.append(key)
        raise HTTPException(503, "TEST connection lost after Stripe creation")

    gateway.call = uncertain
    order = db.get(Submission, UUID(item["id"]))
    with pytest.raises(HTTPException):
        start_checkout(db, order, UUID(q["id"]), s, gateway)
    db.rollback()
    attempt = db.scalar(
        select(StripeAttempt).where(StripeAttempt.quote_id == UUID(q["id"]))
    )
    assert attempt and attempt.session_id is None
    gateway.call = original_call
    start_checkout(db, order, UUID(q["id"]), s, gateway)
    assert all(key == calls[0] for key, data in gateway.creates)
    assert db.scalar(select(func.count()).select_from(StripeAttempt)) == 1


def test_supplement_checkout_separate_from_initial_and_restrictions(foundation):
    from app.commercial import assign_entitlement
    from app.intake_models import PhysicalCard
    from app.pricing_models import SubmissionQuote

    client, db, s, item, q, actor = foundation
    card, payload = additional(foundation)
    route = f"/internal/intake/submissions/{item['id']}/supplementary-quotes"
    response = client.post(route, json=payload)
    assert response.status_code == 201, response.text
    supplement = response.json()
    response = client.post(
        f"{BASE}/{item['id']}/supplementary-quotes/{supplement['id']}/accept",
        json={"accept_terms": True},
    )
    assert response.status_code == 200, response.text
    configure(s)
    gateway = Gateway(db)
    order = db.get(Submission, UUID(item["id"]))
    start_checkout(db, order, UUID(supplement["id"]), s, gateway)
    attempt = db.scalar(select(StripeAttempt))
    session, pi = outcome(gateway, attempt)
    gateway.success["created"] = now().timestamp()
    handle_event(db, event("checkout.session.completed", session), s, gateway)
    pc = db.get(PhysicalCard, UUID(card["id"]))
    quote = db.get(SubmissionQuote, UUID(supplement["id"]))
    assign_entitlement(db, pc, quote, str(pc.id), actor, "TEST assignment")
    assert not card_commercial_state(db, pc)["commercially_eligible"]
    assert (
        "original_shipping_payment_required" in card_commercial_state(db, pc)["reasons"]
    )
    assert not db.get(DispatchExpectation, order.id)


def test_signed_http_success_and_cross_customer_idor(
    foundation, submissions_api, monkeypatch
):
    client, db, settings, item, q, gateway, attempt = setup(foundation)
    session, pi = outcome(gateway, attempt)
    gateway.success["created"] = now().timestamp()
    monkeypatch.setattr("app.stripe_api.StripeGateway", lambda settings: gateway)
    e = event("checkout.session.completed", session)
    raw = json.dumps(e).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(
        settings.stripe_webhook_secret.encode(),
        stamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    # Stripe has neither a customer cookie nor browser CSRF headers.
    from app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as stripe:
        response = stripe.post(
            "/api/stripe/webhook",
            content=raw,
            headers={"stripe-signature": f"t={stamp},v1={signature}"},
        )
    assert response.status_code == 200, response.text
    assert payment_state(db, attempt.quote_id) == "verified"
    original = db.get(VerifiedPayment, attempt.quote_id)
    _, _, login = submissions_api
    login()
    for path in (
        f"{BASE}/{item['id']}/commercial-state",
        f"{BASE}/{item['id']}/payments/{q['id']}",
    ):
        assert client.get(path).status_code == 404
    assert (
        client.post(
            f"{BASE}/{item['id']}/stripe-checkout", json={"quote_id": q["id"]}
        ).status_code
        == 404
    )
    charge = gateway.objects[("charges", pi["latest_charge"])]
    charge["amount_refunded"] = 1
    handle_event(db, event("charge.refunded", charge), settings, gateway)
    assert payment_state(db, attempt.quote_id) == "restricted"
    assert db.get(VerifiedPayment, attempt.quote_id) == original
    from app.stripe_checkout import financial_restrictions

    assert "partially_refunded" in financial_restrictions(db, attempt.quote_id)
    charge["amount_refunded"] = charge["amount"]
    handle_event(db, event("charge.refunded", charge), settings, gateway)
    assert "refunded" in financial_restrictions(db, attempt.quote_id)
    assert "partially_refunded" not in financial_restrictions(db, attempt.quote_id)


@pytest.mark.parametrize("lost_cancel_response", [False, True])
def test_failed_async_retry_cancels_previous_pi_before_new_attempt(
    foundation, lost_cancel_response
):
    client, db, settings, item, q, gateway, attempt = setup(foundation)
    session, pi = outcome(gateway, attempt, "requires_payment_method")
    old_call = gateway.call

    def call(method, path, data=None, key=None):
        if path.endswith("/cancel"):
            pi["status"] = "canceled"
            if lost_cancel_response:
                raise HTTPException(503, "TEST cancellation response lost")
            return deepcopy(pi)
        return old_call(method, path, data, key)

    gateway.call = call
    order = db.get(Submission, UUID(item["id"]))
    if lost_cancel_response:
        with pytest.raises(HTTPException):
            start_checkout(db, order, attempt.quote_id, settings, gateway)
        db.rollback()
    result = start_checkout(db, order, attempt.quote_id, settings, gateway)
    assert result == {"status": "cancelled", "url": None}
    assert pi["status"] == "canceled"
    result = start_checkout(db, order, attempt.quote_id, settings, gateway)
    assert result["url"]
    assert len(gateway.creates) == 2
    assert gateway.creates[0][0] != gateway.creates[1][0]


def test_cross_order_pi_and_event_replay_conflict(foundation):
    client, db, settings, item, q, gateway, attempt = setup(foundation)
    session, pi = outcome(gateway, attempt, "processing")
    wrong = deepcopy(pi)
    wrong["id"] = "pi_OTHER_ORDER"
    gateway.objects[("payment_intents", wrong["id"])] = wrong
    with pytest.raises(ValueError, match="Cross-session"):
        handle_event(db, event("payment_intent.processing", wrong), settings, gateway)
    e = event("checkout.session.completed", session)
    handle_event(db, e, settings, gateway)
    replay = deepcopy(e)
    replay["created"] += 1
    with pytest.raises(ValueError, match="replay conflict"):
        handle_event(db, replay, settings, gateway)
