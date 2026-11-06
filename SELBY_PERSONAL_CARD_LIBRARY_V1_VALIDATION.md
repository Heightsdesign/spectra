# Personal card library V1 — validation and manual acceptance

Validation: 2026-10-25, Windows local development. No production deployment or migration. No customer cards/orders were created as live test fixtures. No existing rows, PC/ORD/SLB-C identities, grading evidence or protected research artifacts were rewritten.

## Actual automated results

| Check | Result |
| --- | --- |
| Full backend regression after inspection-return denial case | 415 passed, 23 existing dependency/config deprecation warnings, 120.30 seconds |
| Focused library + independent PostgreSQL concurrency suite, including one subsequently added same-catalog-copy case | 10 passed, 3 dependency/config warnings, 1.95 seconds |
| Complete Workstation suite including authentication/connection/physical intake | 168 passed, 1 opt-in native credential-store test skipped, 58.37 seconds |
| Existing frontend unit suite | 72 passed |
| TypeScript | Passed |
| ESLint with zero warnings | Passed |
| Production Next webpack build | Passed; existing outside-repository lockfile warning |
| New headless Chrome library workflow | Passed 12 scenario groups, including mobile layout |
| Existing catalog/photo/configuration browser regression | All four reported scenario groups passed |
| Ruff on new backend modules, migration and tests | Passed |
| `git diff --check` | Passed; existing line-ending conversion notices only |

The full backend run preceded the last extra same-catalog fixture case. The later focused 10-test result includes that case; counts overlap and must not be added together. No backend implementation changes followed that full run. Initial regression testing found that adding a null field to anonymous entry responses broke a legacy round-trip client; managed copy metadata is now emitted only for linked entries, and the complete regression rerun passed. One pre-existing QR/PDF decode smoke failed once, then passed in isolation and subsequent full runs without changes to QR/label code.

Commands:

```powershell
# backend, guarded separate PostgreSQL TEST_DATABASE_URL ending in _test
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m pytest tests/test_library.py tests/test_library_concurrency.py -q
../scanner_agent/.venv-analysis/Scripts/python.exe -m ruff check app/library.py app/library_models.py tests/test_library.py tests/test_library_concurrency.py alembic/versions/0010_customer_library.py

# frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
node tests/library-browser.mjs
node tests/catalog-browser.mjs

# scanner_agent
$env:QT_QPA_PLATFORM='offscreen'
$workstationTests=Get-ChildItem tests/test_selby*.py | ForEach-Object { $_.FullName }
.venv-analysis/Scripts/python.exe -m pytest @workstationTests tests/test_connection_settings.py tests/test_desktop_auth.py tests/test_desktop_auth_gui.py tests/test_physical_intake.py -q -p no:cacheprovider
```

## Backend evidence

The new library tests execute FastAPI with the actual PostgreSQL models and existing authentication/CSRF conventions. They cover standalone registration without any SP, atomic multi-copy registration within an order, equal manual copies, equal catalog printings with distinct CC IDs in different orders, one-draft assignment, rejection in another active order, draft release/reassignment, persistent history, foreign-customer 404 isolation, confirmed-order immutability, legacy grouped quantities, search/pagination, private photos, failed-snapshot rollback and unchanged Workstation intake detail/PC behavior.

Concurrency uses a dedicated temporary schema and genuinely independent SQLAlchemy sessions, authentication sessions and FastAPI clients. Two submissions compete for the same CC; exactly one response is 201 and one is 409. PostgreSQL contains one active assignment and one resulting entry. This does not rely on a Python mutex or SQLite reservation.

Quote tests configure an existing order tier/label, produce a quote, attach a copy, assert stale-quote invalidation and inherited configuration, and compare the exact quantity-based price before/after removal. Existing commercial, address, payment and pricing regressions run unchanged.

Return tests execute actual parcel reception, admin custody authorization, explicit PC-to-entry matching and reconciliation. Operators cannot release the copy. An administrator's explicit uninspected/unlinked return releases the historical assignment; retry is idempotent. A later library name/photo change leaves the prior confirmed SP JSON and original photo bytes unchanged. A second order can select the returned CC. Historical PC inspection lookup is denied for the returned object. Adding an inspection dossier blocks return/release entirely. Graded/inspection return lifecycle remains intentionally unsupported.

## Browser evidence and limits

`library-browser.mjs` runs the production Next build and headless Chrome on isolated ports 18181/18182/18183 with a synthetic API and fresh test profile. It exercises separate My Cards/My Orders sections, 26-row library navigation, registration without an order, explicit empty order creation, unavailable-copy disabled state, selecting an available copy, reload persistence, draft removal, registering two distinct identical copies, confirmation read-only UI, network error/retry, French/English labels and a 390px mobile overflow check. Synthetic fixture records never touch PostgreSQL or real customer data.

The existing catalog browser regression separately passed name-first printing search, optional set selection, full pagination, keyboard/mouse interaction, manual fallback, per-copy front/back photo selection/preview/replacement/removal, upload failure fallback, legacy grouped-entry behavior, order-wide configuration, notes, quote behavior, return-address restrictions and mobile presentation. It intentionally uses legacy API fixture responses without the new capability flag; the new library browser validates the new flow.

