"""Transactional identity registry tests; no public certification or grade changes."""

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from selby_workstation.orders import OrderStore
from spectra_scanner.common import AgentError


@pytest.fixture
def store(tmp_path):
    auth = tmp_path / "authorization.json"
    auth.write_text(json.dumps({"authorized_operators": ["supervisor"]}))
    return OrderStore(tmp_path / "orders.sqlite3", auth)


def test_creation_restart_search_customer_and_audit(store):
    order = store.create_order("Alice", "alice@example.test", "EXT-1", "Bag A", "intake")
    assert order["id"] == "ORD-000001" and order["card_count"] == 0
    cards = store.add_cards(order["id"], 3, {"name": "Test card"}, operator="intake")
    assert [c["id"] for c in cards] == [f"SLB-C-{n:06d}" for n in range(1, 4)]
    assert [c["position"] for c in cards] == [1, 2, 3]
    assert all(c["certification_reference"] is None for c in cards)
    opened = OrderStore(store.path, store.authorization_path)
    assert opened.search_orders("alice")[0]["card_count"] == 3
    assert opened.search_orders("ORD-000001")[0]["customer_name"] == "Alice"
    assert opened.search_card("slb-c-000002") == cards[1]
    assert len(opened.cards(order["id"])) == 3
    opened.update_customer(order["id"], "Alice Smith", "new contact", notes="Updated",
                           operator="intake")
    event = opened.history(order["id"])[-1]
    assert event["operation"] == "customer_updated"
    assert event["operator"] == "intake" and event["at_utc"]
    assert event["before"]["customer_name"] == "Alice"
    assert event["after"]["customer_name"] == "Alice Smith"


def test_no_reuse_after_cancellation(store):
    order = store.create_order("A")
    first = store.add_cards(order["id"])[0]
    store.transition(first["id"], "cancelled", "intake", "Customer cancellation")
    store.transition(order["id"], "cancelled", "intake", "Customer cancellation")
    opened = OrderStore(store.path)
    second = opened.create_order("B")
    card = opened.add_cards(second["id"])[0]
    assert second["id"] == "ORD-000002" and card["id"] == "SLB-C-000002"
    assert opened.get_card(first["id"])["status"] == "cancelled"
    with pytest.raises(ValueError):
        opened.add_cards(order["id"])


def test_position_orphans_identity_and_reserved_certification(store):
    order = store.create_order("A")
    card = store.add_cards(order["id"], position=2)[0]
    with pytest.raises(sqlite3.IntegrityError):
        store.add_cards(order["id"], position=2)
    with pytest.raises(ValueError):
        store.add_cards("ORD-999999")
    for sql, args in [
        ("UPDATE cards SET order_id=? WHERE id=?", ("ORD-999999", card["id"])),
        ("UPDATE cards SET position=3 WHERE id=?", (card["id"],)),
        ("UPDATE cards SET id='SLB-C-999999' WHERE id=?", (card["id"],)),
        ("UPDATE orders SET id='ORD-999999' WHERE id=?", (order["id"],)),
        ("UPDATE cards SET certification_reference='PUBLIC-1' WHERE id=?", (card["id"],)),
        ("DELETE FROM cards WHERE id=?", (card["id"],)),
        ("DELETE FROM orders WHERE id=?", (order["id"],)),
        ("DELETE FROM audit WHERE entity=?", (card["id"],)),
    ]:
        with pytest.raises(sqlite3.IntegrityError), store.transaction() as db:
            db.execute(sql, args)
    assert store.get_card(card["id"])["order_id"] == order["id"]


def test_status_lifecycle_and_authorized_correction(store):
    order = store.create_order("A")["id"]
    card = store.add_cards(order)[0]["id"]
    with pytest.raises(ValueError):
        store.transition(order, "completed")
    with pytest.raises(ValueError):
        store.transition(card, "completed")
    for state in ("received", "processing", "completed", "shipped"):
        store.transition(order, state, "operator")
    received = store.get_order(order)["received_at_utc"]
    assert received
    with pytest.raises(ValueError):
        store.transition(order, "received")
    with pytest.raises(ValueError):
        store.transition(order, "received", "intruder", "Mistake", True)
    with pytest.raises(ValueError):
        store.transition(order, "received", "supervisor", "", True)
    store.transition(order, "received", "supervisor", "Incorrect shipping entry", True)
    assert store.get_order(order)["received_at_utc"] == received
    assert store.history(order)[-1]["operation"] == "status_corrected"
    for state in ("processing", "completed"):
        store.transition(card, state, "operator")
    with pytest.raises(ValueError):
        store.transition(card, "registered")
    store.transition(card, "registered", "supervisor", "Incorrect completion", True)
    assert store.get_card(card)["status"] == "registered"


