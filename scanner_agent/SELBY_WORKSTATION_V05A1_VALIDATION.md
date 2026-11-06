# SELBY Workstation V0.5a.1 validation — 2026-10-24

## Results

| Validation | Actual result |
|---|---|
| Final complete scanner/workstation regression | **470 passed**, no failures/errors/skips, **34.14 s** |
| Focused new/existing GUI suite | **24 passed**, **10.04 s** |
| New unified desktop cases within those runs | **10 cases** |
| Ruff on all seven changed/new Python files | Passed |
| Native default GUI startup | Exit **0**, `platform=win32`, `current_module=Dashboard`, no image/session required |
| Native synthetic order-to-grading workflow | `platform=windows`, one order/two cards, grading loaded, automatic acceptance false |
| Console-free Windows launcher | `Launch_SELBY.vbs` opened a visible **pythonw** SELBY V0.5a.1 window; the validation instance closed gracefully |
| Protected evidence | **367 paths checked, zero changes** against the baseline captured before application implementation |

The full suite includes all existing V0.1–V0.5a tests, scanner/storage, image and
report integrity, geometry/references, inspection/condition/grading, policy,
overrides, exports, SQLite identity transactions/recovery, Qt and Chrome reference
editor tests. Existing tests were preserved. Backend/frontend service suites were
not run because those applications were not modified.

Final full command, from `scanner_agent` with native browser access:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp local_data/selby_workstation/v05a1-validation/regression-final2 --junitxml local_data/selby_workstation/v05a1-validation/regression-final2.xml --tb=short
```

Final focused GUI command:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests/test_selby_desktop.py tests/test_selby_gui.py tests/test_selby_condition_gui.py tests/test_selby_grading_gui.py tests/test_selby_orders_gui.py -q -p no:cacheprovider --basetemp local_data/selby_workstation/v05a1-validation/gui-final --junitxml local_data/selby_workstation/v05a1-validation/gui-final.xml --tb=short
```

Lint:

```powershell
.\.venv-analysis\Scripts\python.exe -m ruff check selby_workstation/desktop.py selby_workstation/orders_ui.py selby_workstation/app.py selby_workstation/grading_ui.py selby_workstation/__main__.py selby_desktop.pyw tests/test_selby_desktop.py
```

Use fresh output names for future runs; pytest can replace an existing basetemp.

## Verified workflows

`tests/test_selby_desktop.py` uses real Qt button clicks/keyboard events and the
existing service/models. It covers:

1. Subprocess startup of the normal entry point with diagnostic smoke/store flags
   only: Dashboard is the initial module and no session or Orders view is created.
2. Navigation through all five modules, order creation, two-card addition, exact
   card lookup by Enter, visible selected context and disabled future features.
3. Orders form preservation across navigation and Ctrl+L focus/select-all behavior.
4. Explicit confirmed GUI association, legacy dossier label preservation, linked
   grading open, return to the same order/card, unsaved session preservation and
   same-version workflow resume without replacing the active object.
5. Restart via fresh window/store instances: existing cards and pinned saved
   dossier reopen correctly. The pre-existing registry suite also exercises
   process interruption/recovery and persistent allocation.
6. Missing linked saved session and missing original image: actionable warning,
   unchanged active unrelated session, retained association, and Orders stays open.
7. Cancelled cancellation/association confirmations: no status or link mutation.
8. GUI registry selection preference survives reconstruction; switching clears
   selection but preserves the active inspection. Unrelated SQLite selection is
   rejected read-only with its original bytes unchanged.
9. Cancelled dirty-session discard confirmation: the original session and its
   unsaved work remain active.
10. Returning to a retained Grading view after inspection changes refreshes the
    displayed result from Ready for operator review to Incomplete and updates the
    operator label, while preserving unsubmitted grading explanation text.

Existing GUI tests independently preserve geometry gestures, inspection
Undo/Redo/recovery, condition workflows, complete V0.4 grading operations and
exports, V0.5a intake/audit, and evidence integrity checks.

The initial existing-GUI run had one compatibility failure: explicit closing and
reopening Orders retained a filter instead of clearing it as the previous dialog
did. That behavior was corrected without clearing forms on ordinary navigation.
Subsequent full runs passed **468 tests in 34.36 s** and **469 tests in 51.91 s**.
The later run added the read-only registry guard; final validation additionally
includes the retained-Grading refresh regression. Earlier artifacts were retained,
and no existing test was weakened or deselected.

