# ruff: noqa: F401, F811 -- imported pytest fixtures
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_scanning import bridge, ready
from test_selby_incoming import wait_until

from selby_workstation.app import Workstation


@pytest.fixture
def ui(ready, tmp_path):
    store, data, client = ready
    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "desktop.ini"
    prefs = QSettings(str(settings), QSettings.Format.IniFormat)
    prefs.setValue("orders_path", str(store.path))
    prefs.sync()
    window = Workstation(settings_path=settings)
    window.draft_directory = tmp_path / "drafts"
    window.show()
    window.desktop.pages["Incoming Submissions"].auth = SimpleNamespace(
        connection=client.connection, intake_client=lambda: client
    )
    window.desktop.open_scanner()
    dialog = window.desktop.scanner_dialog
    yield window, dialog, store, data, client
    wait_until(lambda: not dialog.busy)
    window.desktop.pages["Incoming Submissions"].auth = None
    dialog.close()
    window.close()
    app.processEvents()


def submit(dialog, value):
    dialog.input.setText(value)
    QTest.keyClick(dialog.input, Qt.Key.Key_Return)
    wait_until(lambda: not dialog.busy)


def capture(window, name):
    target = os.environ.get("SELBY_SCAN_SCREENSHOTS")
    if target:
        from pathlib import Path

        path = Path(target)
        path.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(path / name))


def test_diagnostic_duplicate_and_focus(ui):
    window, dialog, store, data, client = ui
    submit(dialog, "SELBY:TEST:V1:CALIBRATION")
    assert "Diagnostic recognized" in dialog.status.text()
    assert window.session is None
    capture(dialog, "diagnostic.png")
    submit(dialog, "SELBY:TEST:V1:CALIBRATION")
    assert "Repeated scan ignored" in dialog.status.text()
    dialog.close()
    window.desktop.navigate("Orders")
    field = window.orders_dialog.card_search
    field.setFocus()
    QTest.keyClicks(field, "ordinary typing")
    assert field.text() == "ordinary typing"
    window.desktop.navigate("Labels")
    wait_until(lambda: not window.desktop.pages["Labels"].busy)
    window.desktop.open_scanner()
    submit(dialog, "truncated")
    assert "Invalid" in dialog.status.text()
    capture(window, "labels-scan-action.png")


def test_unpaid_no_session_or_mutation(ui):
    window, dialog, store, data, client = ui
    for check in data["inspection"].values():
        check.update(eligible=False, reasons=[{"code": "payment_unverified"}])
    before = store.path.read_bytes()
    submit(dialog, "SP:PC:1:" + data["submission"]["cards"][1]["reference"])
    assert "BLOCKED" in dialog.status.text()
    assert "payment_unverified" in dialog.status.text()
    assert window.session is None
    assert not hasattr(window, "orders_dialog")
    assert store.path.read_bytes() == before
    capture(dialog, "unpaid-blocked.png")


def test_order_and_existing_workflow_dispatch(ui, monkeypatch):
    window, dialog, store, data, client = ui
    submit(dialog, "SP:ORDER:1:" + data["submission"]["reference"])
    assert window.orders_dialog.order_id == data["binding"]["local_order_id"]
    assert window.session is None
    called = []
    monkeypatch.setattr(
        window.desktop, "open_card_workflow", lambda: called.append(window.orders_dialog.card_id)
    )
    card = data["submission"]["cards"][1]
    submit(dialog, "SP:PC:1:" + card["reference"])
    assert called == [data["binding"]["cards"][card["id"]]]
    assert "No linked session" in dialog.status.text()
    capture(dialog, "identified-card.png")


def test_real_saved_session_resume(ui, tmp_path):
    from test_selby_session import make

    from selby_workstation import grading
    from spectra_scanner.storage import sha256_file

    window, dialog, store, data, client = ui
    card = data["submission"]["cards"][0]
    local_id = data["binding"]["cards"][card["id"]]
    session, image, report = make(tmp_path)
    session.load_report(report)
    grading.initialize(session, local_id)
    saved = session.save(tmp_path / "sessions")
    store.associate_session(local_id, saved, "operator", "Synthetic physical pairing")
    before = sha256_file(saved)
    submit(dialog, "SP:PC:1:" + card["reference"])
    assert window.desktop.current == "Inspection"
    assert window.desktop.workflow_card == local_id
    assert window.session.data["session_id"] == session.data["session_id"]
    assert sha256_file(saved) == before
    capture(window, "resumed-inspection.png")
    window.dirty = False


def test_new_original_revalidates_authorization(ui, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from test_selby_session import make

    window, dialog, store, data, client = ui
    session, image, report = make(tmp_path)
    card = data["submission"]["cards"][0]
    submit(dialog, "SP:PC:1:" + card["reference"])
    assert dialog.new_button.isEnabled()
    data["inspection"][card["id"]].update(eligible=False, reasons=[{"code": "payment_unverified"}])
    dialog.start_original()
    wait_until(lambda: not dialog.busy)
    assert window.session is None
    assert not dialog.new_button.isEnabled()
    data["inspection"][card["id"]].update(eligible=True, reasons=[])
    dialog.last = None
    submit(dialog, "SP:PC:1:" + card["reference"])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a: (str(image), "PNG"))
    dialog.start_original()
    wait_until(lambda: not dialog.busy)
    assert window.session is not None
    assert window.desktop.current == "Inspection"
    assert Path(window.session.data["image"]["path"]).resolve() == image.resolve()
    assert store.get_card(data["binding"]["cards"][card["id"]])["session_reference"] is None
    window.dirty = False


def test_cancelled_local_card_remains_read_only(ui):
    window, dialog, store, data, client = ui
    card = data["submission"]["cards"][0]
    local_id = data["binding"]["cards"][card["id"]]
    store.transition(local_id, "cancelled", "operator", "Synthetic cancellation")
    submit(dialog, "SP:PC:1:" + card["reference"])
    assert "Local card status: cancelled" in dialog.status.text()
    assert window.session is None
    assert not dialog.new_button.isEnabled()
    assert store.get_card(local_id)["status"] == "cancelled"
