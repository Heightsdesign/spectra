"""Scanner-only native key compatibility; never changes the active OS layout."""

# ruff: noqa: F401, F811 -- shared pytest fixtures
import ctypes
import os
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_scanner_ui import ui
from test_scanning import bridge, ready
from test_selby_incoming import wait_until

from selby_workstation.scanner_keyboard import (
    SYSTEM_PROFILE,
    TDW6_PROFILE,
    US_DIGITS,
    US_LETTERS,
    translate_key,
)

DIAGNOSTIC = "SELBY:TEST:V1:CALIBRATION"
RECEIVED = "SELBYMTESTMV&MCQLIBRQTION"


@pytest.fixture
def french():
    if sys.platform != "win32":
        pytest.skip("Windows layout API verification")
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    user.GetKeyboardLayoutList.restype = ctypes.c_int
    user.GetKeyboardLayout.argtypes = [ctypes.c_uint]
    user.GetKeyboardLayout.restype = ctypes.c_void_p
    user.MapVirtualKeyExW.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    user.MapVirtualKeyExW.restype = ctypes.c_uint
    user.ToUnicodeEx.argtypes = [
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_wchar_p,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    user.ToUnicodeEx.restype = ctypes.c_int
    layouts = (ctypes.c_void_p * user.GetKeyboardLayoutList(0, None))()
    user.GetKeyboardLayoutList(len(layouts), layouts)
    handle = next((h for h in layouts if h & 0xFFFFFFFF == 0x040C040C), None)
    if handle is None:
        pytest.skip("Standard French AZERTY layout is not installed; none will be activated")
    before = user.GetKeyboardLayout(0)
    yield user, handle
    assert user.GetKeyboardLayout(0) == before, "Active Windows layout changed"


def frame(widget, payload, french, caps=False):
    user, handle = french
    by_letter = {v: k for k, v in US_LETTERS.items()}
    by_digit = {v: k for k, v in US_DIGITS.items()}
    received = ""
    for char in payload:
        if char in by_letter:
            code, shift = by_letter[char], not caps
        elif char in by_digit:
            code, shift = by_digit[char], False
        else:
            code, shift = {":": (0x27, True), "-": (0x0C, False)}[char]
        vk = user.MapVirtualKeyExW(code, 3, handle)
        keys = (ctypes.c_ubyte * 256)()
        keys[0x10] = 0x80 if shift else 0
        keys[0x14] = 1 if caps else 0
        output = ctypes.create_unicode_buffer(8)
        assert user.ToUnicodeEx(vk, code, keys, output, len(output), 4, handle) == 1
        raw = output.value
        received += raw
        mods = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
        native = (1 if shift else 0) | (0x100 if caps else 0)
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            ord(raw.upper()) if len(raw.upper()) == 1 else 0,
            mods,
            code,
            vk,
            native,
            raw,
        )
        QApplication.sendEvent(widget, event)
    return received


def finish_scan(dialog):
    QTest.keyClick(dialog.scanner_input, Qt.Key.Key_Return)
    wait_until(lambda: not dialog.busy)


def select_profile(dialog):
    dialog.profile.setCurrentIndex(dialog.profile.findData(TDW6_PROFILE))


def screenshot(dialog, name):
    target = os.environ.get("SELBY_SCAN_SCREENSHOTS")
    if target:
        path = Path(target)
        path.mkdir(parents=True, exist_ok=True)
        assert dialog.grab().save(str(path / name))


