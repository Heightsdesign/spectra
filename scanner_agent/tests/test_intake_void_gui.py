"""Explicit PC void selection, confirmation, and historical visibility."""
# ruff: noqa: F811 -- imported pytest fixture.

from copy import deepcopy

from PySide6.QtWidgets import QMessageBox
from test_physical_intake import action, intake  # noqa: F401
from test_selby_incoming import CID, wait_until


def eligible(widget, client):
    client.data["cards"][0].update(
        entry_id=None, status="unidentified", void_eligible=True, void_blockers=[]
    )
    widget.refresh()
    wait_until(lambda: not widget.busy)


def test_void_requires_reason_confirmation_and_full_reference(intake, monkeypatch):
    widget, client, journal, _ = intake
    eligible(widget, client)
    assert widget.buttons["void"].isEnabled()
    action(widget, "void")
    assert not client.calls and "reason" in widget.status.text()
    widget.reason.setText("Mistaken extra click; no physical object")
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Cancel)
    action(widget, "void")
    assert not client.calls and journal.pending(widget.scope, widget.sid) is None
    prompts = []

    def confirm(*args):
        prompts.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    action(widget, "void")
    assert client.calls[-1]["kind"] == "void" and client.calls[-1]["target"] == CID
    assert client.data["cards"][0]["reference"] in prompts[-1]
    assert "Mistaken extra click" in prompts[-1]


def test_voided_history_excluded_and_selection_not_reassigned(intake):
    widget, client, _, _ = intake
    eligible(widget, client)
    reference = client.data["cards"][0]["reference"]
    voided = deepcopy(client.data["cards"][0])
    voided.update(
        status="voided",
        void={"reason": "No object"},
        void_eligible=False,
        void_blockers=["card_voided"],
    )
    client.data["cards"] = [voided]
    client.data["received_quantity"] = 0
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert widget.card.findData(CID) == -1 and widget.card.currentData() is None
    assert not widget.buttons["void"].isEnabled() and widget.buttons["void"].isVisible()
    assert "Received 0" in widget.heading.text() and "Unidentified 0" in widget.heading.text()
    assert widget.inventory.item(0, 0).text() == reference
    assert (
        widget.inventory.item(0, 3).text() == "VOIDED"
        and widget.inventory.item(0, 4).text() == "No object"
    )
    assert not widget.buttons["match"].isEnabled()


def test_ineligible_matched_and_terminal_pc_have_visible_disabled_void_action(intake):
    widget, client, _, _ = intake
    assert not widget.buttons["void"].isEnabled()
    eligible(widget, client)
    client.data["status"] = "reconciled"
    client.data["cards"][0].update(
        void_eligible=False, void_blockers=["begin_reconciliation_required"]
    )
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert not widget.buttons["void"].isEnabled() and widget.buttons["void"].isVisible()


def test_void_retry_requires_refresh_and_confirms_preserved_full_identity(intake, monkeypatch):
    from selby_workstation.incoming import PreviewError

    widget, client, journal, _ = intake
    eligible(widget, client)
    widget.reason.setText("Original verified void reason")
    client.error = PreviewError("Offline; unknown outcome", kind="offline")
    action(widget, "void")
    pending = journal.pending(widget.scope, widget.sid)
    assert pending["target"] == CID and not widget.retry_button.isEnabled()
    client.error = None
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert widget.retry_button.isEnabled()
    prompts = []

    def confirm(*args):
        prompts.append(args[2])
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    widget.reason.setText("Changed form text must not change preserved intent")
    widget.retry_button.click()
    wait_until(lambda: not widget.busy)
    assert client.data["cards"][0]["reference"] in prompts[-1]
    assert "Original verified void reason" in prompts[-1]
    assert client.calls[-1] == pending and widget.pending is None
