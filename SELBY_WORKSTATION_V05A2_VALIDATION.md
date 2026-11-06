# SELBY Workstation V0.5a.2 — Validation

Date: 2026-10-25. These are actual automated results, not live deployment acceptance.

## Executed checks

Commands below ran from `scanner_agent` unless indicated otherwise, using the existing environments and `-B` to avoid new Python bytecode. `-p no:cacheprovider` avoids pytest cache writes.

| Check | Result |
| --- | --- |
| `.venv-analysis/Scripts/python.exe -B -m pytest tests/test_selby_incoming.py -q -p no:cacheprovider` | **16 passed**, 8.28 s |
| Same environment: `pytest tests/test_selby_desktop.py tests/test_selby_incoming.py -q -p no:cacheprovider` | **26 passed**, 10.66 s |
| Full scanner/workstation: `pytest tests -q -p no:cacheprovider` | **483 passed, 3 failed**, 84.63 s; three existing Chrome research-editor tests failed in sandbox |
| Three Chrome tests rerun outside sandbox, fresh unique `--basetemp` | **3 passed**, 3.39 s |
| From `backend`: `.venv/Scripts/python.exe -B -m pytest tests/test_workstation_preview_contract.py -q -p no:cacheprovider` | **5 passed**, 0.20 s; actual FastAPI router/auth code with isolated database double; no migration fixture used |
| Ruff on both new client/UI modules, modified desktop/app modules and both new test files | **All checks passed** |

Chrome rerun cases: `test_blind_reference.py::test_blind_browser_manual_synthetic_only`, `test_physical_reference.py::test_physical_editor_real_browser_on_synthetic_image`, `test_reference.py::test_offline_browser_interface`. Initial sandbox failures were missing Chrome page discovery and `CDP timeout: Runtime.enable`. The first outside-sandbox attempt could not access pytest's previous temporary directory (three setup errors); using a new temporary directory resolved that. No research source was changed to make the tests pass. The combined initial suite plus targeted rerun covers all 486 scanner tests, but is not reported as a single clean full-suite run.

Backend warnings: existing Starlette/httpx TestClient deprecation; unknown `cache_dir` config option when disabling pytest cache support.

## Coverage and preservation evidence

- Client tests perform actual local HTTP requests with the existing endpoint shapes and cookie names. Requests are recorded and asserted to be GET-only under `/internal/intake/`. Search encoding and pagination parameters are verified.
- Existing session authorization is additionally exercised through the actual FastAPI application and `authenticated()` helper. Tests cover successful staff reads, expired/revoked sessions, disabled accounts and absent staff membership. Database writes/commits are asserted absent. This uses a database double, not PostgreSQL or a live account.
- Timeout, unreachable endpoint, HTTP backend failure, invalid response shape and disabled redirects are covered. Non-local HTTP, credentials embedded in URLs, API paths/query strings, malformed ports and production cookies over HTTP are rejected.
- GUI tests cover empty/loading/error/disconnected states, multiple entries with quantity, fewer physical cards than declared units, parcels, missing-card discrepancy, refreshed holds, reference search, expiry, clearing data and ignoring results arriving after disconnect.
- A delayed HTTP response runs while a Qt timer keeps firing and the operator switches to Inspection. This checks event-loop responsiveness rather than relying only on elapsed request time.
- A real temporary SQLite order/card registry and saved grading dossier/images/report are hashed before/after preview. Their bytes, existing `ORD-000001` / `SLB-C-000001` identities, active session object and in-memory session data remain unchanged. Preview also opens without creating a registry, and accepted close clears its in-memory client.
- Existing desktop regression tests exercise navigation, local order creation, explicit saved-session association, reopening pinned evidence, registry selection, grading refresh and preservation of unsaved inspection work.

Implementation files: `scanner_agent/selby_workstation/incoming.py`, `incoming_ui.py`; small navigation/title changes in `desktop.py` and close-time session clearing in `app.py`. Added tests: `scanner_agent/tests/test_selby_incoming.py`, `backend/tests/test_workstation_preview_contract.py`. Guides are at repository root beside the audit. No backend business routes/models, migrations, SQLite schema, local order service, grading policies, protected research code or evidence were edited.

## Scope not validated

No production login, live PostgreSQL retrieval, deployed HTTPS, native manual visual QA, reception/reconciliation mutation, payment clearance, scanner hardware or label printing was tested. The full backend PostgreSQL suite was not run because its fixture applies Alembic migrations; none were authorized for this task. No frontend code changed. End-to-end intake is **not complete or claimed**.

Before durable import: approve a registry/environment identity and association contract, additive schema and atomic import journal, deduplication and recovery tests, and operator reconciliation procedures as described in the audit. Do not convert this preview into an automatic ID allocator or a payment/inspection override.
