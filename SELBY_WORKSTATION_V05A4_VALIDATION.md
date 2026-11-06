# SELBY Workstation V0.5a.4 validation

## Fresh validation — 2026-10-31

The existing implementation was re-audited and hardened in this session. Results below are new executions; the 2026-10-25 results later in this document are historical.

- Focused Workstation intake tests: **9 passed**, 4.63 seconds, including the new Escape-during-request regression.
- Backend native-client/intake/concurrency tests: **29 passed**, 13 dependency/configuration warnings, 52.68 seconds.
- Full current backend suite: **416 passed**, 24 existing dependency/configuration warnings, 127.15 seconds. Command from `backend`: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
- Full Workstation/auth/connection/intake regression selection (same command as below): **169 passed, 1 skipped**, 63.45 seconds. The skipped test remains the opt-in Credential Manager roundtrip.
- Ruff check of all three intake modules and both intake test files passed; formatting check of the three changed Python files passed. `git diff --check` passed with existing line-ending warnings. Since these implementation files were already untracked, Ruff also checked the new edits directly.
- **Native Windows Qt test: 1 passed**, 3 dependency/configuration warnings, 14.46 seconds. The subprocess asserted `QApplication.platformName() == 'windows'`, showed the actual dialog, authenticated, registered a parcel, recorded admin custody authorization, began reconciliation, registered two physical copies separately, matched each by entry UUID, completed reconciliation, closed and reopened the reconciled order, and verified mutation controls remained disabled. The parent verified both PostgreSQL physical records retained their declaration links. The test supplies synthetic credentials and programmatically confirms dialogs; this is automated native GUI validation, not manual operator acceptance or scanner/printer validation.

Native command (from `backend`, with desktop GUI execution permission):

```powershell
$env:SELBY_INTAKE_QT_PLATFORM='windows'
.venv/Scripts/python.exe -m pytest tests/test_workstation_v05a4.py::test_qt_dialog_real_backend_workflow -q -s -p no:cacheprovider --basetemp=./test_tmp_native_intake_20261031
```

The first native attempt failed before running the GUI because the default pytest temporary directory was owned by the sandbox user. The successful retry used its own temporary directory. Repeated runs should choose a fresh `--basetemp` if directory ownership differs. The backend fixture validates a PostgreSQL `_test` database distinct from the development database, applies test migrations, and rolls back synthetic customer/order/custody records. Its loopback HTTP relay invokes the real FastAPI application. This does not validate the separately running development Uvicorn process or mutate pre-existing customer submissions. No production deployment or production data changes were performed.

Coverage remains: single-copy orders, several identical copies, multiple declared entries with equal names and different printings, multiple parcels, partial reception, missing/wrong/unexpected exceptions, blocked completion, exact-key replay after committed-write/lost-read and reconstructed journal, authorization/session failures, reconciled reopening, and unchanged local registry/grading links. The current implementation report records the audit findings and precise production-mapping blocker. **SP/PC → ORD/SLB-C linkage is still incomplete; no production end-to-end success is claimed.** The old native-renderer limitation below is superseded only by the automated Windows test described here; manual physical handling acceptance remains outstanding.

Date: 2026-10-25. Windows development environment. No deployment, production migrations, account changes or reception writes to existing customer submissions were performed. Existing staged/unstaged work and protected research files were preserved.

## Executed checks

- Final full backend suite from `backend`: `.venv/Scripts/python.exe -m pytest -q` — **393 passed**, 22 existing dependency/config deprecation warnings, 94.14 seconds. This includes the additional unexpected-card and distinct-printing cases and the actual Qt/FastAPI integration test.
- Complete Workstation regressions plus connection/auth/intake tests: **168 passed, 1 skipped**, 58.14 seconds. The skipped test is the opt-in native Credential Manager roundtrip; no Credential Manager implementation changed in this release.
- Focused intake GUI/journal suite after tightening creation recovery: **8 passed**, 4.81 seconds.
- Expanded focused backend/native-client/Qt integration suite: **9 passed**, 2 dependency/config warnings, 27.09 seconds; all nine also passed in the final full backend run.
- Ruff check on all new intake modules and new desktop/backend tests: **all checks passed**. Ruff formatting applied only to those new files.
- Changed intake modules passed `compileall`. `git diff --check` passed with existing line-ending conversion notices only.

