# SPECTRA W3.3 — checkout preparation

This document supersedes W3.2's grading-only acceptance and commercial-test instructions in `PRICING.md`. The W3.3 catalog is **not published** by the migration or implementation. No tax regime, carrier, receiving address or shipping rate has been assumed. Payment remains unavailable even for a complete commercial quote.

## 1. Architecture decisions

W2 authentication, verified customers, session-bound CSRF and customer locking are reused. W3.1 card data remains immutable after submission confirmation. Delivery preparation has its own record and optimistic version, so customers can complete delivery for a confirmed submission without reopening cards. Accepted delivery terms cannot be edited through submission endpoints.

The W3.2 conflicts were identified before implementation: percentage discounts cannot express the approved exact unit brackets, and grading-only acceptance does not establish a complete checkout amount. Additive unit-price brackets replace percentage discounts for V1; the validator forbids configuring both. New acceptance requires complete tax/address/shipping readiness. Existing accepted snapshots are neither rewritten nor reinterpreted as full payable orders.

All financial calculations remain server-side integer cents with Decimal HALF_UP rounding. The frontend only formats amounts and parses declared-value input to cents. There are no new third-party dependencies or changes to internal grading/image schemas.

## 2. Commercial pricing configuration

`backend/pricing/spectra-v1.json` contains the approved grading amounts:

| Total physical quantity | Base per physical card |
| --- | --- |
| 1–4 | EUR 19.90 |
| 5–9 | EUR 17.90 |
| 10+ | EUR 16.90 |

The highest eligible bracket applies to every card, across all entry rows. The list base remains 1990 cents; the exact bracket savings are itemized as the volume discount. Standard adds 0, Express 990, Priority 1990 cents per physical card. Classic adds 0 and Detailed 390 cents per physical card. Quantity multiplies every applicable surcharge. V1 has no percentage-discount rules, preventing double discounts.

Detailed-label production intent is stored as structured `label_presentation`: front position, overall grade visible, four categories centering/corners/edges/surface. Selected upgrade identifiers remain on entries; immutable quotes capture the presentation metadata. No grades, printing or certificates are generated. Processing speed changes no grading criteria or grade. All turnaround fields are null.

The pricing engine exposes list base, processing and upgrade totals, discounts, tax, net and grading total separately, plus the applied bracket and individual entry configurations.

## 3. Catalog publishing instructions

