# SELBY Workstation V0.5a.3 validation

Validation date: 2026-10-25. Local Windows development environment only. No production data was modified, no deployment was performed, and no production migration was applied. There are no migrations for this change.

## Local setup and connection fix follow-up

**Root cause:** no `desktop.ini` existed at the established settings path, and no `SELBY_ENVIRONMENT` selected an explicit environment. The previous intentional fail-closed behavior disabled login, but Settings only described manual file editing. The VBS working directory was not the cause: it selects the script directory and settings paths are based on the module location.

**Fix:** Settings now offers environment, backend origin and portal-auth origin fields, explicit local-development defaults, an asynchronous credential-free health test and Save. Saving validates HTTPS/loopback rules, preserves unrelated preferences, and enables the existing login controls immediately. The Incoming screen links to Settings. Environment overrides are identified and cannot be silently overwritten. Changing origins requires prior session revocation; an offline pending revocation leaves the saved origin unchanged. No authentication architecture or Windows Credential Manager adapter was replaced.

Diagnostics now distinguish unconfigured/configured, unreachable/reachable, authentication required/authenticated, session expired and permission denied. Successful refresh clears a stale unreachable diagnostic. Missing/invalid configuration does not affect local Orders, Inspection or Grading.

**Local state verified:** FastAPI `/api/health` returned 200 at `http://127.0.0.1:8000`; the customer portal returned 200 at `http://127.0.0.1:3000`; the backend uses development authentication and the matching `AUTH_ORIGIN`. A read-only development database check found existing staff, so no account or role was created, reset or changed. The intended localhost settings were saved through the native Windows Settings form, not by installing credentials or replacing a configuration file. Closing/reopening the actual GUI loaded them, enabled email/password/sign-in and reported backend reachable/authentication required. Screenshots were inspected at `scanner_agent/local_data/v05a3-connection-validation/incoming-configured.png` and `incoming-reloaded.png`.

**Tests executed for the fix:**

- Full backend regression: **384 passed**, 22 existing deprecation warnings, 71.39 seconds. This includes native-client authentication against real FastAPI/PostgreSQL isolated test fixtures, role checks, expiry, logout/revocation and read-only submission contracts.
- Workstation regressions plus connection/auth tests: **159 passed, 1 skipped**, 51.74 seconds. The skip is the explicitly opted-in native Credential Manager test, which was not rerun for this fix; its earlier successful native roundtrip is recorded below. No secure-store code changed here.
- New setup tests separately: **6 passed**, 3.78 seconds. They cover explicit defaults versus Save, persistence/reload, enabled login, unrelated preference preservation, insecure remote HTTP rejection, background health checks, environment overrides and origin-switch revocation.
- After diagnostic refinements, connection settings, auth GUI and Incoming regressions: **31 passed**, 27.68 seconds.
- Final complete Workstation run, including the added diagnostic assertions: **160 passed, 1 skipped**, 47.97 seconds. Command from `scanner_agent`: set `QT_QPA_PLATFORM=offscreen`, collect all `tests/test_selby*.py` files and pass them with `tests/test_connection_settings.py tests/test_desktop_auth.py tests/test_desktop_auth_gui.py` to `.venv-analysis/Scripts/python.exe -m pytest -q -p no:cacheprovider`.
- Final read-only live prerequisites: **one active verified staff account**, **three confirmed submissions**, and both localhost HTTP services reachable. This establishes available prerequisites, not authenticated GUI acceptance. No customer names, addresses, emails or submission contents were output.
- Changed desktop modules passed `compileall`; `git diff --check` passed with line-ending notices only.
- Native Windows setup/relaunch script passed with the actual local settings and running backend; no password was supplied and no customer data was opened.

**Live steps outstanding:** automatic validation of the VBS launch was attempted but interrupted while the validation harness waited on the launched process tree; a complete VBS-to-login workflow is not claimed. The launcher source and interpreter/working-directory selection were inspected; native direct GUI startup/relaunch passed separately. Authentication into the running development service and searching/opening a portal-created submission require interactive credentials for the existing approved staff account. Those credentials were not available to the agent and were not requested in chat, guessed, extracted or reset. Test-fixture login success is not substituted for this live acceptance step. Use the exact Settings/startup/account instructions in the implementation document to finish acceptance.

**Files changed for this follow-up:** `scanner_agent/selby_workstation/connection.py`, new `connection_settings.py`, `desktop.py`, `incoming.py`, `incoming_ui.py`; new `scanner_agent/tests/test_connection_settings.py`, adjusted `test_selby_incoming.py` and `test_desktop_auth_gui.py`; these two V05A3 documents. Local-only `scanner_agent/local_data/selby_workstation/desktop.ini` now holds only the three nonsecret connection preferences. No backend source, database schema, confirmed declarations, local identity generation or grading/research artifacts were modified.

## Executed tests

- Backend: from `backend`, `.venv/Scripts/python.exe -m pytest -q`: **384 passed**, 22 existing dependency/configuration deprecation warnings, 67.91 seconds.
- Focused desktop/auth/UI: from `scanner_agent`, set `QT_QPA_PLATFORM=offscreen`, then `.venv-analysis/Scripts/python.exe -m pytest tests/test_desktop_auth.py tests/test_desktop_auth_gui.py tests/test_selby_incoming.py tests/test_selby_desktop.py -q`: **44 passed, 1 skipped**, 32.23 seconds. The skipped test requires explicit native Credential Manager opt-in.
- Real Windows Credential Manager: set `SELBY_TEST_CREDENTIAL_MANAGER=1`, then `.venv-analysis/Scripts/python.exe -m pytest tests/test_desktop_auth.py::test_native_windows_credential_manager_roundtrip -q`: **1 passed**. A random `SELBY/TestOnly/…` target held only a synthetic value; replacement/read/deletion were verified with cleanup. One pytest cache permission warning occurred; credential operations passed.