Workstation full-suite command from `scanner_agent`:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$workstationTests=Get-ChildItem tests/test_selby*.py | ForEach-Object { $_.FullName }
.venv-analysis/Scripts/python.exe -m pytest @workstationTests tests/test_connection_settings.py tests/test_desktop_auth.py tests/test_desktop_auth_gui.py tests/test_physical_intake.py -q -p no:cacheprovider
```

Focused suites:

```powershell
# backend directory; requires the existing guarded TEST_DATABASE_URL (_test DB)
.venv/Scripts/python.exe -m pytest tests/test_workstation_v05a4.py -q
# scanner_agent directory
$env:QT_QPA_PLATFORM='offscreen'
.venv-analysis/Scripts/python.exe -m pytest tests/test_physical_intake.py -q -p no:cacheprovider
.venv-analysis/Scripts/python.exe -m ruff check selby_workstation/intake_client.py selby_workstation/intake_journal.py selby_workstation/intake_ui.py tests/test_physical_intake.py ../backend/tests/test_workstation_v05a4.py
```

## Evidence and coverage

The backend integration fixture relays real native HTTP requests into FastAPI against isolated PostgreSQL fixtures, clearing the relay's own cookie jar between requests. It tests desktop login, CSRF and every new client's custody route against existing server authorization and business validation. It does not replace business rules with a desktop mock.

New tests cover single-copy, multiple identical copies, multiple parcels, same-name distinct declared entries, partial arrival with zero received cards, explicit matches, missing quantities, wrong/unexpected cards, open-discrepancy completion rejection, explicit acknowledged exceptions, terminal reconciled state, operator/admin distinction, expired/removed staff access and immutable declaration values. After successful reconciliation, inspection lookup still returns payment_unverified. Existing intake/concurrency/inspection tests cover submission locking, exact-key duplicate replay/conflict, cross-submission isolation, quantity limits and custody/commercial restrictions.

The lost-response test commits a parcel/card POST, deliberately fails the subsequent detail GET, reconstructs the journal as after restart, and retries with the same request key. It asserts one physical identity and one creation audit event, rather than merely checking a client mock call count.

The Qt/API integration test starts the actual PySide6 dialog in a subprocess using the existing Workstation virtual environment, authenticates against the real FastAPI relay, performs parcel arrival, admin custody authorization, begin, two separate copy registrations and explicit matches, and completion. It asserts two actual PostgreSQL physical records with declaration links, no backend grading-card links, and payment still unimplemented. Its credentials, observations and customer records are synthetic test fixtures only; no real operator secrets were needed.

Desktop widget tests separately check explicit confirmations and reasons, ID-specific payloads, no automatic association on creation, discrepancy selection, background-thread execution, scope isolation, blocked overlapping intents, preservation/replay after restart, non-idempotent manual recovery, disabled write controls for reconciled/nonstaff/expired states, and inability to discard an unknown creation into a new identity. A pre-existing temporary local registry with ORD/SLB-C and session-link metadata is hashed before/after intake actions; its bytes and links remain unchanged.

The tests run on Windows Python with Qt's offscreen platform. A fresh native Windows-renderer/printer/scanner/live-customer intake acceptance session was not run in this release. The user previously validated V0.5a.3 live portal/backend authentication; that does not establish live V0.5a.4 physical handling acceptance. No claim of production end-to-end readiness is made.

## Files changed in this release

- New `scanner_agent/selby_workstation/intake_client.py`, `intake_journal.py`, `intake_ui.py`.
- `desktop_auth.py`: authenticated custody-client access; existing credential storage preserved.
- `incoming_ui.py`: explicitly separate physical-intake action and refresh on close; preview transport stays GET-only.
- `desktop.py`, `app.py`, `__main__.py`: V0.5a.4 version display.
- New `scanner_agent/tests/test_physical_intake.py`, `backend/tests/test_workstation_v05a4.py`.
- These two V05A4 documents.

No backend endpoint/source, PostgreSQL schema/migration, existing order SQLite schema, pricing, payment, inspection policy or research artifact was changed. A separate technical SQLite journal initializes its single pending-request table locally when opening intake; this is documented explicitly and is not an order/card import.

## Native operator acceptance still required

1. Relaunch `scanner_agent/Launch_SELBY.vbs` with the existing local connection and verified staff account. Select a dedicated test confirmed submission, open Physical intake and verify declarations and expected counts.
2. Confirm only a genuinely arrived test parcel. Verify PI reference, timestamp/actor and audit. Observe that received-card count remains zero. Admin grants the documented custody override; operator begins reconciliation.
3. Register and individually identify multiple test physical copies across supported parcels. Confirm PC references stay stable across refresh/relaunch, equal-name printings are selected by the intended declaration, and no local ORD/SLB-C is created.
4. Try missing, wrong, unexpected and duplicate-attempt scenarios using test objects. Confirm open issues block completion; documented acknowledgement is visibly distinct from receipt. Verify payment/inspection remain blocked independently.
5. Interrupt connectivity during a test creation, reopen and replay the preserved key. Confirm only one backend PC/PI exists. Never clear an unknown creation by deleting the journal. For an uncertain non-creation, refresh inventory/audit before explicitly clearing its local intent.
6. Verify expiration, permission denial, hold/resume, already-reconciled details and existing local order/session links. Label printing, QR input and production mapping remain deferred and must not be inferred from this release.
