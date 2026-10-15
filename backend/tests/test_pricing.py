import copy
import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from checkout_fixtures import configure_shipping, prepare_delivery
from app.auth import now
from app.pricing import calculate, rounded_ratio
from app.pricing_catalog import publish
from app.pricing_models import PricingCatalog, QuoteAcceptance
from app.pricing_schemas import Catalog
from test_submissions import BASE, CARD, add, draft, submissions_api  # noqa: F401

EXAMPLE = Path(__file__).resolve().parents[1] / "pricing" / "development-example.json"


def document(**changes):
    return {**json.loads(EXAMPLE.read_text(encoding="utf-8")), "tax_validation_reference": "TEST ONLY tax validation", **changes}


def card(quantity=1, tier="standard", upgrades=None):
    return SimpleNamespace(id=uuid4(), **{**CARD, "quantity": quantity}, processing_tier=tier, upgrade_ids=upgrades or ["classic"])


@pytest.fixture
def pricing_api(submissions_api, api):
    client, db, login = submissions_api
    settings = api[2]
    record = publish(db, document(), settings)
    db.commit()
    return client, db, login, settings, record.version


def configured(client, item, tier="standard", upgrades=None, entry_id=None):
    url = f"{BASE}/{item['id']}"
    path = url + (f"/entries/{entry_id}" if entry_id else "") + "/configuration"
    response = client.patch(path, json={"version": item["version"], "processing_tier": tier, "upgrade_ids": upgrades or ["classic"]})
    assert response.status_code == 200, response.text
    return response.json()


def quote(client, item):
    response = client.post(f"{BASE}/{item['id']}/quotes", json={"version": item["version"]})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("tier,label,expected", [("standard", "classic", 1000), ("express", "classic", 1500), ("priority", "classic", 2000), ("standard", "detailed", 1300), ("express", "detailed", 1800), ("priority", "detailed", 2300)])
def test_every_tier_and_label(tier, label, expected):
    result = calculate(Catalog.model_validate(document()), [card(2, tier, [label])])
    assert result["total_minor"] == expected * 2
    assert result["lines"][0]["unit_minor"] == expected
    assert result["currency"] == "EUR"
    assert result["lines"][0]["estimated_turnaround"] is None


@pytest.mark.parametrize("mode,tax,net,total", [("exempt", 0, 17500, 17500), ("exclusive", 3500, 17500, 21000), ("inclusive", 2917, 14583, 17500)])
def test_mixed_quantities_discount_and_tax(mode, tax, net, total):
    config = Catalog.model_validate(document(tax_mode=mode, tax_rate_bps=0 if mode == "exempt" else 2000))
    result = calculate(config, [card(3, "express", ["detailed"]), card(7, "express", ["detailed"])])
    assert result["quantity"] == 10
    assert result["subtotal_minor"] == 18000
    assert result["discount_minor"] == 500
    assert result["discount"]["id"] == "example-bulk-10"
    assert (result["tax_minor"], result["net_minor"], result["total_minor"]) == (tax, net, total)
    assert sum(line["total_minor"] for line in result["lines"]) == total


def test_discounts_highest_threshold_nonstacking_and_scope():
    config = Catalog.model_validate(document(discounts=list(reversed(document()["discounts"]))))
    assert calculate(config, [card(9)])["discount"] is None
    assert calculate(config, [card(50)])["discount_minor"] == 5000
    assert calculate(config, [card(100)])["discount_minor"] == 10000
    config = Catalog.model_validate(document(discount_scope="all"))
    assert calculate(config, [card(10, "priority", ["detailed"])])["discount_minor"] == 1150


def test_half_up_rounding_at_entry_boundary():
    config = Catalog.model_validate(document(base_price_minor=101, discount_scope="all", discounts=[{"id": "half", "min_quantity": 1, "rate_bps": 5000}], tax_mode="exclusive", tax_rate_bps=1000))
    result = calculate(config, [card()])
    assert (result["discount_minor"], result["net_minor"], result["tax_minor"], result["total_minor"]) == (51, 50, 5, 55)
    assert calculate(config, [card(), card()])["total_minor"] == 110
    assert calculate(config, [card(2)])["total_minor"] == 111
    assert rounded_ratio(1, 5000) == 1


def test_catalog_localization_turnaround_and_no_prices_in_logic(pricing_api):
    client, db, _, settings, version = pricing_api
    response = client.get(BASE + "/catalog")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    catalog = response.json()
    assert catalog["version"] == str(version)
    assert list(catalog["tiers"]) == ["standard", "express", "priority"]
    assert all(v["estimated_turnaround"] is None for v in catalog["tiers"].values())
    assert "approval_reference" not in catalog
    changed = document(base_price_minor=777)
    changed["tiers"]["standard"]["estimated_turnaround"] = {"FR": "Estimation configurée", "EN": "Configured estimate"}
    publish(db, changed, settings)
    db.commit()
    item = add(client, draft(client), quantity=1)
    snapshot = quote(client, item)["snapshot"]
    assert snapshot["total_minor"] == 777
    assert snapshot["lines"][0]["estimated_turnaround"]["EN"] == "Configured estimate"


