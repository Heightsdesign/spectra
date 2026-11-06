# SELBY — Single order configuration V1 validation

Date: 2026-10-25. Local repository, isolated PostgreSQL tests, production Next build, headless Chrome with synthetic HTTP fixtures and real offscreen PySide6 tests. No production deployment, data modification, pricing publication or migration was performed. No new migration/dependency is needed.

## Actual results

| Command | Result |
| --- | --- |
| Backend `.venv/Scripts/python.exe -m pytest -q` | **380 passed**, 22 existing warnings |
| Frontend `npm.cmd test` | **72 passed** |
| Frontend `npm.cmd run typecheck` | Passed |
| Frontend `npm.cmd run lint` | Passed, including the final browser test |
| Frontend `npm.cmd run build` | Passed, production Next.js 16.4.0 build |
| Frontend `node tests/catalog-browser.mjs` | Passed against the production build, including order configuration, legacy exceptions, notes, quote lifecycle and existing registration/photo/return checks |
| Workstation `.venv-analysis/Scripts/python.exe -m pytest tests/test_selby_incoming.py tests/test_selby_orders.py -q` with `QT_QPA_PLATFORM=offscreen` | **29 passed**, no skips |

Existing warnings concern Starlette/httpx compatibility, Alembic path separator configuration, Node experimental type stripping and Next ignoring a lockfile outside this repository. They did not fail validation. Database tests use the repository fixture that requires a separate `_test` database and rejects the development database name.

## Backend evidence

`backend/tests/test_order_configuration.py` covers:

- Atomic order-wide processing/label choices plus order notes, one submission-version increment, distinct unchanged card notes and invalidation of old quotes.
- Real PostgreSQL persistence/readback and actual quote calculations across multiple entries/physical quantities. New quotes use the common saved values and snapshot the saved order notes.
- New identification-only card creation inheriting the saved configuration. First-card defaults and optional identification fields remain supported.
- Identification/card-note/quantity edits preserving legacy per-card exceptions when configuration fields are omitted.
- Legacy per-entry and mixed quote APIs remaining operational, including confirmed mixed snapshots that cannot be rewritten by the global operation.
- Old global payloads omitting notes preserving existing order notes; explicit full or partial legacy card-creation values retaining their explicit/default semantics.
- Mixed legacy API creates preserving old default behavior and not altering earlier exceptions; the current V1 UI prevents that conflicting create path until conversion.
- Invalid options, oversized notes and stale versions not partially saving either configuration or notes.
- Upgrade-array order being ignored for common-configuration detection without mutating stored arrays.
- Order notes and identification remaining saveable without a pricing catalog.

The full suite retains pricing/discount/tax, confirmation/acceptance, immutable historical snapshots, ownership/CSRF/version conflicts, catalog/manual identification, photos, addresses/returns, custody, inspection and Workstation preview-contract regressions. Commercial catalog documents and calculation logic were not changed.

## Frontend/browser evidence

`frontend/tests/pricing.test.mjs` tests the actual common-configuration functions, including upgrade-order equivalence, mixed detection and no input mutation. Existing localized pricing, compatibility and request tests remain green.

`frontend/tests/catalog-browser.mjs` now serves synthetic development pricing in addition to its existing catalog/photo/return fixtures. Its real production-rendered DOM checks:

1. Pricing unavailable: no invented selectors, order notes saved through the existing notes API before any cards/services exist. Pricing recovery then renders the one selector pair.
2. A normal saved-card draft: exactly one processing-speed selector and one slab-label selector across the entire customer page; neither exists inside the registration form. Exactly one `notes` card textarea and one separately scoped `order_notes` textarea exist.
3. One save sends choices and order notes together and applies them to all saved entries without changing card notes. Navigation away/back restores the saved selections and notes.
4. Injected legacy per-card exceptions survive load/refresh unchanged. Existing values are read-only, the global pair is disabled, and review is blocked. Notes-only save makes no configuration request and preserves exceptions.
5. Explicit replacement acknowledgement enables the single pair. Saving then unifies the draft; a subsequently registered card inherits the saved settings.
6. Quote generation uses those values. Changing global choices invalidates the prior quote while preserving its snapshot; the next quote consistently reflects the new effective configuration.
7. At a 390px viewport, the page has no horizontal overflow and order selects/textarea have semantic labels. Existing keyboard/mouse catalog interaction, request cancellation, localization and private photo checks remain covered.
8. Review/confirmation remove editable configuration selectors and retain saved photo/order behavior. Customer return preparation still contains no parcel inputs, preserves old measurements and leaves payment unavailable.

