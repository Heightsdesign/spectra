"""Real independent PostgreSQL connections; never share a Session across threads."""
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from checkout_fixtures import configure_shipping, prepare_delivery
from app.checkout_models import ShippingState, ShippingConfiguration
from app.auth import csrf_value, digest, now
from app.config import Settings, get_settings
from app.customer_models import Customer, CustomerSession
from app.database import get_session
from app.main import app
from app.pricing_catalog import publish
from app.pricing_models import PricingCatalog, PricingState
from app.submission_models import Submission
from test_pricing import document, quote
from test_submissions import BASE, add, draft


@pytest.fixture
def concurrent_api(test_engine, tmp_path):
    settings = Settings(auth_mail_dir=tmp_path / "mail")
    versions = []
    with Session(test_engine) as db:
        shipping_previous = db.get(ShippingState, 1).current_version
        shipping_version = configure_shipping(db)
        state = db.get(PricingState, 1)
        previous = state.current_version
        record = publish(db, document(development_only=False, approval_reference="CONCURRENCY TEST FIXTURE"), settings)
        versions.append(record.version)
        customer = Customer(email=f"{uuid4().hex}@example.invalid", password_hash="unused", first_name="Test", last_name="Concurrent", email_verified=True)
        db.add(customer)
        db.flush()
        customer_id = customer.id
        raw = secrets.token_urlsafe(32)
        db.add(CustomerSession(customer_id=customer_id, token_hash=digest(raw), expires_at=now() + timedelta(hours=1)))
        db.commit()

    def sessions():
        with Session(test_engine) as db:
            yield db

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        with TestClient(app) as client:
            client.cookies.set("spectra_session", raw)
            client.headers.update({"Origin": settings.auth_origin, "X-Spectra-Client": "1", "X-CSRF-Token": csrf_value(raw)})
            yield client, settings, versions
    finally:
        app.dependency_overrides.clear()
        with Session(test_engine) as db:
            state = db.scalar(select(PricingState).where(PricingState.id == 1).with_for_update())
            if state.current_version in versions:
                state.current_version = previous
                db.flush()
            shipping_state = db.get(ShippingState, 1)
            shipping_state.current_version = shipping_previous
            db.flush()
            db.execute(delete(ShippingConfiguration).where(ShippingConfiguration.version == shipping_version))
            db.execute(delete(Submission).where(Submission.customer_id == customer_id))
            db.execute(delete(Customer).where(Customer.id == customer_id))
            db.execute(delete(PricingCatalog).where(PricingCatalog.version.in_(versions)))
            db.commit()


def race(*calls):
    barrier = Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(run, calls))


def test_concurrent_address_delivery_and_acceptance(concurrent_api):
    from checkout_fixtures import ADDRESS
    client, _, _ = concurrent_api
    item = add(client, draft(client))
    address = prepare_delivery(client, item)
    path = f"/api/addresses/{address['id']}"
    results = race(*[lambda: client.put(path, json={**ADDRESS, "version": 1, "city": "Changed"}) for _ in range(2)])
    assert sorted(r.status_code for r in results) == [200, 409]
    url = f"{BASE}/{item['id']}"
    payload = {"version": 1, "address_id": address['id'], "declared_value_minor": 10000, "service_id": "test-return"}
    results = race(*[lambda: client.put(url + "/delivery", json=payload) for _ in range(2)])
    assert sorted(r.status_code for r in results) == [200, 409]
    q = quote(client, item)
    item = client.post(url + "/confirm", json={"version": item['version']}).json()
    results = race(lambda: client.put(path, json={**ADDRESS,"version":2,"city":"Final"}),
                   lambda: client.post(url + f"/quotes/{q['id']}/accept", json={"version":item['version'],"accept_terms":True}))
    assert results[0].status_code == 200
    if results[1].status_code == 200:
        assert results[1].json()['snapshot'] == q['snapshot']
        assert client.get(url + "/order-summary").json()['return_address']['city'] == 'Changed'
    else:
        assert results[1].status_code == 409 and results[1].json()['detail'] == 'quote_stale'


def test_simultaneous_configurations_quote_generation_and_acceptance(concurrent_api):
    client, _, _ = concurrent_api
    item = add(client, draft(client))
    prepare_delivery(client, item)
    url = f"{BASE}/{item['id']}"
    def configure(tier):
        return client.patch(url + "/configuration", json={"version": item["version"], "processing_tier": tier, "upgrade_ids": ["classic"]})
    results = race(lambda: configure("express"), lambda: configure("priority"))
    assert sorted(r.status_code for r in results) == [200, 409]
    item = client.get(url).json()
    results = race(lambda: client.post(url + "/quotes", json={"version": item["version"]}), lambda: configure("standard"))
    assert results[1].status_code == 200
    item = client.get(url).json()
    if results[0].status_code == 201:
        old = results[0].json()
        assert client.get(url + "/quotes/" + old["id"]).json()["status"] == "invalidated"
    else:
        assert results[0].status_code == 409
    results = race(*[lambda: client.post(url + "/quotes", json={"version": item["version"]}) for _ in range(2)])
    assert all(r.status_code == 201 for r in results)
    q = results[0].json()
    assert results[1].json() == q
    item = client.post(url + "/confirm", json={"version": item["version"]}).json()
    results = race(*[lambda: client.post(url + f"/quotes/{q['id']}/accept", json={"version": item["version"], "accept_terms": True}) for _ in range(2)])
    assert all(r.status_code == 200 for r in results)
    assert results[0].json() == results[1].json()
    assert results[0].json()["status"] == "accepted"


def test_publication_and_acceptance_have_a_serial_order(concurrent_api, test_engine):
    client, settings, versions = concurrent_api
    item = add(client, draft(client), quantity=1)
    prepare_delivery(client, item)
    q = quote(client, item)
    url = f"{BASE}/{item['id']}"
    item = client.post(url + "/confirm", json={"version": item["version"]}).json()

    def replace_catalog():
        with Session(test_engine) as db:
            record = publish(db, document(development_only=False, approval_reference="CONCURRENCY TEST FIXTURE", base_price_minor=2000), settings)
            versions.append(record.version)
            db.commit()
            return record.version

    accepted, version = race(lambda: client.post(url + f"/quotes/{q['id']}/accept", json={"version": item["version"], "accept_terms": True}), replace_catalog)
    assert client.get(BASE + "/catalog").json()["version"] == str(version)
    historical = client.get(url + f"/quotes/{q['id']}").json()
    assert historical["snapshot"]["total_minor"] == 1000
    if accepted.status_code == 200:
        assert historical["status"] == "accepted"
    else:
        assert accepted.status_code == 409 and accepted.json()["detail"] == "quote_stale"
        assert historical["status"] == "catalog_changed"