The mobile artifact was visually inspected at `frontend/.visual-review/library-mobile.png`. It uses the existing design-system form and card classes. These browser checks complement actual API/PostgreSQL tests; they are not an end-to-end browser-to-live-database acceptance claim. The fixture's client assertions are not the exclusivity security boundary.

## Migration performed locally

Revision 0010 was first exercised by test migrations. Before applying to development, existing development-auth/loopback/allowed-database guards verified the local spectra database and its server metadata. The prior version was 0009. Hashes of every original column/row in customers, customer_submissions, customer_submission_entries, customer_submission_photos, physical_cards, submission_intakes and inspections were recorded in memory. After upgrade to 0010 those hashes were identical, and both new tables were empty. No existing data was converted or merged. No production database was accessed.

Anonymous GET `/api/library/copies` returned 401 from both the actual FastAPI localhost:8000 origin and Next localhost:3000 proxy after activation, confirming the route is present and authenticated. This anonymous smoke does not substitute for customer acceptance.

A subsequent read-only live check signed in a fictional customer through Next.js, read the authenticated library page JSON and rendered account HTML containing My Cards/My Orders, then revoked that test session. It passed without creating any card/order or touching Windows Credential Manager. This verifies live route/schema activation, not a browser-to-live-database write workflow.

Downgrade deliberately refuses destructive automatic deletion. See the implementation document for rollout and backup requirements. Other environments still require an authorized schema upgrade before starting the changed backend. Existing local processes may require restart if they do not reload source/configuration.

## Files changed

- New backend: `app/library_models.py`, `app/library.py`, `alembic/versions/0010_customer_library.py`, `tests/test_library.py`, `tests/test_library_concurrency.py`.
- Backend integration: `alembic/env.py`, `app/main.py`, `app/submission_models.py`, `app/submissions.py`, `app/inspection_eligibility.py`.
- New frontend: `src/lib/library.ts`, `src/components/card-library.tsx`, `tests/library-browser.mjs`.
- Frontend integration: `next.config.ts`, `src/components/account-area.tsx`, `src/components/submissions.tsx`, `src/lib/submissions.ts`, `src/lib/submission-photos.ts` (generic response type; existing photo transport retained).
- These two library documents. Existing unrelated staged/unstaged files and local credential documentation were preserved. Build-generated Next type declarations may be refreshed by the required production build.

## Manual acceptance procedure

Use only local fictional customer/operator accounts, whose credentials remain in the ignored local credentials document. Do not use real cards/production services for these acceptance steps.

1. Start/reload the migrated local FastAPI and Next portal. Log in as client01. Open My Cards and register one manual copy with game/name/language, leaving expansion and number blank. Verify no order was created. Register another copy with the same printing and confirm distinct CC references. Optionally select a catalog printing; it must remain a separate reference from the CC.
2. Add optional front/back images, preview and replace/remove them while the copy is available. Verify invalid/oversized files fail without disabling manual registration. Photos remain private and labeled unverified customer declarations.
3. Open My Orders, choose Create order, and verify an empty SP draft. Choose from my cards and select the first copy. Verify quantity one, its CC reference and retained declaration/photo snapshot. Reload and verify persistence.
4. In another tab create a second draft. The first CC must be unavailable; a stale/racing attempt must return a conflict. The second identical CC must remain selectable. Remove the first CC from the first draft, refresh the chooser, and select it in the second draft. Verify there is one active reservation and no duplicate entry after retries.
5. Register quantity two directly in a draft. Verify two distinct CC references and two quantity-one entries. Existing legacy grouped entries must retain their quantity and photographs. Test a known mixed-config legacy draft: adding copies must require explicit order-wide normalization, not silently replace exceptions.
6. Continue to configuration and quote. Change tier/label and verify every new copy inherits the single order configuration. Add/remove a copy and verify the old quote is invalidated and quantities/prices recalculate under existing rules. Address/shipping/payment restrictions must remain visible and unchanged.
7. Review selected copies and confirm. Verify editing/removal and reuse in a second active order are blocked. Log in as client02 and confirm client01's copies/photos/order details are inaccessible.
8. As an authorized operator, verify the confirmed SP in Workstation Incoming Orders, separate declared entries/quantities and photos, then exercise receipt/matching only on the test objects. There must be no customer-side allocation of ORD/SLB-C and no replacement of existing PC IDs.
9. For a test **uninspected, unlinked, reconciled** copy actually returned to the customer, use the authenticated admin API and a specific return reason. Verify audit/release metadata, the unchanged historical SP/photos/PC, and availability for a new SP. Operators/customers, unreceived copies and any inspection dossier must be rejected. Do not use this path for graded shipments; the outbound lifecycle is still required.
10. Repeat critical screens in French/English and at mobile width; test network failure/retry and backend restarts. Record actual browser-to-local-database and native Windows acceptance before any deployment or production-readiness claim.
