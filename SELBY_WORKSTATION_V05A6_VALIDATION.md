# SELBY Workstation V0.5a.6 validation

Date: 2026-10-31. All custody/production writes used synthetic PostgreSQL fixtures and temporary local journals/registries. The existing dedicated development order and production data were **not** changed. Manual acceptance is pending; the exact operator procedure is in [the implementation report](SELBY_WORKSTATION_V05A6.md#exact-manual-acceptance--existing-dedicated-development-test-order).

## Executed results

| Run | Result |
| --- | --- |
| Full backend regression suite | **453 passed**, 27 existing dependency/configuration warnings, 164.65 seconds |
| Final full Workstation/auth/intake/bridge/wheel/void regression selection | **198 passed, 1 skipped**, 49.60 seconds |
| New focused backend void workflow tests | **16 passed**, 3 dependency/configuration warnings, 33.06 seconds |
| New independent-actor void/void and void/match races | **2 passed**, 5 dependency/configuration warnings, 1.35 seconds |
| Final focused void Qt UI tests, including preserved retry confirmation | **4 passed**, 2.68 seconds |
| Native Windows Qt → FastAPI/PostgreSQL void/reconcile/production workflow | **1 passed**, 3 dependency/configuration warnings, 7.05 seconds |
| Ruff on new void modules/migration/tests and modified custody UI/client/journal | Passed; formatting check passed on eight files |
| `git diff --check` | Passed; existing line-ending notices only |

The sole skipped Workstation test is the pre-existing opt-in native Credential Manager roundtrip. No void or bridge case was skipped. The final full Workstation run includes the last retry confirmation change; the focused test explicitly asserts that retries display the original full PC reference and original reason after refreshing authoritative state.

## Coverage and evidence

The actual client/HTTP integration fixtures create a confirmed order with declared quantity two, two separately registered/matched PCs and a third unidentified PC from a synthetic extra click. Voiding the third yields active Declared 2 / Received 2 / Matched 2 / Unidentified 0. All three PC records remain; the original accidental PC's complete raw database row is compared before/after and remains unchanged. Both legitimate associations remain intact. Reconciliation completes without an unexpected discrepancy; subsequent production mapping contains exactly the two legitimate PC UUIDs and keeps the voided card solely in `voided_cards` history.

Tests verify repeat void with both the same and a different reason, plus a safe replay after reconciliation, produces one immutable void fact and one audit event. UPDATE, DELETE and TRUNCATE of void history fail. Replaying the original registration key still points to its original historical identity and does not resurrect it or allocate an active replacement.

Unsafe-case tests cover current matched, previously matched/unmatched history, questionable status, open and closed discrepancy history, inspection dossier, backend grading UUID, pending production reservation, existing PC production mapping, reconciled and held orders. Each rejection leaves the original PC/links unchanged. Blank reasons, cross-submission targets and revoked staff fail. Existing auth/CSRF regressions remain in the full suite. The valid correction test uses the backend operator role, demonstrating that an administrator override is not needed to perform an otherwise eligible correction.

Voided PCs reject matching, new discrepancies and active label requests. Inspection lookup retains historical access but reports `card_voided` and ineligibility for every action. Production transfer is tested after correction, including preservation of bridge constraints. A lost post-commit detail response leaves a durable journal intent; reconstructing the journal as after restart and replaying the exact void completes without another event.

Concurrency tests migrate a fresh uniquely named PostgreSQL schema and use two actors and independent sessions/connections. Two simultaneous voids produce one event. Void versus match produces one success and one conflict; the resulting PC is either actively matched or voided, never both. Existing production/intake concurrency regressions also pass.

Qt widget tests verify required reason, cancel/no-write behavior, full reference/reason confirmation, backend-driven eligibility, hidden controls for ineligible/terminal PCs, historical VOIDED rows/reasons, exclusion from active counters/selectors and selection clearing. Retry tests require a fresh read and retain the original target/reason even if form text changes.

The native subprocess asserts `QApplication.platformName() == 'windows'`, opens the real intake dialog, selects the synthetic third PC, verifies its full reference appears in confirmation, voids it, checks all four active counters and historical row, completes reconciliation, closes/reopens the order, then prepares production and verifies exactly two PC mappings. The parent independently verifies the two PostgreSQL production-card identities. Dialog confirmations are programmatically accepted; this is actual automated native GUI/application integration, not manual physical-card acceptance. The backend is invoked through the existing loopback HTTP relay into the real FastAPI application against isolated local PostgreSQL fixtures, not a mocked business-rule implementation.

## Commands

From `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_workstation_v05a6.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests/test_void_concurrency.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

Native Windows run from `backend`, with GUI execution permission:

```powershell
$env:SELBY_VOID_QT_PLATFORM='windows'
.venv/Scripts/python.exe -m pytest tests/test_workstation_v05a6.py::test_native_qt_void_then_reconcile_and_prepare -q -s -p no:cacheprovider --basetemp=./test_tmp_native_void_20261031
```

From `scanner_agent`:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$workstationTests=Get-ChildItem tests/test_selby*.py | ForEach-Object { $_.FullName }
.venv-analysis/Scripts/python.exe -m pytest @workstationTests tests/test_connection_settings.py tests/test_desktop_auth.py tests/test_desktop_auth_gui.py tests/test_physical_intake.py tests/test_production_bridge.py tests/test_production_bridge_gui.py tests/test_form_wheel.py tests/test_intake_void_gui.py -q -p no:cacheprovider
```

The existing test fixture requires `TEST_DATABASE_URL` to identify a PostgreSQL/psycopg `_test` database whose name differs from development. It applies migrations only there or in disposable schemas; synthetic operational rows are rolled back. No existing development-order lookup/write, production migration, scanner/printing operation or grading-evidence modification was performed. The native test uses an in-memory synthetic credential vault and temporary journal/registry paths.

## Remaining acceptance and deployment boundary

Migration **0012** is prepared and validated, not applied to the existing development/production order database. Before using the new action there, complete an authorized backup/migration/restart. Then follow the implementation report's exact operator steps to void **only** the confirmed accidental PC. No script automatically selects or modifies that order.

There is no unvoid, deletion, terminal correction, discrepancy-history erasure, production unlinking or reservation release. Existing PDFs/physical labels cannot be recalled; the existing backend has no historical issuance ledger. Current label requests and downstream active workflows reject voided identities. Manual verification that no physical object exists remains an operator responsibility. These restrictions are deliberate and are not bypassed by administrator role or local registry edits.