The browser backend/quotes are controlled synthetic fixtures, not the real price engine. Actual price calculation and transaction behavior are tested separately in PostgreSQL. This is not a full live-data browser → FastAPI → PostgreSQL/storage → Workstation deployment validation.

## Workstation compatibility

The real Qt-enabled Incoming/order suite passed all 29 tests, including legacy declaration display, private customer-photo preview, disconnect clearing, GET-only staff access, identity distinctions and local `ORD-…` / `SLB-C-…` behavior. No Workstation, grading, reconciliation, inspection or physical-identity code was changed for this slice.

## Changed files

| Area | Files |
| --- | --- |
| Portal flow | `frontend/src/components/submissions.tsx`, `pricing-panel.tsx` |
| Shared inference/localization | `frontend/src/lib/pricing.ts`, `submissions.ts` |
| Backend inheritance/atomic save | `backend/app/pricing.py`, `submissions.py`, `pricing_api.py` |
| Tests | `backend/tests/test_order_configuration.py`, `frontend/tests/pricing.test.mjs`, `catalog-browser.mjs` |
| Documentation | `SELBY_ORDER_CONFIGURATION_UX_V1.md`, this report |

## Manual/local verification

Use the existing local backend/PostgreSQL/Next setup; no new migration is needed. Use only approved local catalog configuration, or the existing synthetic fixtures for automated tests. Do not publish example rates commercially.

1. Create a draft, add two cards with different quantities and card notes. Registration must contain no editable speed/label controls.
2. Find the one order-configuration form. Check distinct card/order note labels, select speed and label, enter order notes and save once. Reload/navigate away/back; the settings and both note scopes must persist independently.
3. Add another card without configuration fields and verify it inherits the saved choices. Generate a quote and check every physical quantity uses the same configuration. Change global settings, save and verify the old quote is stale/invalidated and a newly generated quote uses the new values.
4. In an isolated legacy fixture, create different per-card configurations through the retained API. Reload the portal: no background normalization may occur. Edit identification and save order notes without conversion; verify the exceptions are unchanged. Verify new-card creation/review are blocked until explicit replacement is acknowledged and saved.
5. Open a confirmed mixed historical submission. Its values must be read-only and must not be normalized. Existing backend quotes should reflect the stored per-card values.
6. Temporarily make pricing unavailable: manual registration/defaults and order-note saves must remain available without invented configuration. Restore service availability and refresh.
7. Check narrow/desktop widths and keyboard labels. Confirm there is only one editable selector pair for a normal priced draft, one card-note field and one order-note field. Confirmed/review views should have no editable service selectors.
8. Recheck Incoming Submissions and existing quote/payment/return restrictions. No ID substitution or new grading/reconciliation behavior should appear.

Automated browser reproduction, from `frontend` after `npm.cmd run build`: `node tests/catalog-browser.mjs`. It uses local ports 18171–18173, `CHROME_PATH` or the default Windows Chrome install, and ignored `.visual-review/catalog-profile` fixtures/profile files. Workstation tests use the existing Qt-capable `.venv-analysis`; PowerShell can set `$env:QT_QPA_PLATFORM='offscreen'` before pytest.

## Remaining limits

- Shared configuration is inferred from saved entries rather than stored in a new order record. Empty orders cannot choose/persist services, and deleting every entry removes the preference to inherit. Order notes remain independent and persist.
- The compatibility acknowledgement and mixed-draft progression rules apply to the V1 customer UI. Retained APIs still support explicit per-card/mixed workflows; this version does not remove those contracts.
- A customer’s explicit legacy conversion replaces draft exceptions. V1 does not offer a per-card editor to restore them afterward; historical immutable quotes retain their prior snapshots, while backend per-card capabilities remain available for future interfaces.
- Unavailable/deprecated configured options must be resolved against available services before saving a new effective configuration; existing stored values are not silently reset.
- Only explicit saved drafts persist; unsaved text/choices do not survive a full page reload, matching the existing persistence model.
- No commercial fees, tax policy, shipping rules, payments, AI recognition or new production workflow was introduced. No production-readiness claim is made.
