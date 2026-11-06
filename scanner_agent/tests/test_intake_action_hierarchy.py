"""Visibility is distinct from safety availability; semantic colors are explicit."""
# ruff: noqa: F811 -- imported pytest fixture.

import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from test_intake_void_gui import eligible
from test_physical_intake import intake  # noqa: F401
from test_selby_incoming import wait_until

from selby_workstation.operational_style import ACTION_COLORS


def test_default_matched_selection_keeps_void_visible_and_explains_protection(intake):
    widget, client, _, _ = intake
    client.data["cards"][0].update(void_eligible=False, void_blockers=["card_not_unidentified"])
    widget.refresh()
    wait_until(lambda: not widget.busy)
    button = widget.buttons["void"]
    assert button.isVisible() and not button.isEnabled()
    assert "protected" in button.toolTip()
    assert "Matched" in widget.void_hint.text()


def test_pending_complete_intent_blocks_eligible_pc_without_hiding_action(intake):
    widget, client, journal, _ = intake
    eligible(widget, client)
    intent = journal.begin(
        widget.scope,
        widget.sid,
        "transition",
        {"action": "complete", "reason": "Original operator decision"},
    )
    widget.refresh()
    wait_until(lambda: not widget.busy)
    button = widget.buttons["void"]
    assert button.isVisible() and not button.isEnabled()
    assert "Backend eligible" in widget.void_hint.text()
    assert "Pending transition 'complete'" in button.toolTip()
    assert "Local safety block" in widget.void_hint.text()
    assert "complete" in widget.recovery.text()
    assert not widget.retry_button.isEnabled() and widget.review_button.isEnabled()
    assert journal.pending(widget.scope, widget.sid) == intent and not client.calls


def test_void_stays_in_view_while_form_and_history_are_navigated(intake):
    widget, _, _, _ = intake
    widget.resize(1100, 850)
    scroll = widget.findChild(QScrollArea)
    for value in (0, scroll.verticalScrollBar().maximum()):
        scroll.verticalScrollBar().setValue(value)
        QApplication.processEvents()
        button = widget.buttons["void"]
        assert button.isVisible()
        assert widget.rect().contains(button.mapTo(widget, button.rect().center()))
        assert not scroll.isAncestorOf(button)
    for index in range(widget.review_tabs.count()):
        widget.review_tabs.setCurrentIndex(index)
        assert widget.buttons["void"].isVisible()


def _pixel(button):
    QApplication.processEvents()
    return button.grab().toImage().pixelColor(5, button.height() // 2).name()


def _luminance(hex_color):
    channels = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in channels]
    return sum(x * weight for x, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


@pytest.mark.parametrize("role", ACTION_COLORS)
def test_semantic_text_contrast(role):
    _, background, foreground, hover = ACTION_COLORS[role]
    for fill in (background, hover):
        assert (_luminance(foreground) + 0.05) / (_luminance(fill) + 0.05) >= 4.5


def test_enabled_roles_and_disabled_neutral_rendering(intake):
    widget, client, journal, _ = intake
    eligible(widget, client)
    button = widget.buttons["void"]
    assert button.isEnabled() and button.property("actionRole") == "destructive"
    for key, role in [
        ("card", "primary"),
        ("match", "primary"),
        ("complete", "success"),
        ("issue", "warning"),
    ]:
        assert widget.buttons[key].property("actionRole") == role
    enabled = _pixel(button)
    journal.begin(
        widget.scope, widget.sid, "transition", {"action": "complete", "reason": "Review first"}
    )
    widget.refresh()
    wait_until(lambda: not widget.busy)
    assert not button.isEnabled()
    disabled = _pixel(button)
    assert enabled != disabled
    assert disabled == _pixel(widget.buttons["card"])  # No destructive tint when disabled.
    assert button.toolTip() and button.accessibleDescription()


def test_available_void_retains_keyboard_focus_and_confirmation_handler(intake):
    widget, client, _, _ = intake
    eligible(widget, client)
    widget.reason.setText("Synthetic explicit correction")
    button = widget.buttons["void"]
    button.setFocus()
    assert button.hasFocus() and button.focusPolicy() != Qt.FocusPolicy.NoFocus
    QTest.keyClick(button, Qt.Key.Key_Space)
    wait_until(lambda: not widget.busy)
    assert client.calls[-1]["kind"] == "void"


def test_synthetic_native_enabled_action_palette(intake):
    widget, client, _, _ = intake
    eligible(widget, client)
    widget.layout().itemAt(0).widget().setText(
        "STYLE DEMONSTRATION / SYNTHETIC FIXTURE / NO LIVE ORDER"
    )
    widget.resize(1500, 1000)
    widget.buttons["void"].setFocus()
    QApplication.processEvents()
    for key in ("card", "match", "complete", "void", "issue"):
        assert widget.buttons[key].isVisible() and widget.buttons[key].isEnabled()
    assert not client.calls
    screenshot = os.environ.get("SELBY_STYLE_SCREENSHOT")
    if screenshot:
        assert widget.grab().save(screenshot)
