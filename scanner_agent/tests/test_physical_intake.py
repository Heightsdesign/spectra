"""Qt operation selection/recovery contracts; real business rules tested in FastAPI."""

import json
import os
import threading
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QMessageBox
from test_selby_incoming import CID, DETAIL, EID, PID, SID, wait_until

from selby_workstation.connection import DesktopConnection
from selby_workstation.incoming import PreviewError
from selby_workstation.intake_journal import IntakeJournal
from selby_workstation.intake_ui import PhysicalIntake


class FixtureClient:
    def __init__(self):
        self.data = deepcopy(DETAIL)
        for issue in self.data["discrepancies"]:
            issue["id"] = str(uuid4())
        self.actor = {"role": "admin"}
        self.calls = []
        self.threads = []
        self.error = None

    def load(self, sid):
        self.threads.append(threading.get_ident())
        if self.error:
            raise self.error
        return self.actor, deepcopy(self.data)

    def execute(self, operation):
        self.threads.append(threading.get_ident())
        self.calls.append(operation)
        if self.error:
            raise self.error
        return deepcopy(self.data)


@pytest.fixture
def intake(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    client = FixtureClient()
    auth = SimpleNamespace(
        connection=DesktopConnection(
            "development", "http://127.0.0.1:8000", "http://127.0.0.1:3000"
        ),
        intake_client=lambda: client,
    )
    journal = IntakeJournal(tmp_path / "intents.sqlite3")
    widget = PhysicalIntake(auth, SID, journal=journal)
    widget.show()
    wait_until(lambda: not widget.busy)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    yield widget, client, journal, auth
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    widget.close()
    app.processEvents()


def action(widget, key):
    widget.buttons[key].click()
    wait_until(lambda: not widget.busy)


def test_individual_copy_explicit_match_and_no_auto_identity(intake):
    widget, client, journal, auth = intake
    widget.entry.setCurrentIndex(widget.entry.findData(EID))
    widget.notes.setText("Individual copy observed")
    action(widget, "card")
    operation = client.calls[-1]
    assert operation["kind"] == "card" and operation["payload"]["parcel_id"] == PID
    assert "entry_id" not in operation["payload"]
    assert len(operation["payload"]["request_key"]) == 36
    assert journal.pending(widget.scope, SID) is None
    action(widget, "card")
    assert client.calls[-1]["payload"]["request_key"] != operation["payload"]["request_key"]
    widget.reason.setText("Verified this specific physical card against declaration")
    action(widget, "match")
    assert client.calls[-1]["target"] == CID and client.calls[-1]["payload"]["entry_id"] == EID
    assert all(thread != threading.get_ident() for thread in client.threads)


def test_consequential_actions_require_confirmation_and_reason(intake, monkeypatch):
    widget, client, journal, _ = intake
    action(widget, "complete")
    assert not client.calls and "reason" in widget.status.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    action(widget, "parcel")
    assert not client.calls and journal.pending(widget.scope, SID) is None


def test_missing_and_resolution_payloads(intake):
    widget, client, journal, _ = intake
    widget.notes.setText("Declared physical copies absent")
    widget.entry.setCurrentIndex(widget.entry.findData(EID))
    widget.quantity.setValue(2)
    action(widget, "issue")
    payload = client.calls[-1]["payload"]
    assert (
        payload["kind"] == "missing"
        and payload["quantity"] == 2
        and payload["card_id"] is None
        and payload["entry_id"] == EID
    )
    did = str(uuid4())
    client.data["discrepancies"][0]["id"] = did
    client.data["discrepancies"][0]["status"] = "open"
    widget.refresh()
    wait_until(lambda: not widget.busy)
    widget.reason.setText("Reviewed explicit missing exception")
    widget.resolution.setCurrentText("acknowledged")
    action(widget, "resolve")
    assert (
        client.calls[-1]["target"] == did
        and client.calls[-1]["payload"]["status"] == "acknowledged"
    )


def test_pending_receipt_survives_restart_and_retries_same_request(intake):
    widget, client, journal, auth = intake
    client.error = PreviewError("Offline: unknown outcome", kind="offline")
    action(widget, "card")
    pending = journal.pending(widget.scope, SID)
    assert pending and not widget.buttons["card"].isEnabled() and widget.retry_button.isEnabled()
    assert not widget.review_button.isEnabled()
    client.error = None
    restarted = PhysicalIntake(auth, SID, journal=IntakeJournal(journal.path))
    try:
        wait_until(lambda: not restarted.busy)
        assert restarted.pending == pending and not restarted.buttons["card"].isEnabled()
        assert (
            not restarted.review_button.isEnabled()
        )  # An unknown receipt cannot be discarded into a duplicate.
        restarted.retry_button.click()
        wait_until(lambda: not restarted.busy)
        assert client.calls[-1] == pending and restarted.pending is None
    finally:
        restarted.close()


def test_non_idempotent_actions_require_fresh_manual_review(intake):
    widget, client, journal, _ = intake
    client.error = PreviewError("Offline", kind="offline")
    widget.reason.setText("Custody completion decision")
    action(widget, "complete")
    assert journal.pending(widget.scope, SID)["kind"] == "transition"
    assert not widget.retry_button.isEnabled() and not widget.review_button.isEnabled()
    client.error = None
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert widget.review_button.isEnabled() and not widget.buttons["complete"].isEnabled()
    widget.review_button.click()
    assert journal.pending(widget.scope, SID) is None and widget.buttons["complete"].isEnabled()


def test_operator_roles_reconciled_state_and_expired_session(intake):
    widget, client, _, _ = intake
    client.actor["role"] = "operator"
    client.data["status"] = "partially_received"
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert widget.buttons["begin"].isEnabled() and not widget.buttons["override"].isEnabled()
    client.data["status"] = "reconciled"
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert all(not b.isEnabled() for b in widget.buttons.values())
    assert "inspection clearance not granted" in widget.heading.text()
    client.error = PreviewError("Session expired", disconnect=True, kind="expired")
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert widget.data is None and widget.inventory.rowCount() == 0 and widget.entry.count() == 0


def test_journal_scope_atomic_single_pending_and_secret_field_rejection(tmp_path):
    journal = IntakeJournal(tmp_path / "intents.sqlite3")
    operation = journal.begin("backend-a", SID, "parcel", {"notes": "Observed arrival"})
    with pytest.raises(PreviewError, match="pending operation"):
        IntakeJournal(journal.path).begin("backend-a", SID, "parcel", {"notes": "Different object"})
    assert journal.pending("backend-b", SID) is None
    with pytest.raises(PreviewError):
        journal.begin("backend-b", SID, "parcel", {"token": "must-not-persist"})
    journal.finish("backend-a", {**operation, "id": str(uuid4())})
    assert journal.pending("backend-a", SID) == operation
    with pytest.raises(PreviewError):
        journal.retry("backend-b", SID, FixtureClient())


def test_existing_local_registry_and_links_are_untouched(intake, tmp_path):
    import sqlite3
    from hashlib import sha256

    from selby_workstation.orders import OrderStore

    widget, client, _, _ = intake
    store = OrderStore(tmp_path / "existing-orders.sqlite3")
    order = store.create_order(
        "Synthetic local customer", external_reference="SP-existing", operator="fixture"
    )
    card = store.add_cards(order["id"], operator="fixture")[0]
    # Existing linkage metadata is unrelated to backend PC identities.
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE cards SET session_reference=?,session_id=? WHERE id=?",
            (json.dumps("existing-session"), str(uuid4()), card["id"]),
        )
    before = sha256(store.path.read_bytes()).hexdigest()
    action(widget, "card")
    widget.reason.setText("Explicit verification")
    widget.entry.setCurrentIndex(widget.entry.findData(EID))
    action(widget, "match")
    assert sha256(store.path.read_bytes()).hexdigest() == before
    assert store.get_card(card["id"])["session_reference"] == "existing-session"


def test_escape_cannot_dismiss_dialog_during_backend_request(intake):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    widget, client, _, _ = intake
    started, release = threading.Event(), threading.Event()
    original = client.load

    def blocked_load(sid):
        started.set()
        assert release.wait(3)
        return original(sid)

    client.load = blocked_load
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
