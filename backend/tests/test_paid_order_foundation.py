"""V0.6a: real PostgreSQL, synthetic catalog/provider, no production payments."""

# ruff: noqa: F401, F811 -- imported pytest fixtures
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app.auth import now
from app.checkout import shipping_amounts
from app.checkout_schemas import ShippingCatalog
from app.commercial import (
    ProviderConfirmation,
    assign_entitlement,
    card_commercial_state,
    dispatch_deadline,
    dispatch_indicators,
    notification_hooks,
    record_provider_confirmation,
    state,
)
from app.commercial_models import (
    CommercialEvent,
    DispatchExpectation,
    PaymentObligation,
    SupplementaryAcceptance,
    VerifiedPayment,
)
from app.inspection_models import Inspection
from app.intake_models import Discrepancy, IntakeAudit, PhysicalCard, StaffMembership
from app.pricing import calculate
from app.pricing_catalog import publish
from app.pricing_models import QuoteAcceptance, SubmissionQuote
from app.pricing_schemas import Catalog
from app.shipping_catalog import publish as shipping_publish
from app.submission_models import Submission
from checkout_fixtures import ADDRESS, prepare_delivery, shipping_document
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from test_intake import action, begin, issue, parcel, url
from test_intake import card as receive_card
from test_pricing import card, document, pricing_api, quote
from test_submissions import BASE, add, draft, submissions_api


def service_document(**changes):
    result = document(
        schema_version=2,
        development_only=False,
        approval_reference="SYNTHETIC APPROVAL ONLY",
        commercial_terms_version="SYNTHETIC-TERMS-06A",
        base_price_minor=0,
        discounts=[],
        volume_prices=[],
        tax_mode="pending",
        tax_rate_bps=0,
    )
    for index, (key, tier) in enumerate(result["tiers"].items()):
        tier.update(
            name={"FR": "Service TEST " + key, "EN": "TEST service " + key},
            price_minor=1200 + index * 800,
            tax={
                "mode": "inclusive" if index == 0 else "exclusive",
                "rate_bps": 2000 if index == 0 else 1000,
                "validation_reference": "TEST TAX EVIDENCE",
            },
        )
    return {**result, **changes}


@pytest.fixture
def foundation(pricing_api, request):
    client, db, login, settings, _ = pricing_api
    publish(db, service_document(), settings)
    shipping = shipping_document()
    shipping["services"]["test-return"]["additional_card_charge_minor"] = 300
    shipping_publish(db, shipping)
    db.commit()
    item = add(
        client,
        draft(client),
        quantity=getattr(request, "param", 2),
        processing_tier="standard",
        upgrade_ids=["classic"],
    )
    item = add(
        client, item, quantity=1, processing_tier="express", upgrade_ids=["classic"]
    )
    prepare_delivery(client, item)
    q = quote(client, item)
    item = client.post(
        f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}
    ).json()
    accepted = client.post(
        f"{BASE}/{item['id']}/quotes/{q['id']}/accept",
        json={"version": item["version"], "accept_terms": True},
    )
    assert accepted.status_code == 200, accepted.text
    actor = db.get(Submission, UUID(item["id"])).customer_id
    db.add(StaffMembership(customer_id=actor, role="admin"))
    db.commit()
    return client, db, settings, item, accepted.json(), actor


class SyntheticVerifier:
    def __init__(self, confirmation):
        self.confirmation = confirmation

    def verify(self, raw, signature):
        if raw != b"SYNTHETIC TEST ONLY" or signature != "test-signature":
            raise ValueError("Invalid signature")
        return self.confirmation


def verify(db, qid, **changes):
    obligation = db.get(PaymentObligation, UUID(str(qid)))
    values = dict(
        quote_id=obligation.quote_id,
        provider="synthetic-test-only",
        event_id=str(uuid4()),
        payment_id=str(uuid4()),
        amount_minor=obligation.amount_minor,
        currency="EUR",
        paid_at=now(),
    )
    confirmation = ProviderConfirmation(**{**values, **changes})
    return record_provider_confirmation(
        db, b"SYNTHETIC TEST ONLY", "test-signature", SyntheticVerifier(confirmation)
    )


