"""Orders Qt workflow alongside the unchanged inspection workbench."""

import json
from copy import deepcopy

import pytest

pytest.importorskip("PySide6")
from test_selby_gui import window as window  # noqa: E402


def test_orders_workflow_and_inspection_preserved(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    w, app = window
    w.orders_path = tmp_path / "registry.sqlite3"
    original_session = w.session
    original_data = deepcopy(w.session.data)
    w.open_orders()
    app.processEvents()
    d = w.orders_dialog
    d.operator.setText("intake")
    d.customer.setText("Alice")
    d.contact.setText("alice@example.test")
    d.create_order()
    assert d.order_id == "ORD-000001"
    d.count.setValue(3)
    d.metadata.setText("Synthetic card")
    d.add_cards()
    assert d.cards.rowCount() == 3
    d.search.setText("Alice")
    assert d.orders.rowCount() == 1
    d.search.setText("Nobody")
    assert d.orders.rowCount() == 0
    d.card_search.setText("SLB-C-000002")
    d.find_card()
    assert d.card_id == "SLB-C-000002"
    assert "card_created" in d.details.toPlainText()
    d.card_status.setCurrentText("processing")
    d.set_status(True)
    assert d.store.get_card(d.card_id)["status"] == "processing"
    d.order_status.setCurrentText("received")
    d.set_status(False)
    assert d.store.get_order(d.order_id)["received_at_utc"]
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    d.order_status.setCurrentText("draft")
    d.run(lambda: d.set_status(False))
    assert warnings and "correction" in warnings[0]
    d.close()
    app.processEvents()
    w.open_orders()
    d = w.orders_dialog
    assert d.orders.rowCount() == 1
    d.open_order("ORD-000001")
    assert d.cards.rowCount() == 3
    assert w.session is original_session and w.session.data == original_data
    d.close()


def test_orders_available_without_image(window, tmp_path):
    from selby_workstation.app import Workstation

    _, app = window
    empty = Workstation()
    empty.orders_path = tmp_path / "empty.sqlite3"
    empty.open_orders()
    app.processEvents()
    assert empty.session is None
    assert empty.orders_dialog.orders.rowCount() == 0
    empty.orders_dialog.close()
    empty.close()


def test_session_link_table_details_and_unlink(window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from test_selby_session import make

    from selby_workstation import grading

    w, app = window
    w.orders_path = tmp_path / "links.sqlite3"
    w.open_orders()
    d = w.orders_dialog
    d.operator.setText("supervisor")
    d.customer.setText("Link test")
    d.create_order()
    d.add_cards()
    d.open_card("SLB-C-000001")
    inputs = tmp_path / "link-inputs"
    inputs.mkdir()
    session, _, _ = make(inputs)
    grading.initialize(session, "LEGACY-LABEL")
    path = session.save(tmp_path / "link-sessions")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    d.reason.setText("Physical pairing explicitly checked")
    d.link_session()
    assert d.cards.item(0, 4).text() == session.data["session_id"]
    assert "session_associated" in d.details.toPlainText()
    d.verify_session()
    assert "verified" in d.message.text()
    auth = tmp_path / "link-authorization.json"
    auth.write_text(json.dumps({"authorized_operators": ["supervisor"]}))
    d.store.authorization_path = auth
    d.reason.setText("Correct mistaken physical pairing")
    d.unlink_session()
    assert d.cards.item(0, 4).text() == ""
    assert "session_unlinked" in d.details.toPlainText()
    d.close()