Use the existing operator CLI from `backend`, after applying migrations:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.pricing_catalog validate pricing/spectra-v1.json
```

The supplied document validates structurally but reports `TAX VALIDATION PENDING - PUBLICATION BLOCKED`. Attempting to publish it raises a validation error. Copy it to an operator-controlled file, obtain and record the actual tax decision, configure the tax fields described below, validate again, then publish:

```powershell
.venv/Scripts/python.exe -m app.pricing_catalog validate path/to/validated-commercial-catalog.json
.venv/Scripts/python.exe -m app.pricing_catalog publish path/to/validated-commercial-catalog.json
```

Each publication creates a new UUID revision and changes the singleton pointer transactionally. Documents and quotes have database UPDATE-rejection triggers. Old accepted terms retain their original revision and prices. Do not publish synthetic test fixtures or the development example as commercial rates.

## 4. Tax configuration and unresolved assumptions

The supplied amounts are intended customer-facing amounts. V1 sets `customer_gross_prices:true`; consequently `exclusive` tax is rejected for this catalog. Once fiscal treatment is validated, choose either:

- `inclusive`: the configured customer amounts already include the validated tax. Set the actual `tax_rate_bps`, localized tax description and nonempty `tax_validation_reference`. Extract tax per entry as `round_HALF_UP(gross × rate / (10000 + rate))`; net is gross minus extracted tax.
- `exempt`: only following an actual validated decision; rate must be zero, with the applicable localized explanation and validation reference. Gross equals net, with zero tax.

The template's `pending` mode and zero numeric placeholder do **not** assert exemption or a VAT rate. Pending treatment cannot be published. Commercial publication also requires a tax-validation reference. Legacy records without that reference may still be read, but cannot become newly accepted checkout-ready quotes. Legacy exclusive-tax calculations remain supported for historical compatibility.

Shipping services independently require an inclusive or exempt treatment, rate, and validation reference; shipping tax is calculated separately. No jurisdiction or cross-border tax policy is inferred from the selected address. An operator must validate applicability before enabling destinations; this milestone does not implement a jurisdiction rules engine. Neither this document nor synthetic tax assertions in tests approve any fiscal treatment.

## 5. Shipping address data model

`customer_addresses` stores UUID, customer FK, optimistic version, recipient (200), line1/line2 (200), postal code (32), city (100), ISO alpha-2 country, phone (32), instructions (1000), and timestamps. Optional fields use empty strings; postal codes are optional for international compatibility. Countries are validated against ISO codes independently of shipping availability. Supplied phone numbers allow international punctuation and require 7–15 digits; an eligible shipping service may require a phone.

All fields are bounded and reject control characters. Customers have at most 100 saved addresses. Ownership derives from the session, never a request field. DELETE requires the current version and is rejected when any submission selects the address. Quotes retain independent address snapshots even if an unused address is later deleted. Billing can later select a separate address without conflating delivery with invoicing.

`submission_deliveries` stores submission PK/FK, selected address FK, its own version, declared collectible value in cents, service identifier and bounded parcel weight/dimensions. Drafts and confirmed submissions may prepare delivery until commercial acceptance. Card versions and confirmation semantics remain unchanged.

## 6. Shipping readiness rules

`backend/pricing/shipping-unconfigured.json` intentionally contains no supported destinations, services, rates or receiving address. The migration does not publish it. A trusted operator may validate/publish a complete document using:

```powershell
.venv/Scripts/python.exe -m app.shipping_catalog validate path/to/verified-shipping.json
.venv/Scripts/python.exe -m app.shipping_catalog publish path/to/verified-shipping.json
```

`ShippingCatalog`/`ShippingService` in `backend/app/checkout_schemas.py` define the format: EUR currency, supported destinations, optional receiving-address text, and identifier-keyed services with localized names; destination countries; availability; customer charge; tracking; verified trading-card coverage flag and evidence reference; explicit coverage amount, terms and exclusions; phone requirement; optional maximum weight/dimensions; and validated tax treatment. No real example amounts or guarantees are shipped. Different destination/parcel offers can be separate configured services without schema changes. This is an operator-maintained flat-offer foundation, not a carrier calculator.

An order requires:

1. Configured and validated grading tax and commercial grading rates.
2. A selected customer-owned return address and supported country.
3. A selected available service for that country, with tracking and verified applicable trading-card coverage.
4. A declared value within configured coverage, a phone where required, and supplied parcel measurements satisfying configured limits where applicable.
5. A nonempty card submission.

Readiness states include `tax_configuration_pending`, `development_rates`, `missing_return_address`, `unsupported_shipping_destination`, `shipping_price_pending`, `declared_value_required_or_uncovered`, `delivery_phone_required`, `parcel_requirements_pending`, `submission_empty`, and `ready_for_checkout`. Multiple unresolved states may be returned. Incomplete shipping has null charge; incomplete orders have **null `final_payable_minor`**, never the grading subtotal as a payable total. Unavailable/unknown/destination-incompatible service selections are rejected. Unverified or inapplicable coverage cannot produce a payable amount or an insured claim.

Inbound policy is shown in French and English: customers arrange/pay for shipping, package securely, identify the submission reference, and understand online confirmation is not physical receipt. No prepaid inbound label exists. Receiving instructions remain explicitly pending until an operator supplies the real receiving address. No card is marked received.

## 7. Quote lifecycle and backward compatibility

New quote snapshots add `checkout`, containing grading configuration/bracket/items/tax, shipping revision and service terms/charge/tax, return-address snapshot, delivery/declared value/parcel, readiness, currency and final payable amount when complete. Existing quote timestamps retain creation/expiration; the parent quote captures pricing revision. Existing `snapshot.total_minor` deliberately retains its W3.2 meaning of **grading total**; only `checkout.final_payable_minor` represents a complete order amount.

Unaccepted quotes compare card pricing revision, delivery version, selected address ID/version and shipping configuration UUID. Address edits, delivery edits and shipping publication invalidate affected quotes without rewriting their JSON. Expiration and grading-catalog changes retain existing stale-quote handling. Recalculation reuses only a still-valid matching quote. Customer locks serialize address edits, delivery edits, quote generation and acceptance; shared catalog-pointer locks serialize publication against calculation/acceptance. Optimistic versions reject stale writes. New acceptance checks readiness transactionally after the existing status/expiry/development guards.

Accepted quotes are returned unchanged, including retries after expiration or later catalog/address changes. Order review uses the accepted checkout snapshot, not a recomputed address or price. A W3.2 accepted grading-only quote remains grandfathered; order review exposes `legacy_grading_terms`, no payable total and its historical quote identifier. A supplemental shipping agreement for such historical orders requires a future explicit amendment workflow; this milestone does not silently replace their one-per-submission acceptance.

Submission confirmation, explicit quote acceptance and future payment are distinct. No payment event is created. Checkout navigation remains visibly disabled, including when commercially ready.

## 8. Database migration

Alembic `0005_checkout.py`, parent `0004`, creates `customer_addresses`, `submission_deliveries`, immutable `shipping_configurations`, and singleton `shipping_state` with a null active revision. It adds customer/address indexes, FK protections and version/nonnegative-declared-value constraints. The shipping configuration uses the existing immutable-pricing trigger function. Downgrade removes only W3.3 tables in dependency order. Existing grading/image/entry/quote/acceptance rows are untouched. Upgrade/downgrade is tested in an isolated PostgreSQL schema.

## 9. API endpoints and security

| Method | Endpoint | Behavior |
| --- | --- | --- |
| GET | `/api/addresses` | Own saved addresses, capped at 100 |
| POST | `/api/addresses` | Create, 201 |
| PUT | `/api/addresses/{id}` | Full bounded update with version |
| DELETE | `/api/addresses/{id}` | Delete unused own address with version |
| GET | `/api/submissions/{id}/order-summary` | Authoritative current summary or accepted snapshot |
| PUT | `/api/submissions/{id}/delivery` | Set own address/value/service/parcel with delivery version |

Existing catalog, service-configuration, quote create/list/retrieve and explicit acceptance endpoints remain. Quote acceptance additionally returns 409 `checkout_not_ready` for incomplete commercial orders; historical accepted retries remain valid. Stale contexts return `quote_stale` at acceptance.

All endpoints require verified authenticated customers. Mutations use existing exact-origin/JSON/client-marker/session-bound CSRF guards. Foreign addresses/submissions return 404. Unknown fields, monetary overrides and ownership identifiers are rejected. Private responses are no-store/no-referrer/nosniff and input-validation errors are redacted. No address/phone body logging is added; no internal grading records or image storage are exposed. Personal data resides in the existing database and immutable commercial snapshots; deployment retention/access policies must account for both.

## 10. Frontend and files

Account settings now provide address creation/edit/delete. Submission details provide return selection, declared value, optional parcel fields and configured service selection, live grading breakdown/readiness, selected-address review, inbound instructions and a disabled future payment entry. Quote review includes the snapshotted address/shipping/readiness/payable amount. Acceptance controls appear only for checkout-ready commercial quotes. Unsaved delivery edits disable quote actions. French/English dictionaries remain aligned; existing layouts, input labels, fieldsets, alerts and responsive styles are reused.

Official V2 PNGs are unchanged and all four copies match their originals by SHA-256. Header/footer retain V2; remaining legacy favicon references now use the V2 1272×1272 assets.

Created files:

- `CHECKOUT_PREPARATION.md`
- `backend/alembic/versions/0005_checkout.py`
- `backend/app/checkout_models.py`, `checkout_schemas.py`, `checkout.py`, `checkout_api.py`, `shipping_catalog.py`
- `backend/pricing/spectra-v1.json`, `shipping-unconfigured.json`
- `backend/tests/checkout_fixtures.py`, `test_checkout.py`
- `frontend/src/lib/checkout.ts`, `frontend/src/components/checkout-panel.tsx`, `frontend/tests/checkout.test.mjs`

Modified files:

- `backend/alembic/env.py`, `backend/app/main.py`
- `backend/app/pricing_schemas.py`, `pricing_catalog.py`, `pricing.py`, `pricing_api.py`
- `backend/tests/test_pricing.py`, `test_pricing_concurrency.py`, `test_pricing_migration.py`
- `frontend/next.config.ts`, `frontend/src/app/layout.tsx`
- `frontend/src/lib/submissions.ts`, `pricing.ts`
- `frontend/src/components/account-area.tsx`, `submissions.tsx`, `pricing-panel.tsx`
- `frontend/tests/auth.integration.mjs`, `PRICING.md`

Existing positive W3.2 acceptance tests retain their assertions; their fixtures now supply explicitly synthetic validated tax and delivery configuration. No operational shipping defaults are derived from these fixtures.

## 11. Validation results

Final results are recorded below after execution. Earlier implementation runs exposed schema/encoding/test-boundary errors, which were corrected before the final checks; no failed run is represented as a success.

| Check | Result |
| --- | --- |
| Complete backend suite: `pytest tests -q --basetemp test_tmp_w33_release` | **231 passed, 8 warnings in 22.86s**, exit 0 |
| Complete frontend unit suite: `npm.cmd test` | **32 passed, 0 failed, 0 skipped**, 151.3799 ms, exit 0 |
| ESLint: `npm.cmd run lint` | **Exit 0**, zero warnings |
| TypeScript: `npm.cmd run typecheck` | **Exit 0** |
| Production build: `npm.cmd run build` | **Exit 0**, 16 pages; integration proxy and restored default proxy both built |
| Real production Next proxy + PostgreSQL integration, ports 18033/13033 | **1 passed, 0 failed, 0 skipped**, 2544.9033 ms, exit 0 |
| Pricing CLI validate V1 | **Exit 0**: `Valid document; TAX VALIDATION PENDING - PUBLICATION BLOCKED` |
| Shipping CLI validate unconfigured foundation | **Exit 0**: valid configuration; no rates or services |
| Official V2 asset comparison | **4/4 SHA-256 matches**, no asset changes |
| `git diff --check` | **Exit 0** |

Checks executed on 2026-10-13. The eight backend warnings are the existing Starlette/httpx deprecation and repeated Alembic missing-`path_separator` notices, including the added migration upgrade/downgrade passes. Node reports experimental type stripping; Next reports an ignored external parent-directory package-lock. These notices did not fail checks. The final build uses the default backend destination `http://127.0.0.1:8000`. No browser automation or deployment was performed.