def additional(foundation):
    client, db, settings, item, q, actor = foundation
    p, _ = parcel(client, item)
    begin(client, item)
    c, _ = receive_card(client, item, p["id"])
    issue(client, item, kind="unexpected", card_id=c["id"])
    payload = {
        "physical_card_id": c["id"],
        "processing_tier": "express",
        "shipping_service_id": "test-return",
        "declared_value_minor": 1000,
        "parcel": {},
        "reason": "Explicit TEST additional card pricing",
    }
    return c, payload


def test_complete_immutable_mixed_quote_and_unpaid_acceptance(foundation):
    client, db, settings, item, q, actor = foundation
    snapshot = q["snapshot"]
    assert {line["service_id"] for line in snapshot["lines"]} == {"standard", "express"}
    assert snapshot["checkout"]["final_payable_minor"] == 5834
    assert snapshot["checkout"]["tax_total_minor"] == 600
    assert snapshot["checkout"]["net_total_minor"] == 5234
    assert snapshot["checkout"]["line_items"][-1]["kind"] == "return_shipping"
    assert sum(len(line["card_keys"]) for line in snapshot["lines"]) == 3
    obligation = db.get(PaymentObligation, UUID(q["id"]))
    assert obligation.amount_minor == 5834
    assert db.get(VerifiedPayment, UUID(q["id"])) is None
    assert db.get(DispatchExpectation, UUID(item["id"])) is None
    result = client.get(f"{BASE}/{item['id']}/commercial-state").json()
    assert (
        result["payment_status"] == "awaiting_payment"
        and result["dispatch_deadline"] is None
    )
    changed = service_document(commercial_terms_version="SYNTHETIC-TERMS-CHANGED")
    changed["tiers"]["standard"].update(price_minor=9999, available=False)
    publish(db, changed, settings)
    db.commit()
    assert (
        client.get(f"{BASE}/{item['id']}/quotes/{q['id']}").json()["snapshot"]
        == snapshot
    )
    assert (
        client.get(f"{BASE}/{item['id']}/order-summary").json()["final_payable_minor"]
        == 5834
    )
    assert (
        client.post(f"{BASE}/{item['id']}/payments", json={"paid": True}).status_code
        == 404
    )
    assert (
        client.post(
            f"{BASE}/{item['id']}/quotes/{q['id']}/accept",
            json={"version": item["version"], "accept_terms": True, "paid": True},
        ).status_code
        == 422
    )


@pytest.mark.parametrize("tier", ["unknown", "bad/id", "priority"])
def test_invalid_disabled_services(pricing_api, tier):
    client, db, _, settings, _ = pricing_api
    config = service_document()
    config["tiers"]["priority"]["available"] = False
    publish(db, config, settings)
    db.commit()
    item = add(client, draft(client), quantity=1)
    response = client.patch(
        f"{BASE}/{item['id']}/entries/{item['entries'][0]['id']}/configuration",
        json={
            "version": item["version"],
            "processing_tier": tier,
            "upgrade_ids": ["classic"],
        },
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "mode,net,tax,total",
    [
        ("inclusive", 1000, 200, 1200),
        ("exclusive", 1200, 240, 1440),
        ("exempt", 1200, 0, 1200),
    ],
)
def test_explicit_service_and_shipping_tax(mode, net, tax, total):
    config = service_document()
    config["tiers"]["standard"]["tax"].update(
        mode=mode, rate_bps=0 if mode == "exempt" else 2000
    )
    result = calculate(Catalog.model_validate(config), [card(1)])
    assert (result["net_minor"], result["tax_minor"], result["total_minor"]) == (
        net,
        tax,
        total,
    )
    assert shipping_amounts(1200, mode, 0 if mode == "exempt" else 2000) == dict(
        charge_minor=total, net_minor=net, tax_minor=tax, configured_price_minor=1200
    )


