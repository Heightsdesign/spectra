# SELBY — Customer Return Preparation UX V1 validation

Date: 2026-10-25. Local repository validation only. No deployment, production migration, commercial catalog publication, carrier integration or payment change was performed. This slice requires no migration or new dependency.

## Actual results

| Check | Result |
| --- | --- |
| Backend `.venv/Scripts/python.exe -m pytest -q` | **373 passed**, 22 existing dependency/configuration warnings |
| Backend `.venv/Scripts/python.exe -m pytest tests/test_return_preparation.py tests/test_checkout.py -q` | **33 passed**, 2 existing warnings |
| Frontend `npm.cmd test` | **71 passed** |
| Frontend `npm.cmd run typecheck` | Passed |
| Frontend `npm.cmd run lint` | Passed |
| Frontend `npm.cmd run build` | Passed, Next.js 16.4.0 production build |
| Frontend `node tests/catalog-browser.mjs` | Passed, including customer return preparation plus existing registration/catalog/photo checks |
| Frontend `node tests/admin-browser.mjs` | Passed at desktop and 390px mobile widths, including staff parcel measurements and existing admin workflows |
| `git diff --check` | Passed; existing newline-normalization notices only |

The backend uses the existing PostgreSQL test fixture, which rejects the development database name and requires a separate `_test` database. Its standard migration setup runs against that isolated test database; this change adds no migration. Browser tests use real production Next/Chrome with synthetic HTTP fixtures, not live commercial configuration or real carrier data.

Existing warnings concern Starlette/httpx compatibility, Alembic path separator configuration, Node experimental type stripping and Next ignoring an unrelated lockfile outside the repository. No failed check is reported as a success: the first full backend run caught the new internal endpoints being visible in OpenAPI. They were corrected to use `include_in_schema=False`, matching existing intake conventions; the final full run passed all 373 tests.

## Coverage

### Customer return preparation

- `frontend/tests/checkout.test.mjs`: exact EUR parsing; address/value payloads omit every production measurement even if present in FormData; absent service controls do not send a null/default that erases a saved selection; explicit service changes remain possible; configured service choices filter by selected address country.
- The same tests verify that development data, unresolved tax, missing shipping and incomplete readiness never yield a displayed payable amount. The existing tax-pending/unconfigured shipping documents remain unchanged and are checked by the tests.
- `frontend/tests/catalog-browser.mjs`: real DOM contains no weight/dimension inputs and no empty service selector when unconfigured; address-management link remains; total-card-value explanation is associated with the input; SELBY packing responsibility, development-estimate and pending-tax messages are visible. Selecting an address and entering `1250,50` sends only the delivery version, address ID and `125050` minor units. Reload restores both fields, a previously saved parcel and unavailable service ID remain intact, and the payment button is disabled with no payable amount shown.

### Backend compatibility and restrictions

- `backend/tests/test_return_preparation.py`: existing explicitly supplied parcel records are retained on subsequent customer saves that omit them; omitted service IDs are retained; card declarations stay unchanged.
- Missing service configuration keeps saved customer details while charge/payable remain null and commercial quote acceptance returns `checkout_not_ready`.
- New staff GET/PUT reject nonstaff/anonymous access, reject unconfirmed submissions, preserve existing dimension/weight ranges and strict integer checks, enforce CSRF and optimistic delivery versions, and append a reasoned actor/before/after audit.
- A staff measurement update changes delivery context and invalidates an older unaccepted quote. Existing parcel limits still gate eligibility. Accepted commercial snapshots cannot be changed through either customer or staff preparation writes; snapshot/order reads remain unchanged.
- The complete backend suite retains address CRUD/ownership/version/in-use deletion checks, declared-value coverage and phone rules, unsupported destinations, development quote refusal, tax publication gates, immutable historical acceptance, submission/inspection/custody and Workstation preview-contract regressions.

### Staff/browser regressions

`frontend/tests/admin-browser.mjs` now loads all four measurement fields from the staff endpoint, submits weight/dimensions plus a reason, and verifies the existing session-bound CSRF header at desktop/mobile widths. Existing intake records, 36-card inventory, PDF labels, localized controls, responsive layouts, customer lookup/history, footer navigation, confirmation, idempotent retry and operator restrictions also pass. Screenshots remain under ignored `.visual-review/admin/`.