def test_per_card_apply_all_preserves_card_data_and_legacy_updates(pricing_api):
    client, _, _, _, _ = pricing_api
    item = add(client, add(client, draft(client)), game="naruto", card_name="Naruto", quantity=3)
    first = next(c for c in item["entries"] if c["card_name"] == "Pikachu")
    second = next(c for c in item["entries"] if c["card_name"] == "Naruto")
    changed = configured(client, item, "priority", ["detailed"], first["id"])
    assert next(c for c in changed["entries"] if c["id"] == first["id"])["processing_tier"] == "priority"
    assert next(c for c in changed["entries"] if c["id"] == second["id"])["processing_tier"] == "standard"
    q = quote(client, changed)
    assert q["snapshot"]["total_minor"] == 2 * 2300 + 3 * 1000
    # Old W3.1 clients can edit descriptions without resetting selected options.
    response = client.put(f"{BASE}/{item['id']}/entries/{first['id']}", json={**CARD, "card_name": "Raichu", "version": changed["version"]})
    assert response.status_code == 200
    changed = response.json()
    assert next(c for c in changed["entries"] if c["id"] == first["id"])["upgrade_ids"] == ["detailed"]
    changed = configured(client, changed, "express")
    assert all(c["processing_tier"] == "express" and c["upgrade_ids"] == ["classic"] for c in changed["entries"])
    assert next(c for c in changed["entries"] if c["id"] == second["id"])["card_name"] == second["card_name"]


@pytest.mark.parametrize("action", ["notes", "add", "edit", "delete", "configuration", "all"])
def test_quote_invalidation_on_every_draft_change(pricing_api, action):
    client, _, _, _, _ = pricing_api
    item = add(client, draft(client))
    q = quote(client, item)
    url = f"{BASE}/{item['id']}"
    entry = item["entries"][0]["id"]
    if action == "notes":
        response = client.patch(url, json={"version": item["version"], "notes": "new"})
    elif action == "add":
        response = client.post(url + "/entries", json={**CARD, "version": item["version"]})
    elif action == "edit":
        response = client.put(url + "/entries/" + entry, json={**CARD, "quantity": 5, "version": item["version"]})
    elif action == "delete":
        response = client.request("DELETE", url + "/entries/" + entry, json={"version": item["version"]})
    else:
        response = client.patch(url + ("/entries/" + entry if action == "configuration" else "") + "/configuration", json={"version": item["version"], "processing_tier": "express", "upgrade_ids": ["detailed"]})
    assert response.status_code in (200, 201)
    old = client.get(url + "/quotes/" + q["id"]).json()
    assert old["status"] == "invalidated"
    assert old["snapshot"] == q["snapshot"]
    if action != "delete":
        assert quote(client, response.json())["id"] != q["id"]


def test_confirmation_is_not_acceptance_and_examples_cannot_be_accepted(pricing_api):
    client, db, _, _, _ = pricing_api
    item = add(client, draft(client))
    q = quote(client, item)
    url = f"{BASE}/{item['id']}"
    assert client.post(url + f"/quotes/{q['id']}/accept", json={"version": item["version"], "accept_terms": True}).status_code == 409
    response = client.post(url + "/confirm", json={"version": item["version"]})
    assert response.status_code == 200
    item = response.json()
    assert db.scalar(select(QuoteAcceptance)) is None
    assert client.get(url + "/quotes/" + q["id"]).json()["status"] == "valid"
    assert quote(client, item)["id"] == q["id"]
    response = client.post(url + f"/quotes/{q['id']}/accept", json={"version": item["version"], "accept_terms": True})
    assert response.status_code == 409 and response.json()["detail"] == "example_terms_not_acceptable"
    assert client.patch(url + "/configuration", json={"version": item["version"], "processing_tier": "express", "upgrade_ids": ["classic"]}).status_code == 409


def test_expiration_and_historical_prices(pricing_api, monkeypatch):
    client, db, _, settings, _ = pricing_api
    item = add(client, draft(client))
    old = quote(client, item)
    url = f"{BASE}/{item['id']}/quotes/{old['id']}"
    publish(db, document(base_price_minor=9999), settings)
    db.commit()
    changed = client.get(url).json()
    assert changed["status"] == "catalog_changed"
    assert changed["snapshot"] == old["snapshot"]
    fresh = quote(client, item)
    assert fresh["snapshot"]["total_minor"] == 2 * 9999
    monkeypatch.setattr("app.pricing_api.now", lambda: now() + timedelta(days=8))
    assert client.get(f"{BASE}/{item['id']}/quotes/{fresh['id']}").json()["status"] == "expired"
    assert quote(client, item)["id"] != fresh["id"]