@pytest.mark.parametrize("mutation", ["missing", "inactive", "count", "coverage"])
def test_shipping_fail_closed(pricing_api, mutation):
    client, db, _, settings, _ = pricing_api
    publish(db, service_document(), settings)
    config = shipping_document()
    service = config["services"]["test-return"]
    if mutation == "missing":
        config["services"] = {}
    if mutation == "inactive":
        service["available"] = False
    if mutation == "count":
        service["max_cards"] = 1
    if mutation == "coverage":
        service["coverage_minor"] = 1
    shipping_publish(db, config)
    db.commit()
    item = add(client, draft(client), quantity=2)
    address = client.post("/api/addresses", json=ADDRESS).json()
    result = client.put(
        f"{BASE}/{item['id']}/delivery",
        json={
            "version": 0,
            "address_id": address["id"],
            "declared_value_minor": 10000,
            "service_id": "test-return" if mutation in ("count", "coverage") else None,
        },
    )
    assert result.status_code == 200
    assert result.json()["final_payable_minor"] is None
    assert not result.json()["readiness"]["ready"]


def test_unknown_shipping_price_and_tax_never_become_zero():
    config = shipping_document()
    del config["services"]["test-return"]["charge_minor"]
    with pytest.raises(ValidationError):
        ShippingCatalog.model_validate(config)
    config = shipping_document()
    config["services"]["test-return"]["tax_mode"] = "exempt"
    config["services"]["test-return"]["tax_rate_bps"] = 2000
    with pytest.raises(ValidationError):
        ShippingCatalog.model_validate(config)


@pytest.mark.parametrize(
    "paid,expected",
    [
        ("2026-01-31T12:00:00+00:00", "2026-03-02T12:00:00+00:00"),
        ("2026-12-20T12:00:00+00:00", "2027-01-19T12:00:00+00:00"),
        ("2028-02-01T12:00:00+00:00", "2028-03-02T12:00:00+00:00"),
    ],
)
def test_calendar_deadline_across_months_years(paid, expected):
    assert dispatch_deadline(datetime.fromisoformat(paid)) == datetime.fromisoformat(
        expected
    )


def test_verified_provider_seam_replay_amount_and_clock(foundation):
    client, db, _, item, q, _ = foundation
    with pytest.raises(ValueError):
        verify(db, q["id"], amount_minor=1)
    with pytest.raises(ValueError):
        verify(db, q["id"], currency="USD")
    with pytest.raises(ValueError):
        verify(db, q["id"], paid_at=now() + timedelta(days=1))
    verified = verify(db, q["id"])
    db.flush()
    expectation = db.get(DispatchExpectation, UUID(item["id"]))
    assert expectation.dispatch_deadline == verified.verified_at + timedelta(days=30)
    assert verify(db, q["id"], payment_id=verified.provider_payment_id) is verified
    with pytest.raises(ValueError):
        verify(db, q["id"], payment_id="different")
    assert (
        client.get(f"{BASE}/{item['id']}/commercial-state").json()["payment_status"]
        == "verified"
    )
    before = item["status"]
    late = state(
        db,
        db.get(Submission, UUID(item["id"])),
        timestamp=expectation.dispatch_deadline + timedelta(days=10),
    )
    assert "dispatch_deadline_passed" in late["indicators"]
    assert db.get(Submission, UUID(item["id"])).status == before
    assert db.scalar(select(func.count()).select_from(Discrepancy)) == 0
    hooks = notification_hooks(
        db,
        db.get(Submission, UUID(item["id"])),
        timestamp=expectation.dispatch_deadline - timedelta(days=1),
        approaching_days=2,
    )
    assert hooks[0]["kind"] == "dispatch_deadline_approaching"


def test_customer_dispatch_declaration_is_unverified_idempotent_and_multiple(
    foundation,
):
    client, db, _, item, q, _ = foundation
    path = f"{BASE}/{item['id']}/shipment-declarations"
    payload = {
        "request_key": str(uuid4()),
        "carrier": "TEST carrier",
        "tracking": "TEST tracking",
        "declared_dispatch_at": None,
    }
    assert client.post(path, json=payload).status_code == 409
    verify(db, q["id"])
    db.flush()
    result = client.post(path, json=payload)
    assert result.status_code == 201, result.text
    assert result.json()["parcel_receipts"] == []
    assert (
        result.json()["shipment_declarations"][0]["verification"]
        == "customer_declared_only"
    )
    assert len(client.post(path, json=payload).json()["shipment_declarations"]) == 1
    assert (
        client.post(path, json={**payload, "tracking": "different"}).status_code == 409
    )
    assert (
        len(
            client.post(path, json={**payload, "request_key": str(uuid4())}).json()[
                "shipment_declarations"
            ]
        )
        == 2
    )
    p1, _ = parcel(client, item)
    p2, _ = parcel(client, item)
    current = client.get(f"{BASE}/{item['id']}/commercial-state").json()
    assert (
        len(current["parcel_receipts"]) == 2
        and "parcel_received" in current["indicators"]
    )
    result = client.post(
        url(item) + "/dispatch-review",
        json={
            "manual_review_required": True,
            "reason": "Explicit TEST operational review",
        },
    )
    assert "manual_review_required" in result.json()["indicators"]


