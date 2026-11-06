"""SQLite migration, atomic allocation, explicit adoption, immutable identity constraints."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest

from selby_workstation.orders import OrderStore
from selby_workstation.production import BridgeConflict, ProductionStore


@pytest.fixture
def bridge(tmp_path):
    store = ProductionStore(tmp_path / "orders.sqlite3")
    sid, eid, pid = str(uuid4()), str(uuid4()), str(uuid4())
    data = {
        "submission": {
            "id": sid,
            "reference": "SP-" + sid.replace("-", "").upper(),
            "customer_name": "Synthetic",
            "status": "reconciled",
            "entries": [{"id": eid, "card_name": "Same name", "quantity": 2}],
            "cards": [
                {
                    "id": str(uuid4()),
                    "reference": "PC-" + uuid4().hex.upper(),
                    "entry_id": eid,
                    "parcel_id": pid,
                }
                for _ in range(2)
            ],
        },
        "actor": {"id": str(uuid4()), "role": "admin"},
        "preparation": {"eligible": True, "reasons": []},
        "binding": {
            "registry_id": store.registry_id,
            "mode": "create",
            "local_order_id": None,
            "cards": {},
        },
    }
    return store, data


def test_atomic_retry_restart_and_confirmation(bridge):
    store, data = bridge
    first = store.apply("http://local", data, "Verified copies")
    assert len(set(first["cards"].values())) == 2 and not first["confirmed"]
    reopened = ProductionStore(store.path)
    assert reopened.registry_id == store.registry_id
    assert reopened.apply("http://local", data, "Retry") == first
    ready = deepcopy(data)
    ready["binding"].update(local_order_id=first["order_id"], cards=first["cards"])
    mapped = reopened.confirm("http://local", ready, "Backend confirmed")
    assert mapped["confirmed"]
    reopened.confirm("http://local", ready, "Repeat")
    assert len(store.history(first["order_id"])) == 2
    assert OrderStore(store.path).get_order(first["order_id"])["card_count"] == 2
    with store.connection() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_mid_transaction_failure_rolls_back_ids_and_mappings(bridge, monkeypatch):
    store, data = bridge
    original = store._event
    monkeypatch.setattr(
        store, "_event", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted"))
    )
    with pytest.raises(RuntimeError, match="interrupted"):
        store.apply("origin", data, "Observe")
    assert store.mapping("origin", data["submission"]["id"]) is None
    assert store.search_orders() == []
    monkeypatch.setattr(store, "_event", original)
    assert store.apply("origin", data, "Retry")["order_id"] == "ORD-000001"


def test_concurrent_import_uses_one_identity_set(bridge):
    store, data = bridge
    with ThreadPoolExecutor(4) as executor:
        results = list(
            executor.map(
                lambda _: ProductionStore(store.path).apply("origin", data, "Concurrent retry"),
                range(4),
            )
        )
    assert all(r == results[0] for r in results)
    assert len(store.search_orders()) == 1 and len(store.cards(results[0]["order_id"])) == 2


def test_explicit_adoption_preserves_grading_links_and_audit(bridge):
    store, data = bridge
    order = store.create_order("Unverified", external_reference=data["submission"]["reference"])
    cards = store.add_cards(order["id"], 2)
    session_id = str(uuid4())
    with store.transaction() as db:
        db.execute(
            "UPDATE cards SET session_reference=?,session_id=? WHERE id=?",
            ('{"path":"existing-dossier","sha256":"unchanged"}', session_id, cards[0]["id"]),
        )
    before = store.get_card(cards[0]["id"])
    with pytest.raises(BridgeConflict, match="Unverified"):
        store.apply("origin", data, "Must review")
    pairs = {
        pc["id"]: local["id"] for pc, local in zip(data["submission"]["cards"], cards, strict=True)
    }
    data["binding"]["mode"] = "adopt"
    adopted = store.apply(
        "origin",
        data,
        "Verified individual PC identity against dossier",
        "adopt",
        {"order_id": order["id"], "cards": pairs},
    )
    assert adopted["order_id"] == order["id"] and store.get_card(cards[0]["id"]) == before
    assert store.history(order["id"])[-1]["operation"] == "production_adopt"
    assert len(store.search_orders()) == 1


def test_wrong_parent_duplicate_pairs_and_other_registry_are_conflicts(bridge):
    store, data = bridge
    order = store.create_order("A")
    cards = store.add_cards(order["id"], 2)
    other = store.create_order("B")
    wrong = store.add_cards(other["id"])[0]
    pairs = {
        c["id"]: local["id"] for c, local in zip(data["submission"]["cards"], cards, strict=True)
    }
    data["binding"]["mode"] = "adopt"
    bad = {**pairs, data["submission"]["cards"][0]["id"]: wrong["id"]}
    with pytest.raises(BridgeConflict, match="exactly once"):
        store.apply("origin", data, "Review", "adopt", {"order_id": order["id"], "cards": bad})
    data["actor"]["role"] = "operator"
    with pytest.raises(BridgeConflict, match="administrator"):
        store.apply("origin", data, "Review", "adopt", {"order_id": order["id"], "cards": pairs})
    data["binding"]["registry_id"] = str(uuid4())
    with pytest.raises(BridgeConflict, match="another registry"):
        store.apply("origin", data, "Review", distinct=True)


def test_database_constraints_protect_parentage_uniqueness_and_immutability(bridge):
    store, data = bridge
    first = store.apply("origin", data, "Review")
    other = store.create_order("Other")
    local = store.add_cards(other["id"])[0]
    for sql, args in [
        ("UPDATE bridge_cards SET card_id=?", (local["id"],)),
        ("DELETE FROM bridge_orders", ()),
        ("UPDATE bridge_registry SET id=?", (str(uuid4()),)),
        (
            "INSERT INTO bridge_cards VALUES(?,?,?,?,?,?)",
            (
                "origin",
                data["submission"]["id"],
                str(uuid4()),
                "PC-NEW",
                first["order_id"],
                local["id"],
            ),
        ),
        (
            "INSERT INTO bridge_cards VALUES(?,?,?,?,?,?)",
            (
                "origin",
                data["submission"]["id"],
                str(uuid4()),
                "PC-NEW",
                first["order_id"],
                next(iter(first["cards"].values())),
            ),
        ),
    ]:
        with pytest.raises(sqlite3.IntegrityError), store.transaction() as db:
            db.execute(sql, args)


def test_backup_preserves_v1_registry_and_links(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    legacy = OrderStore(path)
    order = legacy.create_order("Existing")
    card = legacy.add_cards(order["id"])[0]
    before = legacy.get_card(card["id"])
    store = ProductionStore(path)
    backups = list(tmp_path.glob("legacy.sqlite3.v1-*.bak"))
    assert len(backups) == 1
    assert OrderStore(backups[0]).get_card(card["id"]) == before
    assert store.get_card(card["id"]) == before
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
    ProductionStore(path)
    assert len(list(tmp_path.glob("*.bak"))) == 1


def test_backend_confirmed_but_local_missing_requires_restore(bridge):
    store, data = bridge
    data["binding"].update(
        local_order_id="ORD-000099",
        cards={c["id"]: f"SLB-C-{i:06d}" for i, c in enumerate(data["submission"]["cards"], 1)},
    )
    with pytest.raises(BridgeConflict, match="Restore registry"):
        store.apply("origin", data, "Retry")
    assert store.search_orders() == []


def test_unreconciled_snapshot_and_explicit_distinct_decision(bridge):
    store, data = bridge
    store.create_order("Unverified")
    store.apply("origin", data, "Reviewed all existing orders; this is distinct", distinct=True)
    assert len(store.search_orders()) == 2
    data["preparation"] = {"eligible": False, "reasons": ["intake_not_reconciled"]}
    with pytest.raises(BridgeConflict, match="intake_not_reconciled"):
        store.preflight("origin", data)
