# SELBY Workstation V0.5a validation — 2026-10-24

## Final results

| Check | Actual result |
|---|---|
| Final complete scanner/workstation regression | **460 passed**, no failures/errors/skips, **32.37 s** |
| Focused V0.5a tests | **14 passed**, **1.42 s**: 11 registry/model tests and 3 Qt tests |
| Ruff on six changed/new Python files | Passed |
| Native Windows Orders startup | Exit 0; `platform=win32`, `orders_loaded=true`, `image_loaded=false`, `automatic_acceptance=false` |
| Protected evidence check | **367 readable paths checked, zero changes** against the current-run baseline |

The full suite includes the 446 existing scanner/workstation regressions, including
V0.1–V0.4 session, centering, condition, grading, evidence, overrides, export, Qt,
and three Chrome reference-editor workflows. Backend/frontend commercial-service
tests were not run: those applications were not changed.

Final full command, from `scanner_agent`:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp local_data/selby_workstation/v05a-validation/regression-final2 --junitxml local_data/selby_workstation/v05a-validation/regression-final2.xml --tb=short
```

Final V0.5a focused command:

```powershell
.\.venv-analysis\Scripts\python.exe -B -m pytest tests/test_selby_orders.py tests/test_selby_orders_gui.py -q -p no:cacheprovider --basetemp local_data/selby_workstation/v05a-validation/focused-final --junitxml local_data/selby_workstation/v05a-validation/focused-final.xml --tb=short
```

Lint command:

```powershell
.\.venv-analysis\Scripts\python.exe -m ruff check selby_workstation/orders.py selby_workstation/orders_ui.py selby_workstation/app.py selby_workstation/__main__.py tests/test_selby_orders.py tests/test_selby_orders_gui.py
```

These output directories are retained. Use new basetemp/output names on a future
run: pytest may replace an existing basetemp directory.

## Coverage and observed behavior

- Customer order creation, contact/reference/notes, customer updates and full
  before/after audit payloads persist across new store instances.
- Multiple cards retain correct parent, permanent positions, optional metadata,
  UTC timestamps, null certification reference and derived order count.
- Sequential independent order/card IDs, cancellation retention, no committed-ID
  reuse, 16 concurrent card allocations with unique IDs/positions.
- Duplicate position rejection, unknown-order refusal, SQL identity/reassignment/
  position guards, delete prevention and audit delete prevention.
- Normal order/card lifecycle, skipped/backward transition rejection, terminal
  states, denied unauthorized/empty-reason corrections, successful authorized
  correction audit and preserved first-received timestamp.
- Exact internal card search, case-insensitive order/customer substring search,
  reopen/restart recovery and unknown-schema refusal.
- Atomic rollback of a failed three-card batch after the second card's audit
  write, failed order creation without orphan audit/entity rows, and a real child
  process terminating with `os._exit(23)` during uncommitted card creation.
  Reopening recovered no partial batch and `PRAGMA integrity_check` returned `ok`.
- Saved V0.4 legacy dossier association leaves original image, report and saved
  JSON bytes unchanged; reference survives reopen; duplicate session association
  across cards is rejected; inspection-only and conflicting internal identity
  dossiers are rejected; link replacement/unlink requires authorization; changed
  evidence is refused through existing loaders.
- Qt order creation, batch additions, searches, card details/audit, statuses,
  invalid-transition warning and reopen preserve the active inspection object and
  its complete data. Orders is available without loading a scan.
- Qt saved-session association/verification and authorized unlink update both
  card details and the session column immediately. This test caught a stale
  table refresh during development; the final revision fixes it.

All test customer names, card descriptions, grading labels and pairing statements
are engineering fixtures. They are not evidence of physical card identity,
grading accuracy, operator authentication or production readiness.

## Native launch and evidence

Native Windows smoke command used a separate validation registry:

```powershell
.\.venv-analysis\Scripts\python.exe -B selby_workstation.py --orders --orders-store local_data/selby_workstation/v05a-validation/native-orders.sqlite3 --smoke-test --screenshot local_data/selby_workstation/v05a-validation/orders-native.png
```

The captured Orders dialog was visually inspected: search fields, order table,
customer form, batch controls, card table, lifecycle/correction controls, session
association buttons and audit/detail pane are visible. The native smoke capture
preceded the final table-refresh correction; the final Qt tests exercise that
correction. No physical intake/scanner/printer workflow was exercised.

Retained local artifacts under `local_data/selby_workstation/v05a-validation/`:

- `regression-final2.xml`: authoritative final full results.
- `focused-final.xml`: final V0.5a results.
- `orders-native.png`, `native-orders.sqlite3`: separate native startup artifacts.
- `protected-before.json`, `protected-result.json`, `check_protected.py`: current
  hashes and verification of the 367 readable paths inherited from the V0.4
  manifest; no paths in that manifest were unavailable during this check.
- Test directories and earlier XML files, including failed development attempts.

The protected baseline was captured after initial implementation but before full
regression; it establishes stability across regression/validation, not a whole-
repository pre-implementation hash comparison. Implementation patches were
limited to the files listed below; no image/research/report patch was made.

Earlier runs are retained for transparency: the initial focused attempt had two
test-harness failures (subprocess import working directory and a nonexistent
snapshot method). Both were corrected. The first full sandbox run had 454 passes
and four failures: three existing Chrome DevTools connection/timeouts and a test
assertion expecting the wrong wrapped image exception. After correcting the
assertion and running with native browser access, all 458 then-current tests
passed in 31.93 s. Adding the table-refresh fix and two Qt cases produced the
final **460-pass** result above. Browser tests were not deselected or weakened.

## Files and scope

Created:

- `selby_workstation/orders.py`
- `selby_workstation/orders_ui.py`
- `selby_workstation/orders_authorization.json` (empty allowlist)
- `tests/test_selby_orders.py`
- `tests/test_selby_orders_gui.py`
- `SELBY_WORKSTATION_V05A.md`
- `SELBY_WORKSTATION_V05A_VALIDATION.md`

Modified existing user files with localized additions:

- `selby_workstation/app.py`: V0.5a window title, registry path and Orders action/dialog.
- `selby_workstation/__main__.py`: Orders launch/store flags and smoke metadata.

Existing session/grading/condition engines, policy, override authorization, saved
sessions, frozen research reports, image originals and upstream gates were not
modified. The pre-existing staged/untracked working tree was retained. No commit,
staging operation, database migration of existing grading records, or cleanup ran.

## Remaining limits

No unresolved functional failure was observed in the final suite. Write-failure
tests inject errors and abrupt process termination; they do not emulate actual
hardware power loss, filesystem corruption, a full physical disk or network-share
durability. Protect and back up the local SQLite store and local correction
allowlist. Operator text and append-only SQL triggers are not authenticated or
tamper-resistant controls. Restoring an obsolete database or using independent
registries requires ID reconciliation outside this slice.

Order/card statuses remain separate operator declarations without automatic grade
or release synchronization. Session pairing requires explicit human judgment;
links pin one saved version, and later versions require authorized replacement.
Customer audit snapshots require controlled storage/retention. UI/evidence loads
are synchronous, with no production-scale pagination/performance validation.
These are documented limitations, not claims of commercial readiness. See the
V0.5a guide for lifecycle policy, backup rules and the exact operator workflow.