def test_batch_failure_rolls_back_cards_allocation_and_audit(store, monkeypatch):
    order = store.create_order("A")["id"]
    real = store._event

    def fail(db, entity, *args):
        real(db, entity, *args)
        if entity == "SLB-C-000002":
            raise OSError("Injected disk write failure")

    monkeypatch.setattr(store, "_event", fail)
    with pytest.raises(OSError):
        store.add_cards(order, 3)
    assert store.cards(order) == []
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM audit").fetchone()[0] == 1
    monkeypatch.setattr(store, "_event", real)
    # Uncommitted allocations were never issued; committed IDs are never reused.
    assert store.add_cards(order)[0]["id"] == "SLB-C-000001"


def test_failed_order_creation_is_atomic(store, monkeypatch):
    def fail(*args):
        raise sqlite3.OperationalError("Injected write failure")

    monkeypatch.setattr(store, "_event", fail)
    with pytest.raises(sqlite3.OperationalError):
        store.create_order("A")
    assert OrderStore(store.path).search_orders() == []


def test_interrupted_transaction_recovers_on_restart(store):
    order = store.create_order("A")["id"]
    script = """
import os, sys
from selby_workstation.orders import OrderStore
s = OrderStore(sys.argv[1])
def crash(*args):
    os._exit(23)
s._event = crash
s.add_cards(sys.argv[2], 3)
"""
    result = subprocess.run([sys.executable, "-B", "-c", script, str(store.path), order],
                            capture_output=True, timeout=30,
                            cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 23, result.stderr.decode()
    opened = OrderStore(store.path)
    assert opened.cards(order) == []
    with opened.connection() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert opened.add_cards(order)[0]["id"] == "SLB-C-000001"


def test_concurrent_allocations_are_unique(store):
    order = store.create_order("A")["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        batches = list(pool.map(lambda _: store.add_cards(order, 2), range(8)))
    cards = [c for batch in batches for c in batch]
    assert len({c["id"] for c in cards}) == 16
    assert sorted(c["position"] for c in cards) == list(range(1, 17))


def test_session_association_preserves_legacy_evidence(store, tmp_path):
    from test_selby_session import make

    from selby_workstation import grading
    from spectra_scanner.storage import sha256_file

    session, image, report = make(tmp_path)
    session.load_report(report)
    grading.initialize(session, "LEGACY-OPERATOR-LABEL")
    path = session.save(tmp_path / "sessions")
    before = {p: sha256_file(p) for p in (path, image, report)}
    order = store.create_order("A")["id"]
    first, second = store.add_cards(order, 2)
    store.associate_session(first["id"], path, "operator", "Physical card pairing checked")
    reference = OrderStore(store.path).verify_association(first["id"])
    assert reference["declared_card_id"] == "LEGACY-OPERATOR-LABEL"
    assert reference["sha256"] == before[path]
    with pytest.raises(sqlite3.IntegrityError):
        store.associate_session(second["id"], path, "operator", "Duplicate pairing")
    assert store.get_card(second["id"])["session_reference"] is None
    with pytest.raises(ValueError):
        store.unlink_session(first["id"], "operator", "Wrong card")
    store.unlink_session(first["id"], "supervisor", "Wrong physical card association")
    assert store.history(first["id"])[-1]["operation"] == "session_unlinked"
    store.associate_session(first["id"], path, "operator", "Pairing rechecked")
    session.data["notes"] = "Next version"
    newer = session.save(tmp_path / "sessions")
    with pytest.raises(ValueError):
        store.associate_session(first["id"], newer, "operator", "New version")
    store.associate_session(first["id"], newer, "supervisor", "Explicit reviewed version update")
    assert {p: sha256_file(p) for p in before} == before
    image.write_bytes(b"Changed evidence")
    with pytest.raises(AgentError):
        store.verify_association(first["id"])


def test_inspection_only_and_mismatched_dossier_rejected(store, tmp_path):
    from test_selby_session import make

    from selby_workstation import grading

    session, _, _ = make(tmp_path)
    order = store.create_order("A")["id"]
    card = store.add_cards(order)[0]["id"]
    path = session.save(tmp_path / "sessions")
    with pytest.raises(ValueError, match="dossier"):
        store.associate_session(card, path, "operator", "Explicit pairing")
    grading.initialize(session, "SLB-C-999999")
    path = session.save(tmp_path / "sessions")
    with pytest.raises(ValueError, match="another internal"):
        store.associate_session(card, path, "operator", "Explicit pairing")
    assert store.get_card(card)["session_reference"] is None


def test_schema_version_rejected(store):
    with store.connection() as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="Unsupported"):
        OrderStore(store.path)