def test_approved_terms_acceptance_retry_and_immutability(pricing_api, monkeypatch):
    client, db, _, settings, _ = pricing_api
    publish(db, document(development_only=False, approval_reference="TEST-ONLY approval fixture"), settings)
    db.commit()
    item = add(client, draft(client))
    configure_shipping(db)
    prepare_delivery(client, item)
    q = quote(client, item)
    url = f"{BASE}/{item['id']}"
    item = client.post(url + "/confirm", json={"version": item["version"]}).json()
    body = {"version": item["version"], "accept_terms": True}
    accept_url = url + f"/quotes/{q['id']}/accept"
    assert client.post(accept_url, json={**body, "accept_terms": False}).status_code == 422
    response = client.post(accept_url, json=body)
    assert response.status_code == 200
    accepted = response.json()
    assert accepted["status"] == "accepted" and accepted["accepted_at"]
    assert client.get(url).json() == item  # Acceptance never rewrites the submission.
    publish(db, document(base_price_minor=3333), settings)
    db.commit()
    monkeypatch.setattr("app.pricing_api.now", lambda: now() + timedelta(days=8))
    assert client.post(accept_url, json=body).json() == accepted
    assert client.get(url + f"/quotes/{q['id']}").json() == accepted
    assert client.post(url + "/quotes", json={"version": item["version"]}).status_code == 409
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE submission_quotes SET snapshot = '{}'::jsonb WHERE id = :id"), {"id": UUID(q["id"])})
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE quote_acceptances SET accepted_at = now() WHERE submission_id = :id"), {"id": UUID(item["id"])})
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text("UPDATE pricing_catalogs SET document = '{}'::jsonb WHERE version = :id"), {"id": UUID(q["pricing_configuration_version"])})


@pytest.mark.parametrize("tier,upgrades,detail", [("invalid", ["classic"], "option_unavailable"), ("standard", ["invalid"], "option_unavailable"), ("standard", ["classic", "detailed"], "options_incompatible"), ("standard", ["classic", "classic"], "options_incompatible"), ("standard", [], "invalid_input")])
def test_invalid_configurations(pricing_api, tier, upgrades, detail):
    client, _, _, _, _ = pricing_api
    item = add(client, draft(client))
    response = client.patch(f"{BASE}/{item['id']}/configuration", json={"version": item["version"], "processing_tier": tier, "upgrade_ids": upgrades})
    assert response.status_code == 422 and response.json()["detail"] == detail


def test_unavailable_and_extensible_incompatible_upgrades(pricing_api):
    client, db, _, settings, _ = pricing_api
    item = add(client, draft(client))
    config = document()
    config["tiers"]["priority"]["available"] = False
    config["groups"]["extra"] = {"min_selected": 0, "max_selected": 3}
    config["upgrades"]["future"] = {**copy.deepcopy(config["upgrades"]["detailed"]), "group": "extra", "incompatible_with": ["detailed"], "allowed_tiers": ["express"]}
    config["upgrades"]["detailed"]["available"] = False
    publish(db, config, settings)
    db.commit()
    url = f"{BASE}/{item['id']}/configuration"
    for tier, upgrades in [("priority", ["classic"]), ("standard", ["detailed"]), ("standard", ["classic", "future"])]:
        assert client.patch(url, json={"version": item["version"], "processing_tier": tier, "upgrade_ids": upgrades}).status_code == 422
    config["upgrades"]["detailed"]["available"] = True
    publish(db, config, settings)
    db.commit()
    assert client.patch(url, json={"version": item["version"], "processing_tier": "express", "upgrade_ids": ["detailed", "future"]}).status_code == 422
    item = configured(client, item, "express", ["classic", "future"])
    assert quote(client, item)["snapshot"]["total_minor"] == 2 * 1800