def test_additional_card_requires_own_acceptance_payment_and_explicit_assignment(
    foundation,
):
    client, db, settings, item, original, actor = foundation
    c, payload = additional(foundation)
    pc = db.get(PhysicalCard, UUID(c["id"]))
    verify(db, original["id"])
    db.flush()
    assert not card_commercial_state(db, pc)["commercially_eligible"]
    initial_snapshot = deepcopy(db.get(SubmissionQuote, UUID(original["id"])).snapshot)
    audit_count = db.scalar(select(func.count()).select_from(IntakeAudit))
    response = client.post(url(item) + "/supplementary-quotes", json=payload)
    assert response.status_code == 201, response.text
    extra = response.json()
    extra_id = UUID(extra["id"])
    assert extra["snapshot"]["checkout"]["shipping"]["charge_minor"] == 300
    assert extra["snapshot"]["checkout"]["final_payable_minor"] == 2500
    accept_path = f"{BASE}/{item['id']}/supplementary-quotes/{extra['id']}/accept"
    assert client.post(accept_path, json={"accept_terms": False}).status_code == 422
    response = client.post(accept_path, json={"accept_terms": True})
    assert response.status_code == 200, response.text
    assert (
        client.post(accept_path, json={"accept_terms": True}).json() == response.json()
    )
    assignment = client.post(
        url(item) + "/commercial-assignment",
        json={
            "physical_card_id": c["id"],
            "quote_id": extra["id"],
            "card_key": c["id"],
            "reason": "Explicit TEST assignment",
        },
    )
    assert assignment.status_code == 200, assignment.text
    assert not assignment.json()["commercially_eligible"]
    assert db.get(VerifiedPayment, extra_id) is None
    verify(db, extra_id)
    db.flush()
    assert card_commercial_state(db, pc)["commercially_eligible"]
    assert db.get(SubmissionQuote, UUID(original["id"])).snapshot == initial_snapshot
    assert db.scalar(select(func.count()).select_from(IntakeAudit)) == audit_count
    assert db.scalar(select(func.count()).select_from(Inspection)) == 0
    assert pc.status == "unidentified" and pc.grading_card_id is None
    # The established inspection provider is still unavailable in V0.6a.
    lookup = client.get(
        "/internal/inspection/lookup", params={"reference": pc.reference}
    ).json()
    assert not lookup["eligibility"]["start"]["eligible"]
    assert "payment_unverified" in [
        r["code"] for r in lookup["eligibility"]["start"]["reasons"]
    ]


def test_supplement_rate_must_be_explicit_and_prior_acceptance_invalidates_competing_quotes(
    foundation,
):
    client, db, _, item, _, _ = foundation
    c, payload = additional(foundation)
    config = shipping_document()
    shipping_publish(db, config)
    db.commit()
    result = client.post(url(item) + "/supplementary-quotes", json=payload)
    assert (
        result.status_code == 409
        and result.json()["detail"] == "supplement_shipping_rate_required"
    )
    config["services"]["test-return"]["additional_card_charge_minor"] = 0
    shipping_publish(db, config)
    db.commit()
    first = client.post(url(item) + "/supplementary-quotes", json=payload).json()
    assert first["snapshot"]["checkout"]["shipping"]["charge_minor"] == 0
    p, _ = parcel(client, item)
    assert action(client, item, "begin").status_code == 200
    second_card, _ = receive_card(client, item, p["id"])
    issue(client, item, kind="unexpected", card_id=second_card["id"])
    second = client.post(
        url(item) + "/supplementary-quotes",
        json={**payload, "physical_card_id": second_card["id"]},
    ).json()
    assert (
        client.post(
            f"{BASE}/{item['id']}/supplementary-quotes/{first['id']}/accept",
            json={"accept_terms": True},
        ).status_code
        == 200
    )
    stale = client.post(
        f"{BASE}/{item['id']}/supplementary-quotes/{second['id']}/accept",
        json={"accept_terms": True},
    )
    assert stale.status_code == 409 and stale.json()["detail"] == "quote_stale"