def test_operator_observation_and_unchanged_system_default(ui, french):
    window, dialog, store, data, client = ui
    assert dialog.profile.currentData() == SYSTEM_PROFILE
    assert frame(dialog.scanner_input, DIAGNOSTIC, french) == RECEIVED
    finish_scan(dialog)
    assert "Invalid" in dialog.status.text()
    select_profile(dialog)
    frame(dialog.scanner_input, DIAGNOSTIC, french)
    dialog.show_diagnostic.setChecked(True)
    finish_scan(dialog)
    assert "Diagnostic recognized" in dialog.status.text()
    assert RECEIVED in dialog.input_diagnostic.text()
    assert "Validated payload: " + DIAGNOSTIC in dialog.input_diagnostic.text()
    assert window.session is None
    screenshot(dialog, "azerty-diagnostic.png")
    frame(dialog.scanner_input, DIAGNOSTIC, french)
    finish_scan(dialog)
    assert "Repeated scan ignored" in dialog.status.text()


@pytest.mark.parametrize("caps", [False, True])
def test_exact_pc_all_hex_and_payment_gate(ui, french, caps):
    window, dialog, store, data, client = ui
    select_profile(dialog)
    # Existing synthetic mapping includes arbitrary hex/digits; every character is native-key decoded.
    card = data["submission"]["cards"][1]
    data["inspection"][card["id"]].update(eligible=False, reasons=[{"code": "payment_unverified"}])
    before = store.path.read_bytes()
    payload = "SP:PC:1:" + card["reference"]
    frame(dialog.scanner_input, payload, french, caps=caps)
    finish_scan(dialog)
    assert card["reference"] in dialog.status.text()
    assert data["binding"]["cards"][card["id"]] in dialog.status.text()
    assert "BLOCKED" in dialog.status.text()
    assert "payment_unverified" in dialog.status.text()
    assert "Validated payload: " + payload in dialog.input_diagnostic.text()
    assert store.path.read_bytes() == before
    assert window.session is None
    dialog.show_diagnostic.setChecked(True)
    screenshot(dialog, "azerty-unpaid-card.png")


def test_entire_production_alphabet_and_order_lookup(ui, french):
    _, dialog, _, data, _ = ui
    select_profile(dialog)
    payload = "SP:PC:1:PC-0123456789ABCDEF0123456789ABCDEF"
    frame(dialog.scanner_input, payload, french)
    assert dialog.scanner_input.decoded == payload
    dialog.scanner_input.clear()
    frame(dialog.scanner_input, "SP:ORDER:1:" + data["submission"]["reference"], french)
    finish_scan(dialog)
    assert "Order lookup:" in dialog.status.text()


