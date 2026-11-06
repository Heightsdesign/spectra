"""Distinct declared copies, PostgreSQL reservation and immutable SP/PC boundaries."""
# ruff: noqa: F811

import base64
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy import select
from test_pricing import (
    configured,
    pricing_api,  # noqa: F401
    quote,
)
from test_submission_photos import image_data
from test_submissions import (
    BASE,
    CARD,
    add,
    draft,
    submissions_api,  # noqa: F401
)

from app.intake_models import StaffMembership
from app.library_models import CopyAssignment
from app.submission_models import Submission

LIB = "/api/library/copies"
DECL = {k: v for k, v in CARD.items() if k not in ("quantity",)}


def create(client, **changes):
    result = client.post(LIB, json={**DECL, **changes})
    assert result.status_code == 201, result.text
    return result.json()


def assign(client, item, copy):
    return client.post(
        f"{BASE}/{item['id']}/library-copies",
        json={"version": item["version"], "copy_id": copy["id"]},
    )


def test_standalone_and_identical_copies_assignment_release_reassign(submissions_api):
    client, db, _ = submissions_api
    first = create(client, expansion="", card_number="")
    second = create(client, expansion="", card_number="")
    assert (
        first["id"] != second["id"]
        and first["available"]
        and not first["identity_verified"]
    )
    one = draft(client)
    two = draft(client)
    one = assign(client, one, first).json()
    assert one["card_count"] == 1 and one["entries"][0]["quantity"] == 1
    assert one["entries"][0]["owned_copy_id"] == first["id"]
    assert assign(client, two, first).status_code == 409
    two = assign(client, two, second).json()
    eid = one["entries"][0]["id"]
    assert (
        client.put(
            f"{BASE}/{one['id']}/entries/{eid}",
            json={**CARD, "version": one["version"]},
        ).status_code
        == 409
    )
    assert (
        client.put(
            f"{LIB}/{first['id']}", json={**DECL, "version": first["version"]}
        ).status_code
        == 409
    )
    removed = client.request(
        "DELETE", f"{BASE}/{one['id']}/entries/{eid}", json={"version": one["version"]}
    ).json()
    assert removed["card_count"] == 0
    assert assign(client, two, first).status_code == 201
    history = list(
        db.scalars(
            select(CopyAssignment).where(CopyAssignment.copy_id == UUID(first["id"]))
        )
    )
    assert len(history) == 2 and sum(a.released_at is None for a in history) == 1


def test_register_in_order_quantity_and_pricing_revision(submissions_api):
    client, db, _ = submissions_api
    item = draft(client)
    response = client.post(
        f"{BASE}/{item['id']}/library-register",
        json={**CARD, "quantity": 3, "version": item["version"]},
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["card_count"] == 3 and len(item["entries"]) == 3
    assert len({e["owned_copy_id"] for e in item["entries"]}) == 3
    assert all(
        e["quantity"] == 1 and e["processing_tier"] == "standard"
        for e in item["entries"]
    )
    assert db.get(Submission, UUID(item["id"])).pricing_revision == 2
    assert (
        client.post(
            f"{BASE}/{item['id']}/library-register", json={**CARD, "version": 1}
        ).status_code
        == 409
    )
    assert len(client.get(LIB).json()["items"]) == 3


def test_confirmed_immutability_ownership_and_legacy_compatibility(submissions_api):
    client, _db, login = submissions_api
    old = add(client, draft(client), quantity=4)
    copy = create(client)
    item = assign(client, draft(client), copy).json()
    confirmed = client.post(
        f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}
    ).json()
    assert (
        client.request(
            "DELETE",
            f"{BASE}/{item['id']}/entries/{item['entries'][0]['id']}",
            json={"version": confirmed["version"]},
        ).status_code
        == 409
    )
    assert assign(client, draft(client), copy).status_code == 409
    assert client.get(f"{BASE}/{item['id']}").json() == confirmed
    assert client.get(f"{BASE}/{old['id']}").json()["entries"][0]["quantity"] == 4
    assert (
        client.get(f"{BASE}/{old['id']}").json()["entries"][0].get("owned_copy_id")
        is None
    )
    login()
    assert client.get(LIB).json()["items"] == []
    assert assign(client, draft(client), copy).status_code == 404
    assert (
        client.put(f"{LIB}/{copy['id']}", json={**DECL, "version": 1}).status_code
        == 404
    )