def test_immutable_financial_rows_and_no_backfilled_payments(foundation):
    _, db, _, item, q, _ = foundation
    for table, identifier in [("payment_obligations", "quote_id")]:
        with pytest.raises(DBAPIError), db.begin_nested():
            db.execute(
                text(f"UPDATE {table} SET amount_minor=0 WHERE {identifier}=:id"),
                {"id": q["id"]},
            )
    assert db.scalar(select(func.count()).select_from(VerifiedPayment)) == 0
    assert db.get(DispatchExpectation, UUID(item["id"])) is None


def test_arbitrary_configured_service_identifier_requires_explicit_draft_selection(
    pricing_api,
):
    client, db, _, settings, _ = pricing_api
    config = service_document()
    config["tiers"] = {"approved-test-service": config["tiers"]["standard"]}
    shipping_publish(db, shipping_document())
    publish(db, config, settings)
    db.commit()
    item = add(client, draft(client), quantity=1)
    assert item["entries"][0]["processing_tier"] == ""
    summary = client.get(f"{BASE}/{item['id']}/order-summary").json()
    assert "service_selection_required" in summary["readiness"]["states"]
    assert (
        client.post(
            f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}
        ).status_code
        == 422
    )
    result = client.patch(
        f"{BASE}/{item['id']}/entries/{item['entries'][0]['id']}/configuration",
        json={
            "version": item["version"],
            "processing_tier": "approved-test-service",
            "upgrade_ids": ["classic"],
        },
    )
    assert result.status_code == 200, result.text
    item = result.json()
    prepare_delivery(client, item)
    assert (
        quote(client, item)["snapshot"]["lines"][0]["service_id"]
        == "approved-test-service"
    )


def test_destination_change_invalidates_unaccepted_quote_but_preserves_accepted_destination(
    foundation,
):
    client, db, _, accepted_item, accepted_q, _ = foundation
    original = client.get(f"{BASE}/{accepted_item['id']}/order-summary").json()
    address = original["return_address"]
    changed = client.put(
        "/api/addresses/" + address["id"],
        json={**ADDRESS, "version": address["version"], "country": "DE"},
    )
    assert changed.status_code == 200
    assert (
        client.get(f"{BASE}/{accepted_item['id']}/order-summary").json()[
            "return_address"
        ]["country"]
        == "FR"
    )
    item = add(
        client,
        draft(client),
        quantity=1,
        processing_tier="standard",
        upgrade_ids=["classic"],
    )
    new_address = prepare_delivery(client, item)
    q = quote(client, item)
    assert (
        client.put(
            "/api/addresses/" + new_address["id"],
            json={**ADDRESS, "version": new_address["version"], "country": "DE"},
        ).status_code
        == 200
    )
    assert (
        client.get(f"{BASE}/{item['id']}/quotes/{q['id']}").json()["status"]
        == "invalidated"
    )
    item = client.post(
        f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}
    ).json()
    assert (
        client.post(
            f"{BASE}/{item['id']}/quotes/{q['id']}/accept",
            json={"version": item["version"], "accept_terms": True},
        ).status_code
        == 409
    )
    assert db.get(VerifiedPayment, UUID(accepted_q["id"])) is None