Coverage includes all volume boundaries 1/4/5/9/10/11/20, aggregation, mixed speed/labels, front-label intent, nonstacking, inclusive rounding, tax publication/readiness, CRUD/ISO/phone/privacy/CSRF/auth/ownership, selected-address deletion protection, stale address/delivery versions, missing rates, unsupported destinations, coverage/parcel constraints, immutable shipping/accepted quotes, legacy accepted agreements, and independent-connection concurrent address/delivery/edit/acceptance operations. Existing W2/W3.1/W3.2 assertions and migration regressions remain. Frontend tests cover both dictionaries, declared-value parsing, authenticated proxy/address requests, pending totals and French/English protected account rendering.

## 12. Known limitations

- Actual tax treatment, supported destinations, receiving address, shipping charges and coverage conditions still require operator configuration and validation. Nothing is commercially published by this change.
- Shipping offers are static operator configuration; no live carrier/rating API, package measurement, physical receipt or insurance issuance exists.
- Submitted card configurations remain frozen. Unavailable grading options require a new draft; no reopening workflow is introduced.
- Historical grading-only agreements need a future explicit supplemental delivery agreement before full checkout.
- No payment processor, payment webhook, shipping label, intake, admin UI, grading automation, certificate or slab printing is implemented.
- HTTP integration and SSR language checks do not execute browser hydration. Interactive browser, viewport and assistive-technology QA remain manual; no such checks are claimed.
- No backend lint tool is configured; frontend ESLint is the repository lint check. Existing dependency notices are described with the final results.