## Native Windows checks and screenshots

Default unified startup command:

```powershell
.\.venv-analysis\Scripts\python.exe -B selby_workstation.py --smoke-test --orders-store local_data/selby_workstation/v05a1-validation/native-registry.sqlite3 --screenshot local_data/selby_workstation/v05a1-validation/dashboard-native.png
```

It returned exit 0 with Dashboard active, no loaded image/report/session, and
`automatic_acceptance=false`. These flags select test output and automatic exit;
they do not select a business module. A separate actual no-argument launch of
`Launch_SELBY.vbs` verified a visible window titled `SELBY · Workstation V0.5a.1`
belonging to `pythonw`, then closed only that newly launched instance. The launcher
check captured visibility and successful graceful closure, not a process exit code.

The retained native harness `native_workflow.py` created a separate synthetic order,
two cards and saved legacy-label dossier using the existing services, associated
them explicitly, opened Grading from the card, and navigated to Settings. It exited
0. All inputs and IDs in these screenshots are engineering fixtures, not business
records, physical pairing evidence, or a real grading assessment.

Screenshots, visually inspected:

- [Default Dashboard](local_data/selby_workstation/v05a1-validation/dashboard-native.png)
- [Orders with selected card and workflow buttons](local_data/selby_workstation/v05a1-validation/orders-native.png)
- [Embedded Grading with selected/active context](local_data/selby_workstation/v05a1-validation/grading-native.png)
- [Settings and read-only authorization configuration](local_data/selby_workstation/v05a1-validation/settings-native.png)

The screenshots show persistent navigation, separate selected/active context,
existing Qt styling and scrollbars for dense content. Native captures preceded
the final displayed-Grading refresh correction; the final Qt regression exercises
that correction. No hardware scanner, printer, barcode device or physical-card
operation was tested.

Local evidence under `local_data/selby_workstation/v05a1-validation/` includes final
and earlier XML files, screenshots, `launcher-result.json`, synthetic registry and
saved sessions, and `protected-before.json` / `protected-result.json` plus the
integrity checker. The protected baseline uses all 367 readable paths inherited
from V0.5a and was captured before application patches. No protected path changed.
Validation artifacts are ignored local files; none replaced original evidence.

## Files changed

Created:

- `selby_workstation/desktop.py`: main navigation, embedding, context, card reopening,
  read-only configuration view and registry preference.
- `selby_desktop.pyw`: console-free entry point and visible startup failures.
- `Launch_SELBY.vbs`: root-relative Windows launcher.
- `tests/test_selby_desktop.py`: unified workflow coverage.
- `SELBY_WORKSTATION_V05A1.md` and this validation report.

Modified:

- `selby_workstation/app.py`: install shell, navigate/reuse workbenches, reset view
  bindings on session replacement/recovery, and actionable errors.
- `selby_workstation/orders_ui.py`: explicit linked workflow actions, context/empty
  states, keyboard-safe lookup buttons and sensitive-action confirmation.
- `selby_workstation/grading_ui.py`: return to Inspection before Condition; refresh
  the operator label when the retained workbench refreshes.
- `selby_workstation/__main__.py`: V0.5a.1 description and unified smoke metadata/screenshots.

No grading/condition/session engine, policy, orders service/schema, immutable ID,
allowlist, frozen research artifact, original scan, source report or unrelated
application was changed. No history rewrite, staging, commit or cleanup occurred.

## Remaining limits

Routine intake, inspection, grading, session association/reopening, navigation and
registry selection are GUI-accessible without business CLI flags. GUI exceptions
are environment setup, backups, deployment permissions, administrative policy/
allowlist editing and restoration of missing evidence at recorded paths. Settings
exposes configuration read-only. Permanent card links still require saved grading
dossiers; inspection-only sessions can be opened but not linked through this adapter.

Condition remains an auxiliary modal inspector. There is one active inspection;
save before replacing it. Unsubmitted forms survive navigation but not application
shutdown. Dense panels scroll, evidence loading is synchronous, and no production-
scale responsiveness or accessibility certification is claimed. Keyboard focus is
prepared for future input devices without barcode parsing. Labels/scanner remain
disabled. Local authorization and evidence guarantees retain all prior limitations.

No production readiness, physical traceability accuracy, actual power-loss
durability or commercial grading performance is claimed from these software tests.
