# SELBY TCG catalog V1.1 - validation

Date: 2026-10-25. Validation uses a dedicated PostgreSQL test database, production Next build, and headless Chrome with synthetic catalog data. No production migration, import or deployment was performed. V1.1 needs no migration.

## Repository finding

The former form conditionally rendered card search only after expansion selection; the existing cards endpoint also required expansion_id. The expansion endpoint already supported empty queries, localized name/code search, and pagination. The former UI exposed a zero counter and arrows beside a plain list rather than an opening dropdown. No reusable combobox existed in the inspected frontend.

V1.1 extends that same endpoint and adds one shared combobox used by both existing selectors. It keeps all existing catalog records, UUIDs, submission schemas, confirmation logic and authentication.

## Executed checks

| Command | Actual result |
| --- | --- |
| Backend `.venv/Scripts/python.exe -m pytest -q` | **349 passed**, 22 existing dependency/configuration warnings |
| Backend `.venv/Scripts/python.exe -m pytest tests/test_tcg_catalog.py tests/test_submissions.py -q` | **29 passed**, 2 existing warnings |
| Frontend `npm.cmd test` | **65 passed** |
| Frontend `npm.cmd run typecheck` | Passed |
| Frontend `npm.cmd run lint` | Passed, including final browser test changes |
| Frontend `npm.cmd run build` | Passed, production Next.js 16.4.0 build |
| Frontend `node tests/catalog-browser.mjs` | Passed against the final production build in headless Chrome |
| Workstation `.venv/Scripts/python.exe -m pytest tests/test_selby_incoming.py tests/test_selby_orders.py -q` | **22 passed, 5 skipped** (optional Qt coverage unavailable) |

The full backend suite includes existing authentication, migration, submission, pricing, checkout, intake/reconciliation, inspection and Workstation preview-contract regressions. Existing warnings concern Starlette/httpx compatibility and Alembic path separator configuration. Next reports an unrelated package-lock.json outside this repository; the build succeeds.

## Coverage and evidence

- Backend catalog tests cover card-name search without an expansion, required game/language scope, expansion-filtered and legacy expansion-only requests, literal search, localized scope, incompatible filters, card details, pagination, repeated names with distinct UUIDs and expansion metadata, and invalid parameters.
- Empty-query expansion coverage seeds 23 real database fixture expansions and navigates both pages. Card pagination traverses 46 stored fixture cards without loss or duplicates.
- Existing integrity tests verify saved mixed catalog/manual drafts, multiple entries, legacy optional references, manual detachment, mismatched snapshot rejection, confirmed immutability after catalog reimport and provider downtime with local records still available.
- Frontend state tests use the actual shared functions for name-first expansion population, distinct printings, parent/language resets, explicit manual detachment and draft restoration.
- The production browser test uses 43 synthetic expansions and 43 printings with the same card name. It checks immediate game-wide card search, printing labels, no implicit first-result selection, ArrowDown/Enter, Escape and input focus, real CDP pointer selection, an empty-query expansion dropdown, all three pages in both selectors, clearable expansion filters, harmless interface rerenders, language/game invalidation, catalog/manual saves, multiple saved entries after reload, and preserved unsaved quantity/notes during mode switches.
- Browser network coverage verifies loading feedback, error/retry/empty feedback and cancellation of a delayed obsolete query. Closed dropdowns issue no catalog requests. A 390px viewport check verifies that the dropdown does not create horizontal page overflow.
- Card selection now uses custom validity on the visible card combobox. Browser assertions verify that opening or typing a query alone cannot validate a selected printing; manual mode removes this prerequisite.

The browser test supplies a local synthetic backend and intercepts browser API traffic through CDP; it does not establish a full live-data FastAPI-to-browser integration. Backend endpoints and snapshots are tested separately against PostgreSQL.

## Browser harness fixes during validation