The customer browser fixture continues to exercise manual registration, optional catalog printings and pagination, photo upload/replacement/removal, failure fallback and confirmation. No card-reference or Workstation identity code was changed.

## Files changed

- `backend/app/checkout_api.py`: preserve omitted customer delivery fields; internal authenticated/audited parcel preparation GET/PUT, reusing existing models/schema/versioning.
- `backend/tests/test_return_preparation.py`: new compatibility, missing-configuration, authorization, audit, eligibility and acceptance-lock tests.
- `frontend/src/components/checkout-panel.tsx`: simplified customer form, destination-filtered services and clear missing-service/packing/value guidance.
- `frontend/src/components/return-parcel-panel.tsx`, `intake-workspace.tsx`: staff parcel preparation fields and save/refresh/locked states.
- `frontend/src/lib/checkout.ts`: FR/EN messages, customer payload projection, service filtering and payable presentation guard.
- `frontend/src/lib/pricing.ts`, `frontend/src/components/pricing-panel.tsx`: pending-tax display/type support and safe payable presentation in quote breakdowns.
- `frontend/tests/checkout.test.mjs`, `catalog-browser.mjs`, `admin-browser.mjs`: corresponding unit and real-browser regressions.
- `SELBY_CUSTOMER_RETURN_PREPARATION_UX_V1.md` and this report: audit, architecture, reference analysis, commercial decisions and validation.

## Local/manual validation

1. Start the existing FastAPI/PostgreSQL/Next setup without changing pricing or shipping configuration. Sign in as a customer and open a submission.
2. In the order summary, verify address selection/address management and the estimated total card value remain. There must be no weight, length, width or height input. Verify the value explanation covers all cards and distinguishes value from grading charges or promised coverage.
3. With shipping unconfigured, verify a clear pending-service explanation replaces the service dropdown. Save an address/value, reload and verify persistence. Existing saved parcel data must not be overwritten by that save. Do not publish test configuration to create a price for this check.
4. In an isolated test environment only, use known configured fixture services to check destination filtering, declared-value/phone/parcel eligibility and quote invalidation. Neither a missing requirement nor development/pending-tax data may become a payable commercial quote. Payment stays unavailable even for complete readiness.
5. Sign in as an operator/admin, open the same submitted declaration in `/admin` or its direct intake detail, and find **Return parcel preparation — staff**. Record measurements with a reason; refresh to verify storage and inspect the intake audit. A plain customer must receive 403 on the staff route. A stale delivery version must fail rather than overwrite.
6. On a separate isolated commercial test fixture, accept a complete quote and verify the staff panel/customer preparation are locked. Changing a saved address or shipping configuration must not rewrite the accepted snapshot. Historical grading-only acceptances must still remain non-payable rather than becoming invented full orders.
7. Check French/English at desktop and narrow widths. Confirm full existing references and UUID URLs are unchanged. Open legacy entries/orders in Workstation Incoming; no short-reference substitution or new local ID mapping should occur.

Reproduce browser checks from `frontend` after `npm.cmd run build` using the two commands in the table. They require local Chrome (`CHROME_PATH` can override the Windows default), use separate local ports/profiles and synthetic data, and clean up their own servers/processes. No new service credentials are needed.

## Limits and decisions still outstanding

- The new staff panel edits the existing **pre-acceptance preparation record**. It is not post-encapsulation fulfillment, dispatch authorization, a carrier rate engine or a way to bypass accepted-term locks. Actual post-acceptance packed measurements require the separate operational shipment boundary described in the architecture audit.
- The current customer portal neither collects nor sends parcel measurements. The legacy delivery API still accepts explicit parcel payloads for compatibility; it was not silently changed into a staff-only API. Old parcel data alone is not proof of operator-measured provenance.
- No estimates for slab/packaging mass, rate bands, service prices, carriers, insurance, compensation limits or delivery times were added. Commercial shipping terms/destinations, coverage evidence, pricing basis, fiscal treatment/references, receiving address and variance handling remain business decisions.
- Existing full `SP-…` references, UUID URLs, audit IDs and independent Workstation ORD/SLB-C identifiers remain unchanged. A shorter customer alias is feasible with separate uniqueness/backfill handling, but is not implemented or silently derived by truncation.
- No live commercial configuration, real carrier quote, payment, dispatch or production-like complete backend/storage/Workstation/browser deployment was validated end to end. No production-readiness claim is made.
