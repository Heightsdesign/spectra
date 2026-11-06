# SELBY V0.6a — validation

Validation date: 2026-11-03. All provider confirmations and numeric catalogs used here are synthetic test data. No actual payment, email, refund or production order mutation occurred.

## Results

| Check | Result |
| --- | --- |
| Broad backend regression, `pytest backend/tests` | **482 passed**, 247.98 seconds, at the broad-sweep revision |
| Final focused commercial/migration/pricing/checkout/library/concurrency regression | **130 passed**, 8.57 seconds, after final domain safeguards |
| Frontend unit/request tests, `npm test` | **77 passed** |
| TypeScript | Pass |
| Production Next build | Pass |
| ESLint on changed frontend components/libraries | Pass |
| Ruff E4/E7/E9/F/I on new backend modules/migrations/tests | Pass |
| Production Next + headless Chrome with synthetic API | Pass; mixed services, consent, disabled payments, FR/EN, mobile layout |

The broad sweep ran before the last narrowly scoped shipping/payment/receipt and presentation refinements. The 130-test focused run validates the final backend commercial source; the final build/browser run validates the final customer presentation. Counts are not added together as unique tests.

Existing warnings are FastAPI/Starlette TestClient/httpx deprecation, Alembic `path_separator`, Node experimental TypeScript stripping, and Next's ignored parent-directory lockfile warning. They did not fail validation.

## Confirmed commercial coverage

`backend/tests/test_paid_order_foundation.py` covers:

- Multiple services in one order, arbitrary service IDs, explicit unselected draft services, invalid/unknown/disabled tiers.
- Frozen service prices, terms, tax and shipping after catalog/address changes; exact complete unpaid obligations.
- Inclusive/exclusive/exempt service and shipping calculations without double-counting tax.
- Missing/inactive rates, unsupported card count, insufficient coverage, missing price and invalid shipping tax configuration.
- Destination changes invalidating unaccepted quotes while accepted destinations remain frozen.
- Thirty-day deadlines across month ends, year boundaries and leap years; no deadline at quote acceptance.
- Trusted verifier failure, incorrect full amount/currency, future payment time, confirmation replay/conflict and owner/staff boundaries.
- Customer shipment declarations as unverified information, idempotent retry, conflicts and multiple parcels.
- Late dispatch preserving the order without cancellation, forfeiture, refund or automatic missing-card discrepancies.
- Five paid declared cards with three received: missing quantities require explicit audited discrepancy/reconciliation decisions; quote/payment amounts remain unchanged; no fake PCs or inspections are created.
- Additional PCs requiring their own accepted supplementary quote, explicit incremental shipping rate, explicit assignment and separate payment. Competing supplemental quotes become stale after another acceptance. Original quote and custody audit remain unchanged.
- Supplementary payment cannot substitute for the unpaid original return-shipping baseline.
- Unpaid physical receipt is reported independently, without establishing payment or a dispatch deadline.
- Existing inspection payment provider remains fail closed even when the isolated foundation ledger is exercised with synthetic trusted confirmations.

`backend/tests/test_paid_order_migration.py` creates a disposable schema at 0012 with existing customer order, declared entry, parcel, PC, grading-card/image metadata, inspection, custody event and audit rows. It upgrades to head, verifies the old rows exactly unchanged and new financial tables empty, confirms BIGINT storage, then downgrades/re-upgrades the empty commercial foundation and checks the old records again. It does not alter development or production schemas.

The broad backend suite additionally covered existing auth, customer operations, catalogs, library, photo/evidence handling, custody, reconciliation, inspection, production bridge, void lifecycle and independent-connection concurrency tests. The pricing concurrency fixture's cleanup is restricted to the guarded `_test` database and its own fixture customer; it temporarily disables only new append-only fixture triggers inside cleanup, then restores them. No such cleanup API exists in the application.

Frontend tests verify consent request payloads contain no payment assertions/prices, dispatch stays disabled without a trusted payment timestamp/deadline, late dispatch is not treated as forfeiture, arbitrary configured service IDs work, and unreliable shipping/tax/terms state never becomes payable. Browser testing runs the built customer portal against a local synthetic API, with no customer database access.

## Browser artifacts

- [Browser acceptance record](validation_artifacts/v06a/browser-validation.json)
- [Desktop checkout and supplementary quote](validation_artifacts/v06a/checkout-desktop.png)
- [French mobile view](validation_artifacts/v06a/checkout-mobile.png)

The browser fixture uses visibly TEST-only service names, amounts, addresses and identities. Its assertions exercise per-entry editing without changing another card, mixed-service quote generation and confirmation, complete quote consent, unpaid shipment controls, supplementary consent, disabled payment actions, French/English text and mobile overflow protection. It is not evidence of a live provider payment or real customer order.

## Reproduction

From repository root, using a fresh basetemp path:

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests -q --basetemp=test_tmp_run/v06a-backend-full-01
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_paid_order_foundation.py backend/tests/test_paid_order_migration.py backend/tests/test_pricing.py backend/tests/test_checkout.py backend/tests/test_library.py backend/tests/test_pricing_concurrency.py backend/tests/test_submissions.py -q --show-capture=no --basetemp=test_tmp_run/v06a-release-final
```

Tests require PostgreSQL via `TEST_DATABASE_URL`. The fixture rejects databases not ending `_test` and rejects the configured development database. Disposable-schema migration tests require schema creation privileges. Concurrency fixtures commit isolated records and remove only their own guarded test records.

From `frontend`:

```powershell
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
node_modules/.bin/eslint.cmd src/components/paid-order-panel.tsx src/components/pricing-panel.tsx src/components/checkout-panel.tsx src/components/submissions.tsx src/lib/commercial.ts src/lib/pricing.ts src/lib/checkout.ts --max-warnings=0
node tests/paid-order-browser.mjs
```

Browser validation requires installed Chrome (or `CHROME_PATH`), the production build and free loopback ports 18281–18283. It starts and closes its own synthetic API, Next server and headless browser. Profiles/artifacts stay under workspace validation directories.

## Release limits

Development/production databases were not migrated, no commercial catalog was published, and no live provider was contacted. Apply migrations before running the updated backend in a release. Charging remains disabled, and the existing grading provider is intentionally unchanged.

Actual business rates, carriers, insurance, terms and tax treatment remain unapproved configuration. Stripe, current refund/dispute/hold evidence, notification delivery/scheduling and post-payment commercial amendments remain outside V0.6a. See [unresolved decisions](SELBY_V06A_UNRESOLVED_DECISIONS.md) and [V0.6b handoff](SELBY_V06B_STRIPE_HANDOFF.md). The earlier complete V0.6a document was unavailable, so alignment with any additional requirements in that missing document remains unverified.
