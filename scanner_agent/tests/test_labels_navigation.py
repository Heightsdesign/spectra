"""Mapped Labels navigation and read-only safeguards; no hardware printing."""

# ruff: noqa: F811 -- imported fixtures.
import hashlib
import sqlite3
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_production_bridge import bridge  # noqa: F401
from test_selby_desktop import desktop  # noqa: F401
from test_selby_incoming import wait_until

from selby_workstation.incoming import PreviewError
from selby_workstation.label_mapping import checked_labels, mapped_orders


@pytest.fixture
def mapped(bridge):
    store, snapshot = bridge
    for card in snapshot["submission"]["cards"]:
        card["status"] = "matched"
    local = store.apply("http://local", snapshot, "Synthetic mapping for labels")
    snapshot["binding"].update(local_order_id=local["order_id"], cards=local["cards"])
    store.confirm("http://local", snapshot, "Synthetic confirmed mapping")
    context = mapped_orders(store.path)[0]
    labels = [
        dict(
            kind="order",
            reference=context["sp"],
            payload="SP:ORDER:1:" + context["sp"],
            text="2 active physical cards",
        )
    ]
    labels.extend(
        dict(
            kind="physical_card",
            reference=card["pc"],
            payload="SP:PC:1:" + card["pc"],
            text="Same card\nBase Set\n1 / FR",
        )
        for card in context["cards"]
    )
    state = dict(
        reference=context["sp"],
        actor="test-operator",
        labels=labels,
        print_eligible=False,
        blockers=["payment_unverified"],
        history=[],
    )

    class Client:
        connection = SimpleNamespace(backend_origin="http://local")

        def production(self, sid):
            return deepcopy(snapshot)

        def labels(self, sid):
            return deepcopy(state)

        def execute(self, operation):
            raise AssertionError("Preview must not POST")

    return store, context, Client(), snapshot, state


def logical_digest(path):
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


def test_mapped_page_orders_route_and_preview_keeps_print_blocked(desktop, mapped, monkeypatch):
    w, app, _ = desktop
    store, context, client, _, _ = mapped
    before = logical_digest(store.path)
    w.orders_path = store.path
    w.desktop.pages["Incoming Submissions"].auth = SimpleNamespace(intake_client=lambda: client)
    import selby_workstation.labels_ui as ui

    monkeypatch.setattr(ui, "native_printer", lambda *a: pytest.fail("Hardware forbidden"))
    monkeypatch.setattr(ui, "submit", lambda *a: pytest.fail("Hardware forbidden"))
    assert "Labels" in w.desktop.buttons
    assert not any(
        button.text() == "Labels · future" for button in w.desktop.findChildren(ui.QPushButton)
    )
    w.desktop.buttons["Labels"].click()
    page = w.desktop.pages["Labels"]
    wait_until(lambda: not page.busy)
    assert w.desktop.current == "Labels"
    page.orders.setCurrentIndex(1)
    page.open_button.click()
    wait_until(lambda: not page.dialog.busy)
    dialog = page.dialog
    assert dialog.state and dialog.labels.count() == 3
    assert context["order_id"] in dialog.heading.text()
    assert all(
        card["card_id"] in dialog.labels.item(i + 1).text()
        for i, card in enumerate(context["cards"])
    )
    for index in range(3):
        dialog.labels.clearSelection()
        dialog.labels.item(index).setSelected(True)
        dialog.buttons[1].click()
        wait_until(lambda: not dialog.busy)
        assert not dialog.preview.pixmap().isNull()
        assert "payment_unverified" in dialog.eligibility.text()
        assert not dialog.buttons[2].isEnabled() and not dialog.buttons[3].isEnabled()
        assert "payment" in dialog.buttons[2].toolTip()
    assert logical_digest(store.path) == before
    w.desktop.navigate("Orders")
    w.orders_dialog.open_order(context["order_id"])
    button = next(
        b
        for b in w.orders_dialog.findChildren(ui.QPushButton)
        if b.text() == "Print labels / preview…"
    )
    button.click()
    wait_until(lambda: not page.busy)
    assert (
        w.desktop.current == "Labels"
        and page.orders.currentData()["order_id"] == context["order_id"]
    )
    assert logical_digest(store.path) == before


@pytest.mark.parametrize(
    "change", ["origin", "registry", "order", "pair", "reference", "void", "unconfirmed", "stale"]
)
def test_reject_mapping_conflicts(mapped, change):
    store, context, client, snapshot, _ = mapped
    if change == "origin":
        client.connection = SimpleNamespace(backend_origin="http://other")
    if change == "registry":
        snapshot["binding"]["registry_id"] = "different"
    if change == "order":
        snapshot["binding"]["local_order_id"] = "ORD-999999"
    if change == "pair":
        snapshot["binding"]["cards"] = {}
    if change == "reference":
        snapshot["submission"]["reference"] = "SP-" + "0" * 32
    if change == "void":
        snapshot["submission"]["cards"][0]["status"] = "voided"
    if change == "unconfirmed":
        context["confirmed"] = 0
    if change == "stale":
        context["cards"][0]["pc"] = "PC-" + "0" * 32
    before = logical_digest(store.path)
    with pytest.raises(PreviewError):
        checked_labels(context, client)
    assert logical_digest(store.path) == before


def test_missing_or_legacy_registry_is_not_created_or_migrated(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    assert mapped_orders(missing) == [] and not missing.exists()
    from selby_workstation.orders import OrderStore

    legacy = OrderStore(tmp_path / "legacy.sqlite3")
    before = logical_digest(legacy.path)
    assert mapped_orders(legacy.path) == []
    assert logical_digest(legacy.path) == before


@pytest.mark.parametrize("failure", ["offline", "expired", "stale_content"])
def test_preview_failures_disable_printing(desktop, mapped, failure):
    w, _, _ = desktop
    store, context, client, _, state = mapped
    w.orders_path = store.path
    w.desktop.pages["Incoming Submissions"].auth = SimpleNamespace(intake_client=lambda: client)
    w.desktop.open_labels(context["order_id"])
    page = w.desktop.pages["Labels"]
    wait_until(lambda: not page.busy)
    page.open_selected()
    wait_until(lambda: not page.dialog.busy)
    dialog = page.dialog
    dialog.labels.item(0).setSelected(True)
    if failure == "stale_content":
        state["labels"][0]["text"] = "Changed active count"
    else:

        def fail(*args):
            raise PreviewError(
                "Session expired" if failure == "expired" else "Offline",
                disconnect=failure == "expired",
            )

        client.production = fail
    dialog.show_preview()
    wait_until(lambda: not dialog.busy)
    assert dialog.state is None and dialog.preview.pixmap().isNull()
    assert not dialog.buttons[2].isEnabled() and not dialog.buttons[3].isEnabled()
    assert "printing is disabled" in dialog.eligibility.text()