def test_security_ownership_csrf_and_price_manipulation(pricing_api):
    client, _, login, _, _ = pricing_api
    item = add(client, draft(client))
    q = quote(client, item)
    url = f"{BASE}/{item['id']}"
    entry_id = item["entries"][0]["id"]
    body = {"version": item["version"], "processing_tier": "express", "upgrade_ids": ["classic"]}
    for extra in ({"price": 1}, {"total_minor": 0}, {"customer_id": str(uuid4())}, {"discount": 100}):
        assert client.patch(url + "/configuration", json={**body, **extra}).status_code == 422
    assert client.post(url + "/quotes", json={"version": item["version"], "total_minor": 0}).status_code == 422
    operations = [("PATCH", url + "/configuration", body), ("PATCH", url + f"/entries/{entry_id}/configuration", body), ("POST", url + "/quotes", {"version": item["version"]}), ("POST", url + f"/quotes/{q['id']}/accept", {"version": item["version"], "accept_terms": True})]
    for method, path, payload in operations:
        assert client.request(method, path, json=payload, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    login()
    for method, path, payload in operations + [("GET", url + "/quotes", None), ("GET", url + f"/quotes/{q['id']}", None)]:
        assert client.request(method, path, json=payload).status_code == 404
    client.cookies.clear()
    for method, path, payload in operations + [("GET", BASE + "/catalog", None), ("GET", url + "/quotes", None), ("GET", url + f"/quotes/{q['id']}", None)]:
        assert client.request(method, path, json=payload).status_code == 401


def test_stale_versions_quotes_and_missing_catalog(submissions_api, api):
    client, db, _ = submissions_api
    item = add(client, draft(client))
    url = f"{BASE}/{item['id']}"
    assert client.get(BASE + "/catalog").status_code == 503
    assert client.post(url + "/quotes", json={"version": item["version"]}).status_code == 503
    publish(db, document(), api[2])
    db.commit()
    item = configured(client, item)
    assert client.post(url + "/quotes", json={"version": item["version"] - 1}).status_code == 409
    assert client.patch(url + "/configuration", json={"version": item["version"] - 1, "processing_tier": "standard", "upgrade_ids": ["classic"]}).status_code == 409
    assert client.get(url + "/quotes/" + str(uuid4())).status_code == 404


def test_production_blocks_example_pricing(pricing_api):
    client, db, _, settings, _ = pricing_api
    item = add(client, draft(client))
    settings.auth_environment = "production"
    with pytest.raises(ValueError, match="Development example"):
        publish(db, document(), settings)
    # Test current_catalog directly; production cookie name deliberately differs.
    from app.pricing import current_catalog
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        current_catalog(db, settings)
    assert error.value.status_code == 503


@pytest.mark.parametrize("reason", ["expired", "invalidated", "catalog_changed"])
def test_commercial_acceptance_rejects_stale_quote(pricing_api, monkeypatch, reason):
    client, db, _, settings, _ = pricing_api
    publish(db, document(development_only=False, approval_reference="TEST fixture"), settings)
    db.commit()
    item = add(client, draft(client))
    q = quote(client, item)
    url = f"{BASE}/{item['id']}"
    if reason == "invalidated":
        item = configured(client, item, "express")
    item = client.post(url + "/confirm", json={"version": item["version"]}).json()
    if reason == "catalog_changed":
        publish(db, document(development_only=False, approval_reference="TEST fixture", base_price_minor=999), settings)
        db.commit()
    if reason == "expired":
        monkeypatch.setattr("app.pricing_api.now", lambda: now() + timedelta(days=8))
    response = client.post(url + f"/quotes/{q['id']}/accept", json={"version": item["version"], "accept_terms": True})
    assert response.status_code == 409 and response.json()["detail"] == "quote_stale"
    assert db.get(QuoteAcceptance, UUID(item["id"])) is None


def test_confirm_rejects_newly_unavailable_configuration(pricing_api):
    client, db, _, settings, _ = pricing_api
    item = configured(client, add(client, draft(client)), "express")
    changed = document()
    changed["tiers"]["express"]["available"] = False
    publish(db, changed, settings)
    db.commit()
    response = client.post(f"{BASE}/{item['id']}/confirm", json={"version": item["version"]})
    assert response.status_code == 422
    assert client.get(f"{BASE}/{item['id']}").json()["status"] == "draft"


def test_quote_must_belong_to_requested_submission(pricing_api):
    client, _, _, _, _ = pricing_api
    first = add(client, draft(client))
    second = add(client, draft(client))
    q = quote(client, first)
    url = f"{BASE}/{second['id']}/quotes/{q['id']}"
    assert client.get(url).status_code == 404
    assert client.post(url + "/accept", json={"version": second["version"], "accept_terms": True}).status_code == 404


@pytest.mark.parametrize("change", [{"base_price_minor": 1.5}, {"base_price_minor": -1}, {"tax_rate_bps": 10001}, {"tax_mode": "exempt", "tax_rate_bps": 1}, {"development_only": False}, {"currency": "USD"}, {"quote_lifetime_seconds": 0}, {"discounts": [{"id": "a", "min_quantity": 1, "rate_bps": 100}, {"id": "b", "min_quantity": 1, "rate_bps": 200}]}])
def test_invalid_operator_configuration(change):
    with pytest.raises(ValidationError):
        Catalog.model_validate(document(**change))
