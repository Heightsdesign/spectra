"""Operator confirmation, visible pending state and background networking contracts."""
# ruff: noqa: F811 -- imported pytest fixture.

import os
import threading
from copy import deepcopy

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_production_bridge import bridge  # noqa: F401
from test_selby_incoming import wait_until

from selby_workstation.incoming import PreviewError
from selby_workstation.production_ui import ProductionDialog


@pytest.fixture
def dialog(bridge, monkeypatch):
    store, snapshot = bridge
    app = QApplication.instance() or QApplication([])
    snapshot["submission"]["payment_status"] = "not_implemented"
    snapshot["inspection"] = {
        c["id"]: {"eligible": False, "reasons": [{"code": "payment_unverified"}]}
        for c in snapshot["submission"]["cards"]
    }
    state = {
        "snapshot": snapshot,
        "mapping": None,
        "mapping_state": "unmapped",
        "conflict": None,
        "unverified": [],
        "registry_id": store.registry_id,
    }
    calls, threads, opened = [], [], []

    class Service:
        error = None

        def __init__(self, client, path):
            pass

        def load(self, sid):
            threads.append(threading.get_ident())
            if self.error:
                raise self.error
            return deepcopy(state)

        def prepare(self, sid, reason, mode, adoption, distinct):
            threads.append(threading.get_ident())
            calls.append((sid, reason, mode, adoption, distinct))
            return deepcopy(state)

    monkeypatch.setattr("selby_workstation.production_ui.ProductionService", Service)
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)

    class Auth:
        def intake_client(self):
            return None

    widget = ProductionDialog(
        Auth(), snapshot["submission"]["id"], store.path, open_order=opened.append
    )
    widget.show()
    wait_until(lambda: not widget.busy)
    yield widget, state, calls, threads, opened, Service
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    widget.close()


def test_confirmation_reason_and_background_work(dialog, monkeypatch):
    widget, state, calls, threads, _, _ = dialog
    widget.prepare_button.click()
    assert not calls and "reason" in widget.status.text()
    widget.reason.setText("Verified permanent identity")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    widget.prepare_button.click()
    assert not calls
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    widget.prepare_button.click()
    wait_until(lambda: not widget.busy)
    assert calls and all(t != threading.get_ident() for t in threads)
    assert "payment_unverified" in widget.table.item(0, 3).text()


def test_pending_mapping_cannot_open_as_confirmed(dialog):
    widget, state, _, _, opened, _ = dialog
    state["mapping"] = {
        "order_id": "ORD-000001",
        "cards": {
            c["id"]: f"SLB-C-{i:06d}"
            for i, c in enumerate(state["snapshot"]["submission"]["cards"], 1)
        },
        "confirmed": 0,
    }
    state["mapping_state"] = "pending confirmation"
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert "pending confirmation" in widget.heading.text() and not widget.open_button.isEnabled()
    state["mapping"]["confirmed"] = 1
    state["mapping_state"] = "confirmed"
    widget.refresh()
    wait_until(lambda: not widget.busy)
    widget.open_button.click()
    assert opened == ["ORD-000001"]


def test_rejected_authorization_clears_protected_details(dialog):
    widget, _, _, _, _, Service = dialog
    Service.error = PreviewError("Permission denied", disconnect=True)
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert widget.value is None and widget.table.rowCount() == 0
    assert not widget.prepare_button.isEnabled() and not widget.open_button.isEnabled()


def test_conflicting_mapping_is_visible_and_cannot_be_opened(dialog):
    widget, state, _, _, _, _ = dialog
    state["mapping"] = {"order_id": "ORD-000001", "cards": {}, "confirmed": 1}
    state["mapping_state"] = "conflict"
    state["conflict"] = "Restore the original registry"
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert "conflict" in widget.heading.text()
    assert "Restore the original registry" in widget.conflicts.toPlainText()
    assert not widget.prepare_button.isEnabled() and not widget.open_button.isEnabled()


def test_adoption_rejects_duplicate_pc_json_before_request(dialog):
    widget, _, calls, _, _, _ = dialog
    widget.mode.setCurrentIndex(1)
    widget.reason.setText("Explicit pairing")
    widget.pairs.setPlainText('{"pc":"SLB-C-000001","pc":"SLB-C-000002"}')
    widget.prepare_button.click()
    assert not calls and "unique" in widget.status.text()


def test_escape_waits_for_pending_network_worker(dialog):
    widget, _, _, _, _, Service = dialog
    started, release = threading.Event(), threading.Event()
    original = Service.load

    def blocked(self, sid):
        started.set()
        assert release.wait(3)
        return original(self, sid)

    Service.load = blocked
    widget.refresh()
    try:
        assert started.wait(2)
        QTest.keyClick(widget, Qt.Key.Key_Escape)
        assert widget.isVisible() and widget.busy
    finally:
        release.set()
    wait_until(lambda: not widget.busy)
    QTest.keyClick(widget, Qt.Key.Key_Escape)
    assert not widget.isVisible()
