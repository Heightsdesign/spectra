"""Explicit form edits: wheel gestures belong to the surrounding page."""

from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class _PageWheelPolicy:
    def wheelEvent(self, event):
        # Ignore even when focused. Qt propagates the original event to the
        # parent scroller, preserving pixel deltas and touchpad gestures.
        # Combo popup views are separate widgets and keep native scrolling.
        event.ignore()


class FormComboBox(_PageWheelPolicy, QComboBox):
    """Selection changes require a click, keyboard or explicit popup choice."""


class FormSpinBox(_PageWheelPolicy, QSpinBox):
    """Integer edits retain keyboard entry and explicit spin buttons."""


class FormDoubleSpinBox(_PageWheelPolicy, QDoubleSpinBox):
    """Decimal edits retain keyboard entry and explicit spin buttons."""
