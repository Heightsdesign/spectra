"""Bounded US Set-1 key decoding, solely for the explicit Windows scanner field.

Qt WindowsNativeModifiers values are defined in qwindowskeymapper.h (Qt 6).
No character substitution, OS layout activation, or device-wide keyboard hook.
"""

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLineEdit

SYSTEM_PROFILE = "system"
TDW6_PROFILE = "tdw6-us-to-fr"
PROFILES = (
    ("System keyboard layout (default)", SYSTEM_PROFILE),
    ("TD-W6 US keyboard output → French AZERTY interpretation", TDW6_PROFILE),
)

US_LETTERS = {
    **dict(zip(range(0x10, 0x1A), "QWERTYUIOP", strict=True)),
    **dict(zip(range(0x1E, 0x27), "ASDFGHJKL", strict=True)),
    **dict(zip(range(0x2C, 0x33), "ZXCVBNM", strict=True)),
}
US_DIGITS = dict(zip(range(0x02, 0x0C), "1234567890", strict=True))


def translate_key(scan_code, native_modifiers, shift):
    """Decode only the physical keys needed by strict QR v1 and calibration."""
    # Qt: ShiftAny=0x11, CtrlAny=0x22, AltAny=0x44, MetaAny=0x88,
    # CapsLock=0x100, NumLock=0x200, ScrollLock=0x400, ExtendedKey=0x1000000.
    if native_modifiers & ~0x711 or bool(native_modifiers & 0x11) != shift:
        raise ValueError("Unsupported or inconsistent native keyboard modifiers.")
    if scan_code in US_LETTERS:
        if not (shift ^ bool(native_modifiers & 0x100)):
            raise ValueError("Lowercase US output is unsupported by the QR contract.")
        return US_LETTERS[scan_code]
    if scan_code in US_DIGITS and not shift:
        return US_DIGITS[scan_code]
    if scan_code == 0x27 and shift:
        return ":"
    if scan_code == 0x0C and not shift:
        return "-"
    raise ValueError("Missing or unsupported US scanner key information.")


class ScannerInput(QLineEdit):
    scan_returned = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = SYSTEM_PROFILE
        self.setReadOnly(True)
        self.setPlaceholderText("Physical scanner input · manual input/paste below")
        self.clear()

    def clear(self):
        super().clear()
        self.received = ""
        self.decoded = ""
        self.error = None

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & ~(
                Qt.KeyboardModifier.KeypadModifier | Qt.KeyboardModifier.ShiftModifier
            ):
                self.error = "Unsupported modified scan terminator. Clear and scan again."
            self.scan_returned.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Shift, Qt.Key.Key_CapsLock):
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Escape):
            if self.received:
                self.error = "Scan interrupted. Clear and scan the complete label again."
            super().keyPressEvent(event)
            return
        if self.error:
            event.accept()
            return
        try:
            if event.isAutoRepeat() or event.count() != 1:
                raise ValueError("Repeated or combined key event. Clear and scan again.")
            if event.modifiers() & ~(Qt.KeyboardModifier.ShiftModifier):
                raise ValueError(
                    "Unsupported scanner shortcut/modifier. Use the manual paste field."
                )
            if len(event.text()) != 1 or len(self.received) >= 256:
                raise ValueError("Missing, combined or oversized scanner input.")
            self.received += event.text()
            self.setText(self.received)
            if self.profile == TDW6_PROFILE:
                if sys.platform != "win32" or not event.nativeVirtualKey():
                    raise ValueError(
                        "Windows native key information unavailable. Use manual input."
                    )
                value = translate_key(
                    event.nativeScanCode(),
                    event.nativeModifiers(),
                    bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
                )
            else:
                value = event.text()
            self.decoded += value
        except ValueError as exc:
            self.error = str(exc)
        event.accept()

    def inputMethodEvent(self, event):
        self.error = "IME input is unsupported in scanner capture. Use manual input."
        event.accept()