def test_search_pagination_and_private_photo_snapshot(submissions_api):
    client, _db, login = submissions_api
    copy = create(client)
    create(client, card_name="Other")
    assert len(client.get(LIB + "?search=Pika&limit=1").json()["items"]) == 1
    assert client.get(LIB + "?limit=1").json()["has_more"]
    assert len(client.get(LIB + "?offset=1&limit=1").json()["items"]) == 1
    assert client.get(LIB + "?limit=101").status_code == 422
    data = image_data()
    photo = client.post(
        f"{LIB}/{copy['id']}/photos",
        json={
            "version": copy["version"],
            "side": "front",
            "filename": "front.png",
            "data": base64.b64encode(data).decode(),
        },
    )
    assert photo.status_code == 201, photo.text
    copy = photo.json()
    item = assign(client, draft(client), copy).json()
    snapshot = item["entries"][0]["pre_shipment_photos"][0]
    assert snapshot["sha256"] == copy["pre_shipment_photos"][0]["sha256"]
    assert snapshot["id"] != copy["pre_shipment_photos"][0]["id"]
    assert snapshot["uploaded_at"] == copy["pre_shipment_photos"][0]["uploaded_at"]
    assert not snapshot["identity_verified"]
    confirmed = client.post(
        f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}
    ).json()
    assert confirmed["status"] == "submitted"
    assert (
        client.get(
            f"{BASE}/{item['id']}/entries/{item['entries'][0]['id']}/photos/{snapshot['id']}"
        ).content
        == data
    )
    url = f"{LIB}/{copy['id']}/photos/{copy['pre_shipment_photos'][0]['id']}"
    assert client.get(url).headers["cache-control"] == "private, no-store"
    login()
    assert client.get(url).status_code == 404


def test_snapshot_failure_rolls_back_assignment_and_copy(submissions_api):
    client, _db, _ = submissions_api
    copy = create(client)
    item = draft(client)
    with patch(
        "app.library.clone_photos", side_effect=OSError("Synthetic storage failure")
    ):
        assert assign(client, item, copy).status_code == 503
    assert client.get(LIB).json()["items"][0]["available"]
    assert client.get(f"{BASE}/{item['id']}").json()["card_count"] == 0


