# SELBY Workstation V0.5a.5 validation

Date: 2026-10-31. Validation used synthetic local FastAPI/PostgreSQL fixtures and temporary SQLite registries. No production deployment/data edits, printing, protected research edits or grading-evidence edits were performed.

## Results

- New SQLite/Qt bridge tests: **15 passed**, 1.33 seconds.
- Focused PostgreSQL/native-client bridge and independent-connection concurrency tests: **19 passed**, 4 dependency/configuration warnings, 40.89 seconds.
- Final full backend suite: **435 passed**, 25 existing dependency/configuration warnings, 177.91 seconds. This includes all new bridge tests and existing authentication, intake, inspection, migration and customer-operation regressions.
- Full Workstation/auth/intake/bridge regression selection: **184 passed, 1 skipped**, 48.96 seconds. The skip is the pre-existing opt-in native Credential Manager roundtrip; its implementation is unchanged.
- Final native Windows GUI integration: **1 passed**, 3 dependency/configuration warnings, 15.20 seconds. This run includes the final registry recovery backup, backend/local conflict comparison and Orders display. An earlier native run also passed before the final hardening.
- Ruff check on the new bridge sources/tests/migration and modified custody transport passed. Ruff formatting check on all nine new Python files passed. Existing unrelated files retain their formatting.
- `git diff --check` passed with existing line-ending conversion warnings only. New Python files were checked directly by Ruff because they remain untracked in the pre-existing working tree.

## Exact commands

From `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests/test_workstation_v05a5.py tests/test_production_concurrency.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider
```

From `scanner_agent`:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$workstationTests=Get-ChildItem tests/test_selby*.py | ForEach-Object { $_.FullName }
.venv-analysis/Scripts/python.exe -m pytest @workstationTests tests/test_connection_settings.py tests/test_desktop_auth.py tests/test_desktop_auth_gui.py tests/test_physical_intake.py tests/test_production_bridge.py tests/test_production_bridge_gui.py -q -p no:cacheprovider
```

Native Windows run, from `backend` with GUI execution permission:

```powershell
$env:SELBY_BRIDGE_QT_PLATFORM='windows'
.venv/Scripts/python.exe -m pytest tests/test_workstation_v05a5.py::test_native_qt_bridge_and_local_orders -q -s -p no:cacheprovider --basetemp=./test_tmp_native_bridge_20261031
```

## Evidence and coverage

The guarded `TEST_DATABASE_URL` must use PostgreSQL/psycopg, a database name ending `_test`, and a different name from the configured development database. Tests run real application routes with isolated outer transactions; the concurrency test creates/migrates/drops a uniquely named disposable schema using independent connections and actors. Existing SP/PC/customer records are not selected for receipt/import. Local registries/backups/preferences are under test temporary directories.

| Case | Executed evidence |
| --- | --- |
| One-card order | Full intake/reconciliation → production bridge; exact one PC/SLB-C pair |
| Multi-card / identical copies | Quantities `(3,)` and `(2,1)` include identical copies and equal-name different-printing entries; UUID-specific mapping, one local identity per object |
| Repeated import / existing mapping / restart | New service/store instances retain registry UUID and exact IDs; one backend reservation event, one backend confirmation event, no duplicate local identity events |
| Interrupted transaction | Injected exception during local audit insertion rolls back order/card sequences and all mapping rows |
| Interrupted protocol | Failure after reservation commit, before local commit, before confirmation, after confirmation commit, and before local finalization; reconstructed service resumes exact IDs |
| Recovery backup | Pending registry UUID/PC pair set is readable from the recovery snapshot after interrupted confirmation |
| Local concurrency | Four independent stores/threads allocate one order and one physical-card mapping set |
| Backend concurrency | Two distinct actors/DB connections race different registry UUIDs: one 200, one 409. Exact reserve/confirm races replay once; audit count remains one per action |
| Existing unverified records | Same external reference does not imply identity; preparation stops before reservation until explicit adoption/distinct choice |
| Adoption / grading links | Exact PC/SLB-C adoption preserves the complete existing card/session-link record; no extra order/card; nonadmin adoption rejected by backend and desktop |
| Conflicts / parentage / database constraints | Wrong parent, duplicate local identity, immutable registry/mapping deletion/update, foreign registry, changed backend IDs and missing-local-confirmed-state cases reject without replacement allocation |
| Reconciled exceptions | Acknowledged missing copies produce no phantom local cards; acknowledged unresolved/unexpected concerns block preparation |
| Existing backend grading link | Non-null backend grading UUID blocks import; FK/link remains unchanged |
| Unreconciled / draft | Desktop eligibility rejection and direct draft reservation request rejected; no production identities/reservation |
| Authorization | Missing Origin, session, CSRF, removed staff role, nonadmin adoption and wrong registry all fail closed |
| Audit/migration | Immutable bridge update/delete tested; fresh-schema migration rejects TRUNCATE and PC mapping changes; v1 SQLite backup remains readable and preserves legacy IDs/links |
| Qt behavior | Explicit confirmation and reason, duplicate adoption JSON rejection, off-main-thread work, pending/conflict states disable reopening, permission failure clears detail, Escape cannot close an outstanding worker |

The native integration subprocess asserts `QApplication.platformName() == 'windows'`, uses an in-memory synthetic credential vault, opens the actual Workstation and production dialog, prepares three PCs, retries, opens their actual local Orders records, verifies PC references and confirmed mapping state, closes/reopens the bridge, and confirms independent inspection eligibility stays blocked. Test settings select the temporary registry before Workstation initialization and disable ambient connection restore. Every new bridge network request is handled by the real FastAPI application via a loopback HTTP relay and PostgreSQL, not a desktop business-rule mock. Confirmation dialogs are programmatically accepted; this is automated native GUI validation, not manual physical-object handling acceptance.

During test development, one intermediate backend run failed three added test cases due to a missing `PhysicalCard` test import. The import was corrected and all 19 focused backend cases passed on rerun. No product failure was hidden by skipping those cases. The retained skip is solely the unrelated opt-in Credential Manager roundtrip.

## Limits and release boundary

The separately running development Uvicorn process and existing customer data were not used for writes; this is actual local application/PostgreSQL integration with synthetic fixtures. No production migration was applied. Before authorized deployment, take a PostgreSQL backup and apply Alembic 0011; the Workstation v2 migration creates a local pre-migration backup and production recovery snapshots automatically on explicit bridge use. Use one writable registry copy and a stable backend origin. Recovery/reassignment after loss of all registry backups requires a separate reviewed maintenance procedure; the software deliberately refuses replacement IDs.

Printing, scanner workflows, payment-provider implementation and grading authorization are outside V0.5a.5. Manual physical-card/operator acceptance and production rollout remain outstanding. See the [implementation report](SELBY_WORKSTATION_V05A5.md) for schema, exact authorization/eligibility, recovery rules, files changed and adoption procedure.