## 13. Local testing instructions

Configure backend and frontend using `AUTHENTICATION.md`, `SUBMISSIONS.md` and `PRICING.md`. From `backend`, run `.venv/Scripts/python.exe -m alembic upgrade head`, then start `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`. From `frontend`, run `npm.cmd run dev`. Use a verified local account.

1. Open `/account/settings`, save an international-format return address, edit it and delete a separate unused address. Switch French/English using the existing account language controls.
2. Create a submission with multiple entries/quantities. With the development catalog, review noncommercial example prices; with an operator-validated V1 catalog, verify exact approved brackets and per-card speed/label surcharges. The supplied pending V1 file cannot be published.
3. Select a return address, enter declared value, and save. Without verified shipping configuration, observe pending shipping and null payable total. Do not send physical cards while the receiving address is pending.
4. Generate a quote, edit the selected address or delivery, and verify the previous quote is invalidated. Recalculate. Confirming cards does not accept commercial terms or mark physical receipt.
5. Only in the isolated automated test environment, synthetic coverage/rate/tax fixtures exercise ready quotes, acceptance, historical snapshots and concurrency. For real operation, configure actual validated services with the shipping CLI. Never copy synthetic test offers into production.

Automated commands:

```powershell
# backend; TEST_DATABASE_URL must be a separate PostgreSQL database ending _test
.venv/Scripts/python.exe -m pytest tests -q --basetemp test_tmp_w33_local

# frontend
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

Run HTTP integration separately from backend tests because both temporarily publish catalogs in the test database. Default ports 8000/13000 must be free; for the isolated ports used here:

```powershell
# frontend: bake the integration backend into the production proxy
$env:SPECTRA_BACKEND_URL='http://127.0.0.1:18033'
npm.cmd run build

# repository root
$env:SPECTRA_TEST_BACKEND_PORT='18033'
$env:SPECTRA_TEST_FRONTEND_PORT='13033'
backend/.venv/Scripts/python.exe frontend/tests/run-local-integration.py

# frontend: restore the intended default production proxy afterward
Remove-Item Env:SPECTRA_BACKEND_URL -ErrorAction SilentlyContinue
npm.cmd run build
```

The runner creates a unique verified test customer, publishes only a temporary development catalog in the guarded test database, and cleans up that customer's submissions/addresses and restores the previous pricing pointer. Backend fixtures likewise roll back or clean up synthetic shipping configurations. No development/production commercial catalog is published by validation.