- All existing Workstation tests: with `QT_QPA_PLATFORM=offscreen`, pass every `tests/test_selby*.py` file to `.venv-analysis/Scripts/python.exe -m pytest -q -p no:cacheprovider`: **137 passed**, 27.92 seconds.
- After secure-store error-handling hardening, auth/service GUI tests rerun: **16 passed, 1 skipped**, 15.95 seconds.
- Final Incoming client/UI regression after removing the remaining internal cookie-copy error wording: **18 passed**, 12.40 seconds.
- Application startup smoke: `.venv-analysis/Scripts/python.exe -B selby_workstation.py --smoke-test --screenshot local_data/v05a3-validation/startup.png` exited successfully on Windows and reported Dashboard loaded, no image, no automatic acceptance. Offscreen rendering produced missing-font boxes, so that screenshot is not visual acceptance evidence.
- Native Windows renderer: set `QT_QPA_PLATFORM=windows` and rerun `tests/test_desktop_auth_gui.py`: **6 passed**, 11.43 seconds. Native startup smoke also exited successfully and saved `scanner_agent/local_data/v05a3-validation/startup-windows.png` for visual inspection. This uses the real Windows Qt renderer with synthetic fixture data for the GUI tests; live deployment acceptance remains outstanding.
- `git diff --check` passed; only line-ending conversion notices were emitted. No frontend code changed, so frontend build/lint were not run for this desktop/backend mission.

## What these tests establish

The new backend integration tests run the actual native authentication client through a loopback HTTP relay into FastAPI with isolated PostgreSQL test data. The relay deliberately clears the TestClient cookie jar between requests, so authentication depends on the native client's own server-issued cookie. Tests exercise real password verification, staff checks, saved-session restore, CSRF logout and database revocation, invalid password, expiry and removed membership. Submission snapshots and business-model counts are compared before/after to detect unintended business writes. Authentication session writes are expected.

Backend tests cover customer/reference filtering, literal wildcard search, deterministic pagination, query/limit/offset validation, unauthorized access and Incoming access-log query redaction. Existing intake/photo and historical-submission tests remain included in the full suite.

Qt tests instantiate and interact with actual PySide6 widgets against a controlled HTTP fixture. They cover sign-in, automatically loaded orders, columns, search/page reset, detail/photo handling, role denial, expiry, saved-session restoration, offline errors and retries, offline logout/pending revocation, cancellation and keeping local navigation responsive. Existing preview tests check business GET allowlists, redirect rejection, bounded responses, private photos and unchanged local order/evidence state. Storage failure, corrupt records, origin validation, session scoping and login redirects are covered independently.

GUI fixture tests use synthetic data and a test-only memory credential store; the separate native Windows test verifies the production Credential Manager adapter. These are complementary checks, not a claim that a deployed production backend was tested through the desktop against real customer records. No real credentials or customer PII were needed.

## Files changed for this slice

- Backend: `app/intake.py`, `app/main.py`, new `app/access_privacy.py`; new `tests/test_workstation_v05a3.py`, adjusted `tests/test_workstation_preview_contract.py` mock actor names.
- Desktop: new `selby_workstation/connection.py`, `credential_store.py`, `desktop_auth.py`; updated `incoming.py`, `incoming_ui.py`, `desktop.py`, `app.py`, `__main__.py`; launcher guidance in `Launch_SELBY.vbs`; new `workstation-connection.example.ini`.
- Desktop tests: new `tests/incoming_fixtures.py`, `test_desktop_auth.py`, `test_desktop_auth_gui.py`; updated `test_selby_incoming.py`.
- These two V05A3 documents. The repository already contained other staged/unstaged/untracked work; it is not attributed to this slice. No frontend or research-artifact changes were needed for this mission.

## Manual acceptance procedure still required

1. Configure the real development backend/portal origins in the existing desktop settings. Launch via the Windows shortcut/VBS; verify local modules work with the backend stopped and with Incoming unconfigured.
2. Start the backend, sign in with a verified operator. Check automatic recent list, customer/reference search, dates/statuses/counts, an empty search, multiple pages, refresh and keyboard navigation.
3. Open an existing confirmed submission, inspect declarations/received/matched distinctions and an authorized private front/back photo. Confirm no local order or physical-card identifiers were created.
4. Close/relaunch; verify secure session restore. Sign out online; confirm backend revocation and no restore. Test password failure, a nonstaff account, expired/revoked session and membership removal.
5. Sign out while offline; confirm cleared UI, pending-revocation message and no order access. Reconnect/retry to complete revocation, then sign in again. Confirm existing local orders/evidence still work throughout.
6. On the target deployment, validate HTTPS certificates, actual auth origin/cookie settings, OS credential policy, external access-log privacy and real representative catalog/submission/photo data. Confirm no secrets or customer search terms enter proxy logs.

## Remaining limitations

First-party native password login is an explicitly scoped compatibility solution; backend OAuth/OIDC support is required before browser-based PKCE can be implemented. No refresh/SSO/MFA or non-Windows keychain support was added. Offline revocation is deferred until connectivity or server expiry. Efficient card-name search, production-scale query profiling and physical intake/import integration remain future work. No production-readiness claim is made.