@pytest.mark.parametrize("inspection_started", [False, True])
def test_workstation_intake_and_explicit_admin_return_history(
    submissions_api, inspection_started
):
    client, db, _ = submissions_api
    copy = create(client)
    original = image_data("red")
    copy = client.post(
        f"{LIB}/{copy['id']}/photos",
        json={
            "version": copy["version"],
            "side": "front",
            "filename": "original.png",
            "data": base64.b64encode(original).decode(),
        },
    ).json()
    item = assign(client, draft(client), copy).json()
    item = client.post(
        f"{BASE}/{item['id']}/confirm", json={"version": item["version"]}
    ).json()
    actor = db.get(Submission, UUID(item["id"])).customer_id
    db.add(StaffMembership(customer_id=actor, role="admin"))
    db.commit()
    path = f"/internal/intake/submissions/{item['id']}"
    from uuid import uuid4

    parcel = client.post(path + "/parcels", json={"request_key": str(uuid4())}).json()
    returned = f"{path}/library-copies/{copy['id']}/return"
    assert (
        client.post(
            returned, json={"reason": "Actual physical return confirmed"}
        ).status_code
        == 409
    )
    for action in ("override", "begin"):
        assert (
            client.post(
                path + "/transition",
                json={"action": action, "reason": "Synthetic custody decision"},
            ).status_code
            == 200
        )
    card = client.post(
        path + "/cards", json={"request_key": str(uuid4()), "parcel_id": parcel["id"]}
    ).json()
    assert (
        client.post(
            path + f"/cards/{card['id']}/match",
            json={
                "entry_id": item["entries"][0]["id"],
                "reason": "Specific copy verified",
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            path + "/transition",
            json={"action": "complete", "reason": "Reconciled copy"},
        ).status_code
        == 200
    )
    preview = client.get(path).json()
    assert preview["received_quantity"] == preview["declared_quantity"] == 1
    assert preview["cards"][0]["reference"].startswith("PC-")
    db.get(StaffMembership, actor).role = "operator"
    db.commit()
    assert client.post(returned, json={"reason": "Actual return"}).status_code == 403
    db.get(StaffMembership, actor).role = "admin"
    db.commit()
    if inspection_started:
        from app.inspection_models import Inspection

        db.add(Inspection(physical_card_id=UUID(card["id"]), started_by=actor))
        db.commit()
        assert (
            client.post(
                returned, json={"reason": "Cannot release inspection evidence"}
            ).status_code
            == 409
        )
        assert not next(
            c for c in client.get(LIB).json()["items"] if c["id"] == copy["id"]
        )["available"]
        return
    assert (
        client.post(
            returned, json={"reason": "Actual physical return confirmed"}
        ).status_code
        == 200
    )
    assert client.post(returned, json={"reason": "Retry"}).status_code == 200
    assert client.get(f"{BASE}/{item['id']}").json() == item
    copy = client.put(
        f"{LIB}/{copy['id']}",
        json={
            **DECL,
            "version": copy["version"],
            "card_name": "Updated after actual return",
        },
    ).json()
    copy = client.post(
        f"{LIB}/{copy['id']}/photos",
        json={
            "version": copy["version"],
            "side": "front",
            "filename": "later.png",
            "data": base64.b64encode(image_data("blue")).decode(),
        },
    ).json()
    assert client.get(f"{BASE}/{item['id']}").json() == item
    old_photo = item["entries"][0]["pre_shipment_photos"][0]
    assert (
        client.get(
            f"{BASE}/{item['id']}/entries/{item['entries'][0]['id']}/photos/{old_photo['id']}"
        ).content
        == original
    )
    assert assign(client, draft(client), copy).status_code == 201
    lookup = client.get(
        "/internal/inspection/lookup", params={"reference": card["reference"]}
    ).json()
    assert "customer_copy_returned" in {
        r["code"] for r in lookup["eligibility"]["start"]["reasons"]
    }


def test_same_catalog_printing_can_have_distinct_copies_in_different_orders(
    submissions_api,
):
    from test_tcg_catalog import seed

    from app.tcg_models import CatalogCard

    client, db, _ = submissions_api
    expansion = seed(db)
    card = db.scalar(
        select(CatalogCard).where(CatalogCard.expansion_id == expansion.id)
    )
    values = {
        "catalog_card_id": str(card.id),
        "card_name": card.name,
        "expansion": expansion.name,
        "card_number": card.collector_number,
        "language": "fr",
    }
    copies = [create(client, **values), create(client, **values)]
    assert copies[0]["catalog_card_id"] == copies[1]["catalog_card_id"]
    assert copies[0]["id"] != copies[1]["id"]
    assert all(
        assign(client, draft(client), copy).status_code == 201 for copy in copies
    )


def test_assignment_inherits_quote_configuration_and_invalidates_quote(pricing_api):
    client, _, _, _, _ = pricing_api
    item = add(client, draft(client), quantity=2)
    item = configured(client, item, "priority", ["detailed"])
    before = quote(client, item)
    copy = create(client)
    item = assign(client, item, copy).json()
    assert item["card_count"] == 3
    assert all(
        e["processing_tier"] == "priority" and e["upgrade_ids"] == ["detailed"]
        for e in item["entries"]
    )
    assert (
        client.get(f"{BASE}/{item['id']}/quotes/{before['id']}").json()["status"]
        == "invalidated"
    )
    assert quote(client, item)["snapshot"]["total_minor"] == 3 * 2300
    target = next(e for e in item["entries"] if e.get("owned_copy_id"))
    item = client.request(
        "DELETE",
        f"{BASE}/{item['id']}/entries/{target['id']}",
        json={"version": item["version"]},
    ).json()
    assert (
        item["card_count"] == 2
        and quote(client, item)["snapshot"]["total_minor"] == 2 * 2300
    )