@pytest.mark.parametrize("foundation", [4], indirect=True)
def test_five_paid_three_received_missing_requires_explicit_reconciliation(foundation):
    from test_intake import close

    client, db, _, item, q, actor = foundation
    assert item["card_count"] == 5
    verify(db, q["id"])
    db.flush()
    amount = db.get(PaymentObligation, UUID(q["id"])).amount_minor
    p, _ = parcel(client, item)
    begin(client, item)
    standard = next(e for e in item["entries"] if e["processing_tier"] == "standard")
    express = next(e for e in item["entries"] if e["processing_tier"] == "express")
    pcs = []
    for index in range(3):
        pc, _ = receive_card(client, item, p["id"])
        pcs.append(pc)
        assert (
            client.post(
                url(item) + "/cards/" + pc["id"] + "/match",
                json={"entry_id": standard["id"], "reason": "Explicit TEST copy match"},
            ).status_code
            == 200
        )
    assert db.scalar(select(func.count()).select_from(Discrepancy)) == 0
    assert action(client, item, "complete").json()["detail"] == "quantity_unreconciled"
    for entry in (standard, express):
        missing = issue(client, item, kind="missing", entry_id=entry["id"], quantity=1)
        assert close(client, item, missing).status_code == 200
    assert action(client, item, "complete").status_code == 200
    assert db.get(PaymentObligation, UUID(q["id"])).amount_minor == amount
    assert db.get(SubmissionQuote, UUID(q["id"])).snapshot == q["snapshot"]
    assert db.scalar(select(func.count()).select_from(PhysicalCard)) == 3
    for pc in pcs:
        result = client.get(
            "/internal/inspection/lookup", params={"reference": pc["reference"]}
        ).json()
        assert not result["eligibility"]["start"][
            "eligible"
        ]  # Provider remains unavailable.
    assert db.scalar(select(func.count()).select_from(Inspection)) == 0


def test_no_signature_bypass_and_owner_staff_boundaries(foundation, submissions_api):
    client, db, _, item, q, _ = foundation
    with pytest.raises(ValueError):
        record_provider_confirmation(db, b"unverified", "bad", SyntheticVerifier(None))

    class NotVerified:
        def verify(self, *args):
            return {"paid": True}

    with pytest.raises(ValueError):
        record_provider_confirmation(db, b"json", "bad", NotVerified())
    assert db.get(VerifiedPayment, UUID(q["id"])) is None
    submissions_api[2]()
    assert client.get(f"{BASE}/{item['id']}/commercial-state").status_code == 404
    assert client.get(f"{BASE}/{item['id']}/supplementary-quotes").status_code == 404
    assert (
        client.post(
            url(item) + "/dispatch-review",
            json={"manual_review_required": True, "reason": "Not staff"},
        ).status_code
        == 403
    )


def test_supplement_cannot_rely_on_unpaid_original_shipping(foundation):
    client, db, _, item, original, actor = foundation
    c, payload = additional(foundation)
    quote_response = client.post(url(item) + "/supplementary-quotes", json=payload)
    assert quote_response.status_code == 201, quote_response.text
    extra = quote_response.json()
    assert (
        client.post(
            f"{BASE}/{item['id']}/supplementary-quotes/{extra['id']}/accept",
            json={"accept_terms": True},
        ).status_code
        == 200
    )
    pc = db.get(PhysicalCard, UUID(c["id"]))
    assign_entitlement(
        db,
        pc,
        db.get(SubmissionQuote, UUID(extra["id"])),
        c["id"],
        actor,
        "Explicit TEST assignment",
    )
    verify(db, extra["id"])
    db.flush()
    assert (
        "original_shipping_payment_required" in card_commercial_state(db, pc)["reasons"]
    )
    assert db.get(DispatchExpectation, UUID(item["id"])) is None
    verify(db, original["id"])
    db.flush()
    assert card_commercial_state(db, pc)["commercially_eligible"]
    assert db.get(DispatchExpectation, UUID(item["id"])) is not None


def test_unpaid_receipt_preserves_independent_custody_indicators(foundation):
    client, db, _, item, q, _ = foundation
    parcel(client, item)
    value = client.get(f"{BASE}/{item['id']}/commercial-state").json()
    assert "awaiting_verified_payment" in value["indicators"]
    assert "parcel_received" in value["indicators"]
    assert value["dispatch_deadline"] is None
    assert db.get(VerifiedPayment, UUID(q["id"])) is None


def test_unselected_service_cannot_be_confirmed_if_catalog_becomes_unavailable(
    pricing_api,
):
    from app.pricing_models import PricingState

    client, db, _, settings, _ = pricing_api
    publish(db, service_document(), settings)
    db.commit()
    item = add(client, draft(client), quantity=1)
    assert item["entries"][0]["processing_tier"] == ""
    db.get(PricingState, 1).current_version = None
    db.commit()
    result = client.post(
        f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}
    )
    assert result.status_code == 422
    assert result.json()["detail"] == "service_selection_required"
    assert client.get(f"{BASE}/{item['id']}").json()["status"] == "draft"
