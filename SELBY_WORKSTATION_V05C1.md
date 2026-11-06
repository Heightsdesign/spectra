# SELBY Workstation V0.5c.1 — scanner keyboard compatibility

## Delivered behavior

Scan card now offers two locally stored scanner profiles:

- **System keyboard layout (default)**: use the characters Windows supplies.
- **TD-W6 US keyboard output → French AZERTY interpretation**: decode native US physical key positions before passing the result to the unchanged strict QR decoder.

Windows can remain in French AZERTY. The application does not activate, install, switch or globally remap a keyboard layout, and installs no global input hook. The TD-W6 keyboard-wedge transport is confirmed by the operator; physical acceptance of this new correction profile is still pending.

The dialog has separate **Physical scanner input** and **Manual QR input / paste** fields. Translation applies only to key events in Physical scanner input while the TD-W6 profile is selected. Manual typing and clipboard paste are submitted exactly as entered. The scanner field does not accept paste or text editing; use the separate manual field. Ordinary typing elsewhere in the application and Windows is unaffected.

## Audit and implementation

Audited V0.5c `scanner_ui.py`, `scanning.py`, desktop scanner action/focus, existing Qt worker and duplicate behavior, the V0.5b.1 fixed diagnostic decoder, and `backend/app/physical_identity.py`. Production grammar remains `SP:PC:1:PC-<32 uppercase hexadecimal digits>` and `SP:ORDER:1:SP-<32 uppercase hexadecimal digits>`. Diagnostic remains exactly `SELBY:TEST:V1:CALIBRATION`. Neither decoder nor identity/eligibility resolution was changed.

Added `scanner_keyboard.py`: a bounded Windows Set-1 key decoder. It consumes `QKeyEvent.nativeScanCode()` and native modifier state. It uses the physical US letter/digit keys, shifted semicolon for colon, and unshifted minus. Shift and Caps Lock determine US letter case; lowercase output is rejected, never uppercased opportunistically. Shift consistency is checked against Qt modifiers. Native virtual-key information must be present, but is not used to infer US letters because Windows virtual keys depend on layout. The received French text is displayed for diagnosis, not used as a substitution table.

The Qt Windows modifier masks are defined in the [Qt Windows key mapper](https://raw.githubusercontent.com/qt/qtbase/dev/src/plugins/platforms/windows/qwindowskeymapper.h); the supported native fields are described in [QKeyEvent](https://doc.qt.io/qt-6/qkeyevent.html). Windows scan codes describe key positions while character interpretation depends on keyboard state/layout; see [Microsoft keyboard input documentation](https://learn.microsoft.com/en-us/windows/win32/inputdev/about-keyboard-input). This is why replacing `M` with `:` or `Q` with `A` in arbitrary strings would be unsafe.

Unsupported/missing/extended scan codes, inconsistent modifiers, Ctrl/Alt/AltGr/Meta combinations, lowercase US output, dead/IME input, repeated or combined key events and oversized frames fail closed. An error latches for that frame; a valid suffix reports rejection and resets capture. A profile change or Clear scanner input also resets capture. Truncated translated payloads still fail the original strict decoder. No partial or ambiguous identity reaches backend lookup.

Key-level information is available and verified on native Windows Qt, so no character-learning calibration or additional diagnostic QR was introduced. Devices that do not supply supported native key information are rejected rather than guessed.

Updated `scanner_ui.py` provides the selector, separate manual path, scanner capture controls and optional **Show last input diagnostic (memory only)**. It shows received characters and the full strict-decoder-validated payload, or REJECTED. Payload validity does not assert backend authorization. This diagnostic accesses no credentials and writes no log/settings history. It remains in the dialog's memory until replaced or the process closes. Selected profile alone is persisted under `scanner/profile` in the existing desktop INI; existing suffix preference is retained. Unknown stored profile identifiers fall back to System.

`desktop.py` focuses the physical field when Scan card opens. Workstation title/launcher text now identify V0.5c.1. Existing Enter/Return and no-suffix modes, two-second canonical-payload duplicate protection, bounded background lookup, close guards, immutable bridge checks, payment/inspection restrictions, evidence verification and explicit session creation/association are retained.

## Limits

A keyboard wedge shares the keyboard stream. Qt does not reliably identify which attached keyboard emitted these events; **any keyboard typed into Physical scanner input is treated under the selected profile**. Use Manual QR input for human typing and paste. The profile does not monitor scanner connection.

The implementation is specific to Windows Qt native Set-1 key events and US scanner output. Unicode-only injection, keypad character variants and unsupported device modes are rejected. No silent character-substitution fallback exists. Qt upgrades should repeat the native metadata tests.

No production record, backend contract, commercial gate, custody record or grading evidence was modified by this implementation. Test data was created only in isolated synthetic registries. See [validation](SELBY_WORKSTATION_V05C1_VALIDATION.md) and [operator instructions](SELBY_WORKSTATION_V05C1_OPERATOR.md).
