"""Wheel navigation must never edit operational fields, including focused ones."""
# ruff: noqa: E402, F811 -- Qt environment and imported pytest fixture.

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QVBoxLayout,
    QWidget,
)
from test_physical_intake import intake  # noqa: F401

from selby_workstation.form_widgets import FormComboBox, FormDoubleSpinBox, FormSpinBox


def wheel(widget, delta=-120, popup=False):
    if popup:
        position = widget.rect().center()
        event = QWheelEvent(
            QPointF(position),
            QPointF(widget.mapToGlobal(position)),
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(widget, event)
    else:
        position = widget.mapTo(widget.window(), widget.rect().center())
        QTest.wheelEvent(widget.window().windowHandle(), QPointF(position), QPoint(0, delta))
    QApplication.processEvents()


@pytest.fixture
def form():
    app = QApplication.instance() or QApplication([])
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    content.setMinimumHeight(1200)
    layout = QVBoxLayout(content)
    layout.addSpacing(80)
    combo, integer, decimal = FormComboBox(), FormSpinBox(), FormDoubleSpinBox()
    combo.addItems([f"Entry {i}" for i in range(40)])
    combo.setCurrentIndex(10)
    for widget in (integer, decimal):
        widget.setRange(0, 100)
        widget.setValue(10)
    for widget in (combo, integer, decimal):
        layout.addWidget(widget)
    layout.addStretch()
    scroll.setWidget(content)
    scroll.resize(320, 240)
    scroll.show()
    assert QTest.qWaitForWindowExposed(scroll)
    scroll.activateWindow()
    QTest.qWait(50)
    app.processEvents()
    yield scroll, combo, integer, decimal
    combo.hidePopup()
    scroll.close()
    app.processEvents()


@pytest.mark.parametrize("field", [1, 2, 3])
@pytest.mark.parametrize("focused", [False, True])
def test_wheel_preserves_values_and_scrolls_parent(form, field, focused):
    scroll, combo, integer, decimal = form
    widget = form[field]
    if focused:
        widget.setFocus()
    else:
        widget.clearFocus()
    scroll.verticalScrollBar().setValue(0)
    before = combo.currentIndex(), integer.value(), decimal.value()
    wheel(widget)
    assert (combo.currentIndex(), integer.value(), decimal.value()) == before
    assert scroll.verticalScrollBar().value() > 0
    position = scroll.verticalScrollBar().value()
    wheel(widget, 120)
    assert scroll.verticalScrollBar().value() < position
    assert (combo.currentIndex(), integer.value(), decimal.value()) == before


@pytest.mark.parametrize("field", [2, 3])
def test_spin_keyboard_typing_and_explicit_buttons_work(form, field):
    widget = form[field]
    widget.setFocus()
    QTest.keyClick(widget, Qt.Key.Key_Up)
    assert widget.value() == 11
    widget.selectAll()
    QTest.keyClicks(widget, "25")
    QTest.keyClick(widget, Qt.Key.Key_Return)
    assert widget.value() == 25
    option = QStyleOptionSpinBox()
    widget.initStyleOption(option)
    up = widget.style().subControlRect(
        QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, widget
    )
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=up.center())
    assert widget.value() == 26


def test_combo_keyboard_and_popup_scrolling_and_click_work(form):
    scroll, combo, _, _ = form
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() == 11
    view = combo.view()
    combo.showPopup()
    assert QTest.qWaitForWindowExposed(view.window())
    assert view.isVisible()
    view.window().resize(300, 140)
    QApplication.processEvents()
    bar = view.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    parent_position = scroll.verticalScrollBar().value()
    wheel(view.viewport(), popup=True)
    assert bar.value() > 0
    assert scroll.verticalScrollBar().value() == parent_position
    index = view.indexAt(QPoint(10, 10))
    assert index.isValid()
    QTest.mouseMove(view.viewport(), view.visualRect(index).center())
    QTest.qWait(250)
    QTest.mouseClick(
        view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(index).center(), delay=50
    )
    assert combo.currentIndex() == index.row() and not view.isVisible()


def test_intake_all_selectors_and_quantity_survive_page_scrolling(intake):
    widget, client, journal, _ = intake
    fields = widget.findChildren(QComboBox) + widget.findChildren(QSpinBox)
    assert len(fields) == 7
    scroll = widget.findChild(QScrollArea)
    widget.resize(900, 500)
    QApplication.processEvents()
    for field in fields:
        assert isinstance(field, (FormComboBox, FormSpinBox))
        if isinstance(field, QComboBox):
            field.addItem("Second explicit choice", "synthetic-choice")
            field.setCurrentIndex(field.count() - 1)
        else:
            field.setValue(3)

    def values():
        return [
            (f.currentIndex(), f.currentData()) if isinstance(f, QComboBox) else f.value()
            for f in fields
        ]

    before = values()
    for field in fields:
        scroll.ensureWidgetVisible(field)
        field.setFocus()
        QApplication.processEvents()
        start = scroll.verticalScrollBar().value()
        wheel(field)
        assert scroll.verticalScrollBar().value() > start
        assert values() == before
    assert not client.calls and journal.pending(widget.scope, widget.sid) is None
