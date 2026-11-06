"""Unified desktop workflows using the real existing UI and persistence services."""
# ruff: noqa: E402

import json
import os
import sqlite3
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QPushButton
from test_selby_grading import pair as pair
from test_selby_session import make

from selby_workstation import grading
from selby_workstation.app import Workstation
from spectra_scanner.storage import sha256_file


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    w = Workstation(settings_path=tmp_path / "desktop.ini")
    w.orders_path = tmp_path / "orders.sqlite3"
    w.draft_directory = tmp_path / "drafts"
    w.show()
    app.processEvents()
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    yield w, app, warnings
    w.dirty = False
    w.close()
    app.processEvents()


def click(parent, text):
    button = next(b for b in parent.findChildren(QPushButton) if b.text() == text)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()


def intake(w):
    click(w.desktop, "Orders")
    d = w.orders_dialog
    d.operator.setText("intake")
    d.customer.setText("Desktop customer")
    d.contact.setText("test@example.test")
    click(d, "Create order")
    d.count.setValue(2)
    click(d, "Add cards")
    d.card_search.setText("SLB-C-000001")
    QTest.keyClick(d.card_search, Qt.Key.Key_Return)
    return d


def saved_dossier(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    s, image, report = make(inputs)
    s.load_report(report)
    grading.initialize(s, "LEGACY-DESKTOP-CARD")
    return s.save(tmp_path / "sessions"), image, report


def test_default_entry_point(tmp_path):
    result = subprocess.run([sys.executable, "-B", "selby_workstation.py", "--smoke-test",
                             "--orders-store", str(tmp_path / "default.sqlite3")],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    data = json.loads(result.stdout.strip())
    assert data["current_module"] == "Dashboard"
    assert not data["image_loaded"] and not data["orders_loaded"]


def test_navigation_creation_context_keyboard_and_no_implicit_session(desktop):
    w, app, warnings = desktop
    assert w.desktop.current == "Dashboard"
    for name in ("Orders", "Inspection", "Grading", "Settings", "Dashboard"):
        click(w.desktop, name)
        assert w.desktop.current == name
    d = intake(w)
    assert d.orders.rowCount() == 1 and d.cards.rowCount() == 2
    assert "SLB-C-000001" in w.desktop.context.text()
    click(d, "Open linked grading")
    assert "no linked grading session" in d.message.text()
    assert w.session is None and not warnings
    d.notes.setText("Unsubmitted form preserved")
    click(w.desktop, "Dashboard")
    click(w.desktop, "Orders")
    assert d.notes.text() == "Unsubmitted form preserved"
    QTest.keyClick(w, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert d.card_search.hasFocus()
    assert d.card_search.selectedText() == "SLB-C-000001"
    assert not any(b.isEnabled() for b in w.desktop.findChildren(QPushButton)
                   if "future" in b.text())


def test_linked_session_return_resume_and_restart(desktop, tmp_path, monkeypatch):
    w, app, warnings = desktop
    d = intake(w)
    path, image, report = saved_dossier(tmp_path)
    hashes = {p: sha256_file(p) for p in (path, image, report)}
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    d.reason.setText("Explicit physical pairing checked")
    click(d, "Associate saved grading session…")
    click(d, "Open linked grading")
    assert w.desktop.current == "Grading"
    assert w.session.data["grading"]["working"]["card_id"] == "LEGACY-DESKTOP-CARD"
    current = w.session
    w.notes.setPlainText("Uncommitted inspection note")
    state = deepcopy(current.data)
    click(w.desktop, "Orders")
    assert d.card_id == "SLB-C-000001"
    assert w.session is current and w.session.data == state and w.dirty
    click(d, "Open linked inspection")
    assert w.session is current and w.notes.toPlainText() == "Uncommitted inspection note"
    assert w.desktop.current == "Inspection"
    assert w.desktop.workflow_card == "SLB-C-000001"
    assert {p: sha256_file(p) for p in hashes} == hashes
    restarted = Workstation(settings_path=tmp_path / "restart.ini")
    restarted.orders_path = w.orders_path
    restarted.draft_directory = tmp_path / "restart-drafts"
    restarted.open_orders()
    restarted.orders_dialog.card_search.setText("SLB-C-000001")
    restarted.orders_dialog.find_card()
    restarted.desktop.open_card_workflow(True)
    assert restarted.session.saved_path == path.resolve()
    assert restarted.orders_dialog.cards.rowCount() == 2
    restarted.dirty = False
    restarted.close()
    app.processEvents()
    assert not warnings


@pytest.mark.parametrize("missing", ["session", "image"])
def test_missing_linked_evidence_preserves_active_session(desktop, tmp_path, missing):
    w, _, warnings = desktop
    d = intake(w)
    path, image, _ = saved_dossier(tmp_path)
    d.store.associate_session(d.card_id, path, "intake", "Explicit pairing")
    other = tmp_path / "other"
    other.mkdir()
    unrelated, _, _ = make(other)
    other_path = unrelated.save(tmp_path / "other-sessions")
    w.open_session(other_path)
    current = w.session
    (path if missing == "session" else image).unlink()
    click(w.desktop, "Orders")
    click(d, "Open linked grading")
    assert warnings and "recorded path" in warnings[-1]
    assert w.session is current
    assert w.desktop.current == "Orders"
    assert d.store.get_card(d.card_id)["session_reference"] is not None


def test_sensitive_actions_cancel_without_changes(desktop, tmp_path, monkeypatch):
    w, _, warnings = desktop
    d = intake(w)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    d.order_status.setCurrentText("cancelled")
    click(d, "Set order status")
    assert d.store.get_order(d.order_id)["status"] == "draft"
    path, _, _ = saved_dossier(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    click(d, "Associate saved grading session…")
    assert d.store.get_card(d.card_id)["session_reference"] is None
    assert not warnings


def test_settings_persist_registry_and_do_not_replace_inspection(desktop, tmp_path, monkeypatch):
    from selby_workstation.orders import OrderStore

    w, _, warnings = desktop
    intake(w)
    path, _, _ = saved_dossier(tmp_path)
    w.open_session(path)
    current = w.session
    selected = tmp_path / "other-registry.sqlite3"
    OrderStore(selected).create_order("Other registry")
    click(w.desktop, "Settings")
    assert "orders.sqlite3" in w.desktop.paths.text()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(selected), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    click(w.desktop, "Use an existing orders registry…")
    assert w.session is current
    assert not hasattr(w, "orders_dialog")
    restarted = Workstation(settings_path=tmp_path / "desktop.ini")
    assert restarted.orders_path == selected
    restarted.open_orders()
    assert restarted.orders_dialog.store.search_orders()[0]["customer_name"] == "Other registry"
    restarted.close()
    assert not warnings


def test_dirty_session_replacement_requires_confirmation(desktop, tmp_path, monkeypatch):
    w, _, warnings = desktop
    d = intake(w)
    path, _, _ = saved_dossier(tmp_path)
    d.store.associate_session(d.card_id, path, "intake", "Physical pairing")
    other = tmp_path / "other"
    other.mkdir()
    unrelated, _, _ = make(other)
    w.open_session(unrelated.save(tmp_path / "unrelated"))
    w.notes.setPlainText("Do not discard")
    current = w.session
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    click(w.desktop, "Orders")
    click(d, "Open linked inspection")
    assert w.session is current and w.dirty
    assert w.desktop.current == "Orders" and not warnings


def test_settings_refuses_unrelated_sqlite_without_modifying_it(desktop, tmp_path, monkeypatch):
    w, _, warnings = desktop
    current = w.orders_path
    unrelated = tmp_path / "unrelated.db"
    with sqlite3.connect(unrelated) as db:
        db.execute("CREATE TABLE unrelated (value TEXT)")
    original = sha256_file(unrelated)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(unrelated), ""))
    click(w.desktop, "Settings")
    click(w.desktop, "Use an existing orders registry…")
    assert warnings and "not compatible" in warnings[-1]
    assert w.orders_path == current and sha256_file(unrelated) == original


def test_grading_refreshes_after_inspection_changes(desktop, pair, tmp_path):
    w, _, warnings = desktop
    front, _ = pair
    path = front.save(tmp_path / "graded-inputs")
    w.open_session(path)
    click(w.desktop, "Grading")
    dialog = w.grading_dialog
    assert '"state": "Ready for operator review"' in dialog.result.toPlainText()
    dialog.notes.setText("Unsubmitted grading explanation")
    click(w.desktop, "Inspection")
    w.operator.setText("Revised operator")
    w.apply_edit("physical", 0, [[92, 96], [450, 98]])
    click(w.desktop, "Grading")
    assert w.grading_dialog is dialog
    assert '"state": "Incomplete"' in dialog.result.toPlainText()
    assert dialog.operator.text() == "Operator: Revised operator"
    assert dialog.notes.text() == "Unsubmitted grading explanation"
    assert not warnings
