# SELBY Workstation V0.5c.1 — validation

Date: 2026-11-02. Windows, PySide6/Qt **6.12.0**.

## Results

- **60 passed**, native Windows Qt (`QT_QPA_PLATFORM=windows`), final regression run, 19.81 seconds.
- Focused offscreen keyboard-profile run: **20 passed, 1 skipped**. The skipped check intentionally requires real Windows Qt message delivery; it passed in the native run.
- Existing V0.5c resolver/UI regression: **22 passed** before the new profile tests.
- Ruff passes for `scanner_keyboard.py`, `scanner_ui.py` and `test_scanner_keyboard.py`.
- The actual `.pyw` launcher starts V0.5c.1 successfully, showing Dashboard with no image, report, grading or order loaded.

## Native verification method

The profile tests use the installed **standard French AZERTY** layout handle (`040C040C`). Windows `MapVirtualKeyExW` and `ToUnicodeEx` with a nonmutating flag generate received French characters for specified physical keys and modifier state. Those characters and native fields are delivered to the real scanner widget through constructed QKeyEvents. No keyboard layout is loaded, activated or changed. Each French-layout fixture asserts that the active thread keyboard-layout handle is identical before and after testing.

A separate native test posts one key-down/key-up message **only to its own Qt window**. It confirms the actual Windows-to-Qt path exposes scan code `0x02`, native virtual key `0x31` and consistent modifier fields. It does not use SendInput, automate scanner hardware, or send keystrokes to another application. Full diagnostic/card tests use software-generated events; physical TD-W6 timing and actual modifier sequences remain unverified.

The operator's observed string is reproduced exactly through the French Windows layout API:

```text
SELBYMTESTMV&MCQLIBRQTION
```

Under System profile it fails the strict decoder. Under the TD-W6 profile the same physical key positions validate as:

```text
SELBY:TEST:V1:CALIBRATION
```

[Microsoft MapVirtualKeyExW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-mapvirtualkeyexw) documents explicit-layout scan/virtual-key mapping. [Microsoft ToUnicodeEx](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-tounicodeex) documents explicit key-state interpretation and the flag used to avoid changing keyboard state.

## Coverage

| Acceptance concern | Automated evidence |
| --- | --- |
| Default unchanged | Fresh profile is System; French diagnostic text is rejected |
| Reported AZERTY diagnostic | Exact observed raw string; exact validated diagnostic; no grading opened |
| Production characters | `SP:PC:1:PC-0123456789ABCDEF0123456789ABCDEF` translates exactly; order QR lookup also tested |
| Exact physical copy | Existing synthetic order contains two identical-name cards; translated second PC resolves its exact mapped SLB-C |
| Shift/Caps state | Left/right Shift, Caps Lock uppercase, digits with Caps Lock; lowercase and conflicting Shift/Caps rejected |
| Ambiguous/unsupported keys | Missing/extended key codes, inconsistent native/Qt modifiers, Ctrl/Alt, shifted digits/minus and unshifted semicolon rejected |
| Invalid/truncated QR | Translated incomplete PC rejected by unchanged decoder; existing invalid/version/case/URL tests retained |
| Error frame isolation | Unsupported key latches rejection even if valid-looking keys follow; subsequent fresh frame succeeds |
| Manual paste/input | Clipboard paste of canonical diagnostic remains exact; manually typed corrupted diagnostic remains unchanged and fails |
| Suffix handling | Enter, Shift+Return and explicit no-suffix Identify scan path |
| Duplicate protection | Repeated corrected diagnostic suppressed; existing repeated-card tests retained |
| Local profile persistence | QSettings profile and suffix restored in a newly constructed dialog; partial capture reset on profile change |
| Ordinary keyboard fields | Existing Orders search-field typing test retained; no application/global keyboard hook |
| Payment gates/data integrity | Translated PC remains blocked for `payment_unverified`, no session or registry-byte change |
| Evidence/session behavior | Existing saved-dossier resume and checksum preservation; explicit authorized new-image flow retained |
| Production/grading regression | Existing bridge, bridge-GUI and grading-GUI tests included in 60-check run |
| Real native metadata | Window-targeted Windows message reaches QKeyEvent with expected native key data |

Synthetic registries, settings and test-session drafts are isolated in test directories. No development production order was edited, and no payment/custody restriction was overridden. No backend implementation, production identity decoder, mapping model or grading component was changed for this release.

## Native screenshots

- [AZERTY diagnostic and validated payload](validation_artifacts/v05c1/azerty-diagnostic.png)
- [Exact card identity with payment block](validation_artifacts/v05c1/azerty-unpaid-card.png)
- [Real V0.5c.1 launcher](validation_artifacts/v05c1/native-launcher.png)

Screenshots use software-generated input and controlled synthetic backend responses. They are not photographs or evidence of physical scans. Live backend acceptance from V0.5c is documented separately; no new live paid state was manufactured for V0.5c.1.

## Exact commands

Run from the repository root. Create the parent artifact directory first and use a fresh basetemp directory for each run.

```powershell
$env:QT_QPA_PLATFORM='windows'
$env:SELBY_SCAN_SCREENSHOTS="$PWD/validation_artifacts/v05c1"
scanner_agent/.venv-analysis/Scripts/python.exe -m pytest scanner_agent/tests/test_scanner_keyboard.py scanner_agent/tests/test_scanning.py scanner_agent/tests/test_scanner_ui.py scanner_agent/tests/test_production_bridge.py scanner_agent/tests/test_production_bridge_gui.py scanner_agent/tests/test_selby_grading_gui.py -q -p no:cacheprovider --basetemp=validation_artifacts/v05c1/native-final
scanner_agent/.venv-analysis/Scripts/python.exe -m ruff check scanner_agent/selby_workstation/scanner_keyboard.py scanner_agent/selby_workstation/scanner_ui.py scanner_agent/tests/test_scanner_keyboard.py
scanner_agent/.venv-analysis/Scripts/python.exe scanner_agent/selby_desktop.pyw --smoke-test --screenshot validation_artifacts/v05c1/native-launcher.png
```

The smoke screenshot path must not already exist. No test alters the active Windows keyboard layout. The layout-API tests skip with a reason if the standard French layout is not installed; none was skipped in the native acceptance run.

## Physical acceptance and limits

**Pending operator action:** real TD-W6 diagnostic scan and real synthetic physical-card label scan while Windows remains French AZERTY. Record received/validated payloads, exact mapped PC/ORD/SLB-C, blocked commercial state, repeat behavior and profile restoration after restart. See [operator instructions](SELBY_WORKSTATION_V05C1_OPERATOR.md).

The software cannot distinguish the TD-W6 from another keyboard inside the dedicated scanner field. Device variants that send Unicode-only input or unsupported scan-code/modifier sequences fail closed. This profile does not repair arbitrary already-corrupted pasted text and does not claim scanner connection monitoring. Existing V0.5c backend custody/session restrictions remain in force, including conservative blocking for `operation_conflict`.
