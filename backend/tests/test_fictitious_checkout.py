"""Fictitious documents only in the guarded, transaction-isolated test database."""
# ruff: noqa: F401,F811
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.checkout import shipping_config
from app.commercial_models import PaymentObligation, VerifiedPayment
from app.config import Settings
from app.fictitious_checkout import require_snapshot
from app.pricing import current_catalog
from app.pricing_catalog import publish
from app.pricing_models import SubmissionQuote
from app.pricing_schemas import Catalog
from app.shipping_catalog import publish as publish_shipping
from app.stripe_checkout import accepted_obligation
from test_pricing import document, pricing_api, quote
from test_submissions import BASE, add, draft, submissions_api
from test_stripe_checkout import Gateway, configure
from checkout_fixtures import ADDRESS


def documents():
    root = Path(__file__).resolve().parents[1] / "pricing"
    return tuple(json.loads((root / f"fictitious-stripe-test-{kind}.json").read_text(encoding="utf-8"))
                 for kind in ("pricing", "shipping"))


def enable(settings):
    configure(settings)
    settings.stripe_fictitious_enabled = True


def ready(pricing_api):
    client, db, _, settings, _ = pricing_api
    enable(settings)
    pricing, shipping = documents()
    publish(db, pricing, settings)
    publish_shipping(db, shipping, settings)
    db.commit()
    item = add(client, draft(client), quantity=2)
    address = client.post("/api/addresses", json=ADDRESS).json()
    response = client.put(f"{BASE}/{item['id']}/delivery", json={
        "version": 0, "address_id": address["id"], "declared_value_minor": 10000,
        "service_id": "fictitious-test-return-fr"})
    assert response.status_code == 200, response.text
    return client, db, settings, item, response.json()


def test_fictitious_exact_total_acceptance_and_checkout(pricing_api, monkeypatch):
    client, db, settings, item, summary = ready(pricing_api)
    assert summary["readiness"]["ready"] is True
    assert summary["stripe_test_only"] is True
    assert summary["grading"]["development_only"] is True
    assert summary["grading"]["total_minor"] == 2000
    assert summary["shipping"]["charge_minor"] == 500
    assert summary["tax_total_minor"] == 0
    assert summary["final_payable_minor"] == 2500
    q = quote(client, item)
    accept = f"{BASE}/{item['id']}/quotes/{q['id']}/accept"
    assert client.post(accept, json={"version": item["version"], "accept_terms": True}).status_code == 409
    item = client.post(f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}).json()
    assert client.post(accept, json={"version": item["version"], "accept_terms": False}).status_code == 422
    response = client.post(accept, json={"version": item["version"], "accept_terms": True})
    assert response.status_code == 200, response.text
    qid = UUID(q["id"])
    assert db.get(PaymentObligation, qid).amount_minor == 2500
    gateway = Gateway(db)
    monkeypatch.setattr("app.stripe_api.StripeGateway", lambda settings: gateway)
    path = f"{BASE}/{item['id']}/stripe-checkout"
    first = client.post(path, json={"quote_id": str(qid)})
    assert first.status_code == 200, first.text
    assert first.json()["url"].startswith("https://checkout.stripe.com/")
    assert client.post(path, json={"quote_id": str(qid)}).json() == first.json()
    assert len(gateway.creates) == 1
    assert gateway.creates[0][1]["line_items[0][price_data][unit_amount]"] == "2500"
    assert db.get(VerifiedPayment, qid) is None
    assert db.get(SubmissionQuote, qid).snapshot == q["snapshot"]
    settings.stripe_fictitious_enabled = False
    assert client.post(path, json={"quote_id": str(qid)}).status_code == 503
    with pytest.raises(HTTPException):
        accepted_obligation(db, UUID(item["id"]), qid, settings)


@pytest.mark.parametrize("change", [
    {"stripe_fictitious_enabled": False}, {"stripe_enabled": False},
    {"stripe_mode": "live"}, {"auth_environment": "production"},
    {"stripe_secret_key": "sk_live_FORBIDDEN"},
])
def test_publication_and_active_reads_fail_closed(pricing_api, change):
    _, db, _, settings, _ = pricing_api
    enable(settings)
    pricing, shipping = documents()
    publish(db, pricing, settings)
    publish_shipping(db, shipping, settings)
    db.commit()
    # Deliberately bypass Settings assignment validation to exercise runtime gates too.
    for key, value in change.items():
        setattr(settings, key, value)
    for action in (
        lambda: publish(db, pricing, settings),
        lambda: publish_shipping(db, shipping, settings),
        lambda: current_catalog(db, settings),
        lambda: shipping_config(db, settings),
        lambda: require_snapshot({"checkout": {"stripe_test_only": True}}, settings),
    ):
        with pytest.raises((HTTPException, ValueError)):
            action()


def test_ordinary_development_catalog_still_not_acceptable(pricing_api):
    client, db, settings, item, _ = ready(pricing_api)
    # Even with the explicit TEST opt-in, an ordinary example is not upgraded.
    publish(db, document(), settings)
    db.commit()
    summary = client.get(f"{BASE}/{item['id']}/order-summary").json()
    assert "development_rates" in summary["readiness"]["states"]
    assert summary["final_payable_minor"] is None
    q = quote(client, item)
    item = client.post(f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}).json()
    response = client.post(f"{BASE}/{item['id']}/quotes/{q['id']}/accept", json={
        "version": item["version"], "accept_terms": True})
    assert response.status_code == 409
    assert response.json()["detail"] == "example_terms_not_acceptable"


def test_fictitious_catalog_cannot_claim_commercial_status():
    pricing, _ = documents()
    with pytest.raises(ValidationError):
        Catalog.model_validate({**pricing, "development_only": False, "approval_reference": "fake"})


def test_publication_preserves_existing_order_and_quote(pricing_api):
    client, db, _, settings, _ = pricing_api
    item = add(client, draft(client))
    old_quote = quote(client, item)
    enable(settings)
    pricing, shipping = documents()
    publish(db, pricing, settings)
    publish_shipping(db, shipping, settings)
    db.commit()
    db.expire_all()
    assert client.get(f"{BASE}/{item['id']}").json() == item
    assert db.get(SubmissionQuote, UUID(old_quote["id"])).snapshot == old_quote["snapshot"]
    assert client.get(f"{BASE}/{item['id']}/quotes/{old_quote['id']}").json()["status"] == "catalog_changed"


def test_production_configuration_rejects_fictitious_activation():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, stripe_fictitious_enabled=True, stripe_enabled=False,
                 auth_environment="production", auth_origin="https://example.com")