def test_manual_paste_and_typing_are_unchanged(ui):
    _, dialog, _, _, _ = ui
    select_profile(dialog)
    QApplication.clipboard().setText(DIAGNOSTIC)
    dialog.input.setFocus()
    QTest.keyClick(dialog.input, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert dialog.input.text() == DIAGNOSTIC
    dialog.submit()
    assert "Diagnostic recognized" in dialog.status.text()
    dialog.last = None
    QTest.keyClicks(dialog.input, RECEIVED)
    assert dialog.input.text() == RECEIVED
    dialog.submit()
    assert "Invalid" in dialog.status.text()


def test_truncation_missing_native_and_profile_reset(ui, french):
    _, dialog, _, _, _ = ui
    select_profile(dialog)
    frame(dialog.scanner_input, "SP:PC:1:PC-123", french)
    finish_scan(dialog)
    assert "Invalid" in dialog.status.text()
    QTest.keyClicks(dialog.scanner_input, DIAGNOSTIC)
    finish_scan(dialog)
    assert "native key information" in dialog.status.text()
    assert "Validated payload: REJECTED" in dialog.input_diagnostic.text()
    frame(dialog.scanner_input, "SP:PC:", french)
    dialog.profile.setCurrentIndex(0)
    assert dialog.scanner_input.decoded == ""
    assert dialog.scanner_input.received == ""


def test_no_suffix_and_restart_preference(ui, french):
    _, dialog, _, _, _ = ui
    select_profile(dialog)
    dialog.suffix.setCurrentIndex(1)
    frame(dialog.scanner_input, DIAGNOSTIC, french)
    QTest.keyClick(dialog.scanner_input, Qt.Key.Key_Return)
    assert "Diagnostic recognized" not in dialog.status.text()
    dialog.submit_scanner()
    assert "Diagnostic recognized" in dialog.status.text()
    settings = QSettings(dialog.shell.settings.fileName(), QSettings.Format.IniFormat)
    assert settings.value("scanner/profile") == TDW6_PROFILE
    from selby_workstation.scanner_ui import ScannerDialog

    reopened = ScannerDialog(dialog.shell)
    assert reopened.profile.currentData() == TDW6_PROFILE
    assert reopened.suffix.currentIndex() == 1
    reopened.close()


@pytest.mark.parametrize(
    "code,native,shift",
    [
        (0, 0, False),
        (0xE01E, 1, True),
        (0x1E, 0, True),
        (0x1E, 1, False),
        (0x1E, 3, True),
        (0x1E, 0x41, True),
        (0x1E, 0, False),
        (0x02, 1, True),
        (0x27, 0, False),
        (0x0C, 1, True),
    ],
)
def test_unsupported_keys_rejected(code, native, shift):
    with pytest.raises(ValueError):
        translate_key(code, native, shift)


def test_shift_sides_caps_and_digit_rules():
    assert translate_key(0x1E, 0x10, True) == "A"
    assert translate_key(0x1E, 0x100, False) == "A"
    assert translate_key(0x02, 0x100, False) == "1"
    with pytest.raises(ValueError):
        translate_key(0x1E, 0x101, True)


def test_real_windows_message_native_metadata(ui):
    """Post a key message only to our own Qt widget; no SendInput or layout activation."""
    if QApplication.platformName() != "windows":
        pytest.skip("Requires the real Windows Qt platform")
    from PySide6.QtCore import QObject

    _, dialog, _, _, _ = ui
    select_profile(dialog)
    received = []

    class Observe(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Type.KeyPress:
                received.append(
                    (
                        event.nativeScanCode(),
                        event.nativeVirtualKey(),
                        event.nativeModifiers(),
                        event.modifiers(),
                    )
                )
            return False

    observer = Observe(dialog.scanner_input)
    dialog.scanner_input.installEventFilter(observer)
    dialog.activateWindow()
    dialog.scanner_input.setFocus()
    QApplication.processEvents()
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    user.PostMessageW.restype = ctypes.c_int
    hwnd = int(dialog.scanner_input.winId())
    assert user.PostMessageW(hwnd, 0x100, 0x31, 1 | (0x02 << 16))
    assert user.PostMessageW(hwnd, 0x101, 0x31, 1 | (0x02 << 16) | (1 << 30) | (1 << 31))
    wait_until(lambda: bool(received))
    scan, vk, native, modifiers = received[0]
    assert scan == 0x02
    assert vk == 0x31
    assert bool(native & 0x11) == bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    assert native & ~0x711 == 0
    dialog.scanner_input.clear()


def test_unsupported_native_event_latches_until_clear(ui, french):
    _, dialog, _, _, _ = ui
    select_profile(dialog)
    bad = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ShiftModifier, 0x1E, 0x51, 0, "Q"
    )
    QApplication.sendEvent(dialog.scanner_input, bad)
    frame(dialog.scanner_input, DIAGNOSTIC, french)
    finish_scan(dialog)
    assert "inconsistent native keyboard modifiers" in dialog.status.text()
    assert "Validated payload: REJECTED" in dialog.input_diagnostic.text()
    frame(dialog.scanner_input, DIAGNOSTIC, french)
    finish_scan(dialog)
    assert "Diagnostic recognized" in dialog.status.text()


def test_shifted_return_is_a_suffix_not_payload(ui, french):
    _, dialog, _, _, _ = ui
    select_profile(dialog)
    frame(dialog.scanner_input, DIAGNOSTIC, french)
    QTest.keyClick(dialog.scanner_input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert "Diagnostic recognized" in dialog.status.text()