Early attempts exposed harness focus and timing assumptions. The final harness enables Chrome document focus emulation, waits for React/debounced results, scrolls instantly before real pointer selection, and tolerates an invalid interception ID when the application cancels an obsolete request. Failed attempts were rerun; only the passing final run is reported above. One interrupted harness run left its local Next/Chrome processes; these were explicitly stopped before rerunning. The final harness closes its own child processes and fixture server in finally.

## Files changed for V1.1

- `backend/app/tcg_api.py`: optional expansion with game/language scope; additive game and expansion context in cards list/detail responses.
- `backend/tests/test_tcg_catalog.py`: compatible scope, printings and multi-page regressions.
- `frontend/src/components/catalog-combobox.tsx`: new shared searchable combobox.
- `frontend/src/components/catalog-fields.tsx`: immediate card search, optional expansion, mode/reset integration and visible selection validation.
- `frontend/src/lib/catalog.ts`: populate expansion from the selected printing.
- `frontend/src/app/globals.css`: dropdown, scroll, focus and flexible control layout.
- `frontend/tests/catalog.test.mjs`, `frontend/tests/catalog-browser.mjs`: state and browser coverage.
- `SELBY_TCG_CATALOG_V1.md`, this report: API/UI changes, setup, limitations and validation.

No submission identifiers, confirmed snapshot fields, Workstation IDs, physical intake logic, grading evidence, authentication, payment or inspection restrictions were changed.

## Manual browser validation with imported catalog data

1. Use a local development database with the existing 0008 migration and at least two imported sets in one supported catalog language. To exercise pagination, import more than 20 sets/cards, spacing operator requests as documented in the architecture guide. V1.1 itself requires no additional migration.
2. Start FastAPI and Next with the existing backend rewrite configuration; sign in to a customer account and open a draft submission.
3. Choose a game/catalog language. Open card search immediately, type a known card name, and verify results across sets. Check that each row includes name, set name/code, collector number and language. Enter without highlighting must not choose a printing. Highlight with arrows and press Enter; verify every declared field.
4. Open the expansion field with an empty query. Verify available sets, scroll, search by localized name and code, load every remaining page, and select a row with mouse and keyboard. Escape should close the popup while retaining input focus.
5. With an expansion filter selected, search for cards and verify all results belong to that expansion. Clear it and verify game-wide results return. Select a printing, then change expansion, language and game in turn; incompatible card IDs and fields must reset. Switching interface-label language alone must preserve a selected filter.
6. Enable manual mode. Enter all four declared fields without selecting an expansion; set quantity and notes. Return to catalog mode and back: text, quantity and notes must remain until an explicit selection/reset. Save the manual entry and verify no catalog ID was assigned.
7. Save two different catalog printings and a manual entry, reload, and reopen an existing entry. Verify saved fields and IDs. Confirm a separate test submission, refresh the catalog, and verify the confirmed declaration and Workstation preview remain unchanged.
8. Use browser network throttling/offline mode: verify loading, failure/retry feedback, no stale results replacing a newer query, and a usable manual fallback. Restore connectivity and retry. Test at desktop and narrow mobile widths.

Reproduce the automated browser check after `npm.cmd run build` with `node tests/catalog-browser.mjs` from frontend. It uses ports 18171-18173, CHROME_PATH or the default Windows Chrome install, and an ignored profile at `.visual-review/catalog-profile`.

## Remaining limits

No live-provider-to-database-to-browser-to-Workstation end-to-end run or production catalog-data review was performed. Manual steps above remain to be run against the intended imported inventory. Synthetic browser coverage and PostgreSQL API coverage do not imply complete real catalog coverage or production readiness.

Only imported Pokemon FR/EN sets are searchable through the existing importer; other games, missing records and unimported languages use manual entry. Pagination remains offset-based and can shift during concurrent imports; an exact full page needs one extra request to discover the end. Results accumulate on explicit Load more rather than infinite scrolling. Very large loaded lists and large-catalog substring performance have not been load tested. Exhaustive screen-reader/device testing remains outstanding. No automatic provider refresh, cross-language printing equivalence or variant disambiguation was added. Saved drafts persist explicitly as before; unsaved text does not survive a reload.
