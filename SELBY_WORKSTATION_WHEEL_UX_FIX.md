# Workstation mouse-wheel form safety

Date: 2026-10-31.

The Physical Intake dialog contains six wheel-sensitive combo boxes (parcel, physical card, declared entry, discrepancy, discrepancy kind and resolution) and one quantity spin box. The inspection sidebar also scrolls, and DesktopShell wraps Orders, Grading and Condition dialogs in scroll areas. Their selectors and integer/decimal spin boxes need the same protection.

Added shared `FormComboBox`, `FormSpinBox` and `FormDoubleSpinBox` subclasses in `scanner_agent/selby_workstation/form_widgets.py`. Their common policy ignores wheel events even when focused. Qt's normal window-event propagation then scrolls the surrounding page with the original wheel/trackpad event. There is no manual forwarding, synthetic scroll increment, global filter or focus-dependent exception. Explicit typing, keyboard navigation, mouse selection and spin buttons retain Qt behavior. Combo popup item views are separate widgets and retain their existing wheel scrolling and selection handling.

The five operational UI modules (`intake_ui.py`, `orders_ui.py`, `grading_ui.py`, `condition_ui.py`, `app.py`) import these subclasses under their existing Qt constructor names. No form layout, backend code, migration, grading rule/evidence, production identity mapping or stored record was changed. Standalone connection/production settings without page scroll areas were left alone. Canvas zoom and table scrolling are unchanged.

## Validation

- Final focused wheel Qt suite: **10 passed**, 1.08 seconds, offscreen.
- Native Windows Qt wheel suite: **10 passed**, 1.49 seconds, `QT_QPA_PLATFORM=windows`.
- Workstation/auth/intake/production bridge regressions including the wheel tests: **194 passed, 1 skipped**, 58.89 seconds. The skip is the existing opt-in Credential Manager roundtrip.
- FastAPI/PostgreSQL intake/reconciliation/production client and concurrency regressions: **48 passed**, 14 existing dependency/configuration warnings, 98.74 seconds.
- Ruff check and formatting of the shared widgets and new test file passed; `git diff --check` passed with existing line-ending notices.

Tests cover focused and unfocused combo/integer/decimal controls, unchanged values, parent scrolling in both directions, keyboard and typed numeric edits, clicked spin buttons, keyboard combo changes, scrolling/clicking an open dropdown, and all seven actual intake fields remaining unchanged while the parent page scrolls. Intake scrolling issues no write requests and creates no pending journal operation. Page wheel tests use QtTest's window-level wheel dispatch so Qt performs actual hit-testing and parent propagation; popup wheel tests address its viewport. The popup test explicitly opens the dropdown and waits for its window exposure, including Windows animation, before inspecting or clicking it. Earlier native attempts failed because they inspected the animated popup before exposure; the final test passes without changing popup implementation or styling.

Commands from `scanner_agent`:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv-analysis/Scripts/python.exe -m pytest tests/test_form_wheel.py -q -p no:cacheprovider
$workstationTests=Get-ChildItem tests/test_selby*.py | ForEach-Object { $_.FullName }
.venv-analysis/Scripts/python.exe -m pytest @workstationTests tests/test_connection_settings.py tests/test_desktop_auth.py tests/test_desktop_auth_gui.py tests/test_physical_intake.py tests/test_production_bridge.py tests/test_production_bridge_gui.py tests/test_form_wheel.py -q -p no:cacheprovider

$env:QT_QPA_PLATFORM='windows'
.venv-analysis/Scripts/python.exe -m pytest tests/test_form_wheel.py -q -p no:cacheprovider --basetemp=./test_tmp_native_wheel_20261031
```

From `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_workstation_v05a4.py tests/test_workstation_v05a5.py tests/test_intake.py tests/test_intake_concurrency.py tests/test_production_concurrency.py -q -p no:cacheprovider
```

Native tests use synthetic intake fixtures and temporary files. Backend regression writes use the existing guarded test database/disposable schemas; no operational records were edited. Protected research artifacts remain untouched.
