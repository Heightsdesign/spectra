# W3.2 — Configurable services and pricing

## Architecture and compatibility

Customer card entries now carry a processing-tier identifier and an array of upgrade identifiers. A quantity represents that many physical cards **with the same configuration**. Separate entries let the customer use different configurations for otherwise identical cards. Configuration is editable only in drafts, including the atomic apply-to-all action.

The catalog is a validated, immutable JSONB document identified by a UUID version. It contains localized tier/upgrade names and descriptions, prices in integer euro cents, availability, ordering, optional localized turnaround text, selection groups and compatibility restrictions. Standard, Express and Priority plus included Classic and paid Detailed labels are provided in the development example. Detailed-label descriptions explain the intended centering/corners/edges/surface presentation; no category grades are generated or altered. New options/groups and discount thresholds require a new configuration document, not a database schema change.

An operator CLI publishes a complete document and atomically updates a singleton current-version pointer. Previous versions remain unchanged. There is no catalog editing API or admin dashboard. Migration does **not** seed commercial or example rates automatically. The supplied example is explicitly development-only, has null turnaround estimates and an example tax treatment. Production refuses development catalogs; commercial acceptance refuses development quotes in every environment. Publishing commercial rates requires `development_only: false` and an operator-supplied `approval_reference`. This field records the operator's approval decision; the application does not verify approval against an external system.

W3.1 confirmation remains draft → submitted and freezes card details. It neither accepts a quote nor pays for anything. Quotes can be generated before or after confirmation, including for submissions confirmed before W3.2. A separate immutable acceptance record can be created only for a submitted submission and a current, unexpired quote from approved rates, with explicit consent. Repeating acceptance of the same quote returns the same record. Only one quote can be accepted per submission. No submitted data or status is rewritten by quoting or acceptance.

A separate `pricing_revision` increments for all draft edits, including notes, entry changes and configuration. Confirmation changes the existing submission version but preserves this pricing revision, so a reviewed quote remains applicable when the customer confirms unchanged cards. W3.1 clients that omit new fields keep their selected options on update. Without a published catalog, legacy implicit Standard/Classic drafts still work; explicit configuration and quoting fail closed. Once a catalog is published, unavailable selections cannot be saved, quoted or newly confirmed.

## Pricing rules

All monetary inputs are bounded integer minor units. All fractional monetary operations use `Decimal`, with `ROUND_HALF_UP` to a whole cent. JavaScript only formats server-provided cents for display.

For each entry:

1. Unit price = configured base grading price + selected speed surcharge + selected upgrade charges.
2. Subtotal = unit price × physical quantity.
3. Count physical quantities across the whole submission for discount eligibility. The eligible rule with the **highest minimum-quantity threshold** wins. Rules do not stack; duplicate thresholds/IDs are rejected. Configuration selects whether the percentage discount applies to base grading charges or all charges.
4. Round the discount **once per entry**, then subtract it from the entry subtotal.
5. For exclusive tax, round `(discounted amount × rate_bps / 10000)` and add it. For inclusive tax, round `(discounted amount × rate_bps / (10000 + rate_bps))` and extract it from the discounted amount. Exempt mode requires rate zero.
6. Sum the rounded line discounts, net amounts, taxes and totals. The displayed total always reconciles to the displayed entries.

Splitting an entry can change its rounded total by a cent; this is intentional entry-level rounding and is covered by a test. Tax treatment is global configuration, not a customer-location tax determination. No external tax calculation or commercial rates have been invented.

## Quote lifecycle and integrity

Every quote stores immutable resolved prices, the configuration document, card descriptions, quantities, selected service/upgrade descriptions, discounts, tax treatment, totals, submission notes, catalog version, pricing revision, creation time and expiry. Timestamps in quote API responses are normalized to UTC.

Quote status is derived without rewriting historical values:

- `valid`: unchanged submission revision, current catalog version and unexpired quote.
- `invalidated`: a draft was edited after the quote.
- `expired`: expiry passed.
- `catalog_changed`: another catalog version was published.
- `accepted`: this quote has the immutable acceptance record; later expiry/catalog changes do not alter its accepted terms.
- `superseded`: another quote for the submission was accepted.
- `unavailable`: a development quote cannot be used in production.

Identical simultaneous quote-generation requests reuse the same still-valid quote. Edits invalidate by revision; catalog publication makes unaccepted older quotes stale, but preserves their original totals. Recalculation creates a new snapshot. Stale or expired quotes cannot be accepted. Accepted terms remain readable and unchanged after price changes and expiration.

Every route uses the existing verified active customer session and server-derived ownership. Mutations reuse Origin/client-header/JSON/session-CSRF checks. Unknown payload fields (including totals, taxes, discounts and ownership) are rejected. Both submission ID and quote/entry ID are scoped server-side. Responses use existing private/no-store handling and never expose internal grading records or original images.

Lock order is customer → submission → shared catalog-state lock. The catalog publisher takes an exclusive catalog-state lock. Submission versions protect stale editing clients; the pricing revision protects quote content. This serializes editing, quote generation, confirmation and acceptance, while publication cannot interleave with an authoritative calculation or acceptance. PostgreSQL triggers reject updates to catalog versions, quote snapshots and acceptance rows. There are no customer deletion endpoints for these records. Database operators remain responsible for retention, access privileges and backups.

## Migration

`0004_pricing.py`, after `0003`:

- Adds `customer_submissions.pricing_revision`, backfilled to 1.
- Adds `customer_submission_entries.processing_tier`, backfilled to `standard`, and JSONB `upgrade_ids`, backfilled to `["classic"]`.
- Adds `pricing_catalogs`, `pricing_state`, `submission_quotes` and `quote_acceptances` with foreign keys, a singleton-state constraint, quote expiry constraint and submission index.
- Adds immutable-update triggers for catalogs, quotes and acceptance rows.
- Seeds only the empty catalog pointer, with no prices or turnaround estimates.

The migration preserves existing customer entry data, quantities, submission status, version and confirmation time, and does not touch internal card/image schemas. A disposable-schema test upgrades W3.1 data, checks the backfill, downgrades and upgrades again. Downgrading to `0003` removes W3.2 pricing/configuration history; keep a backup before considering that operation outside tests.

## API

All routes are under `/api/submissions` and require authentication. Mutations require existing CSRF protection.

| Method | Path | Payload / behavior |
| --- | --- | --- |
| GET | `/catalog` | Current localized catalog and pricing version; 503 if unconfigured/unusable |
| PATCH | `/{id}/configuration` | `{version, processing_tier, upgrade_ids}`; applies atomically to all draft entries |
| PATCH | `/{id}/entries/{entry_id}/configuration` | Same payload; one draft entry |
| POST | `/{id}/quotes` | `{version}`; generate/reuse server quote, HTTP 201 |
| GET | `/{id}/quotes?offset=0&limit=50` | Historical quote list; maximum limit 100 |
| GET | `/{id}/quotes/{quote_id}` | Historical snapshot with current lifecycle status |
| POST | `/{id}/quotes/{quote_id}/accept` | `{version, accept_terms:true}`; explicit approved commercial acceptance, no payment |

Existing POST/PUT entry routes also accept `processing_tier` and `upgrade_ids`. On legacy PUT requests that omit these fields, selected options are preserved. Configuration errors return 422, conflicts/stale quotes/immutable submissions return 409, foreign or missing records return 404. Quote acceptance itself does not increment the submission version.

## Frontend

The existing `/account/submissions/{id}` page now includes:

- Service and label choices while adding/editing an entry.
- Per-entry configuration forms and an apply-to-all form.
- Localized catalog descriptions, availability, prices and explicitly configured turnaround text only.
- A clear explanation that every quantity unit shares its entry's configuration.
- Server-generated quote review with per-card charges, quantity, discounts, tax, totals, dates and pricing version.
- Stale/expired status messages and a recalculation action.
- Explicit acceptance controls for approved quotes on confirmed submissions, with a required consent checkbox.
- A visible payment-unavailable message and separation of confirmation, commercial acceptance and payment.

Unsaved edits disable conflicting actions. Refreshing services discards unsaved configuration choices; submission reload resets unsaved entry changes. Confirmation and acceptance still revalidate server-side. The quote UI hides a prior version while loading a changed submission and fails closed if quote loading fails. Expiry updates in the UI, but the server clock remains authoritative.

FR/EN follows the established typed dictionary pattern. Styles reuse the existing purple/yellow theme tokens and neutral surfaces. V2 logo files and the shared logo component are unchanged in W3.2.

## Files created and modified

Created:

- `backend/app/pricing_models.py`
- `backend/app/pricing_schemas.py`
- `backend/app/pricing.py`
- `backend/app/pricing_api.py`
- `backend/app/pricing_catalog.py`
- `backend/pricing/development-example.json`
- `backend/alembic/versions/0004_pricing.py`
- `backend/tests/test_pricing.py`
- `backend/tests/test_pricing_concurrency.py`
- `backend/tests/test_pricing_migration.py`
- `frontend/src/lib/pricing.ts`
- `frontend/src/components/pricing-panel.tsx`
- `frontend/tests/pricing.test.mjs`
- `PRICING.md`

Modified:

- `backend/app/submission_models.py` — entry choices and pricing revision
- `backend/app/submission_schemas.py` — optional new fields for legacy-compatible entry requests
- `backend/app/submissions.py` — validation, response fields and quote revision invalidation
- `backend/app/main.py` — register pricing routes before the UUID submission route
- `backend/alembic/env.py` — pricing metadata discovery
- `frontend/src/lib/submissions.ts` — typed selections and generic existing request helper
- `frontend/src/components/submissions.tsx` — service controls and quote panel
- `frontend/src/app/globals.css` — responsive pricing display using existing accent tokens
- `frontend/tests/auth.integration.mjs` — retain W2/W3.1 assertions and add W3.2 proxy checks
- `frontend/tests/run-local-integration.py` — temporary example catalog with cleanup/restoration
- `README.md` — link this guide

No dependencies, internal grading/image schemas, payment, shipping, carrier, certification or admin features were added. Existing unrelated working-tree changes are preserved.

## Local testing

Use the existing PostgreSQL/auth setup from `AUTHENTICATION.md`. Do not publish the example to a commercial environment.

From `backend` in PowerShell:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.pricing_catalog validate pricing/development-example.json
.venv/Scripts/python.exe -m app.pricing_catalog publish pricing/development-example.json
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

From `frontend`, run `npm.cmd run dev`. Keep `AUTH_ORIGIN` consistent with that browser origin; `SPECTRA_BACKEND_URL` defaults to `http://127.0.0.1:8000`. Sign into a verified account and open `/account`.

1. Create a draft, add multiple entries and choose different speeds/labels. Use quantity >1 and check the all-units explanation.
2. Apply one configuration to all entries, then customize one entry again.
3. Generate a quote and verify line amounts reconcile with totals. Edit an entry and observe that the old quote becomes invalidated; regenerate it.
4. Review and confirm. Verify that configuration is immutable, the unchanged quote remains valid, and confirmation is not recorded as acceptance or payment.
5. Verify that the example is visibly marked and cannot be accepted commercially. Switch FR/EN.
6. To exercise commercial acceptance locally, use a **separate operator-controlled test document** with test-only values and `development_only:false` plus a test approval reference. This simulates approval for testing; it does not approve real SPECTRA prices. Generate a new quote on a confirmed submission, explicitly accept it, then publish a changed catalog and verify that accepted totals stay unchanged.

For an actual approved commercial catalog, copy the document format, replace all example rates/discounts/tax text with approved settings and record the real approval reference. Leave `estimated_turnaround:null` unless an estimate has been explicitly approved/configured. Validate then publish with the same CLI. A new UUID version is generated every time.

Automated checks:

```powershell
# From backend; TEST_DATABASE_URL must be a separate PostgreSQL database ending in _test.
.venv/Scripts/python.exe -m pytest tests -q --basetemp test_tmp_w32_check

# From frontend, sequentially:
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

For real HTTP integration, after migrating the test database and making a production build, run `backend/.venv/Scripts/python.exe frontend/tests/run-local-integration.py` from the repository root. Default ports 8000/13000 must be free. The runner publishes a temporary development catalog only in the verified test database, preserves the previous catalog pointer, creates a unique customer and removes its submissions/quotes/customer plus the temporary catalog afterward. Run it separately from the backend suite because it temporarily changes test-database catalog state.

For isolated ports used during this milestone:

```powershell
# From frontend:
$env:SPECTRA_BACKEND_URL='http://127.0.0.1:18032'
npm.cmd run build

# From repository root, in the same shell or with these variables set:
$env:SPECTRA_TEST_BACKEND_PORT='18032'
$env:SPECTRA_TEST_FRONTEND_PORT='13032'
backend/.venv/Scripts/python.exe frontend/tests/run-local-integration.py
```

Next bakes the backend destination into its production build. Rebuild with the intended backend URL afterward (remove the temporary `SPECTRA_BACKEND_URL` variable to return to the default). No development database rates were published as part of automated validation.

## Limitations

- No commercial SPECTRA rates, turnaround commitments or tax jurisdiction policy are approved by this implementation. Example commercial acceptance is deliberately blocked.
- Submitted configurations remain frozen. If a service becomes unavailable before an unaccepted quote is generated/accepted, the customer must create a new draft with currently available options; no reopening workflow is introduced.
- One entry has one configuration for all quantity units; split entries for differences.
- The UI reviews the latest/current quote; historical quote pagination is exposed through the API.
- Catalog management is an operator CLI; there is no admin UI.
- No browser automation, screenshots or assistive-technology testing were run. Client interaction and visual viewport QA remain manual.
- Existing dependency warnings (Starlette/httpx, Alembic path separator, Node type stripping and an external package-lock warning from Next) remain unrelated to pricing behavior.

## Exact validation results (2026-10-12)

| Check | Exact result |
| --- | --- |
| Complete backend suite: `.venv/Scripts/python.exe -m pytest tests -q --basetemp test_tmp_w32_final` | **207 passed, 6 warnings in 21.37s** |
| Complete frontend unit suite: `npm.cmd test` | **27 passed, 0 failed, 0 skipped** |
| ESLint: `npm.cmd run lint` | **Exit 0**, zero warnings |
| TypeScript: `npm.cmd run typecheck` | **Exit 0** |
| Production build: `npm.cmd run build` | **Exit 0**, all 16 pages generated, submission details included |
| Real Next production proxy + PostgreSQL integration on ports 18032/13032 | **1 passed, 0 failed, 0 skipped**; includes unchanged W2/W3.1 assertions plus mixed configurations, quantity totals, quotes, invalidation, concurrency and blocked example acceptance |
| Catalog CLI `validate pricing/development-example.json` | **Exit 0**, `Valid catalog; DEVELOPMENT EXAMPLES ONLY` |
| `git diff --check` | **Exit 0** |
| Official V2 PNG comparison | All four `frontend/public/brand/*v2.png` SHA-256 hashes match `imgs/*v2.png` |

Backend coverage includes every initial speed/label combination, mixed quantities, discount thresholds/scope/non-stacking, inclusive/exclusive/exempt tax, half-cent rounding, all mutation invalidations, expiration, historical prices, approved acceptance and retries, immutable-update triggers, unavailable/incompatible/future options, ownership, unauthenticated access, CSRF and forged-price rejection. Independent-connection tests exercise simultaneous configuration updates, quoting versus edits, idempotent quote generation/acceptance and catalog publication versus acceptance. The migration test exercises upgrade/backfill/downgrade/re-upgrade on existing W3.1 data in a disposable test schema.

The six backend warnings are the existing Starlette/httpx deprecation plus repeated Alembic missing-`path_separator` notices from migration runs. Frontend output also contains Node's experimental type-stripping notice and Next's warning about ignoring a package-lock outside this repository. None failed checks. The final production build restores the default backend destination (`http://127.0.0.1:8000`).
# W3.3 update

See [CHECKOUT_PREPARATION.md](CHECKOUT_PREPARATION.md) for approved initial grading amounts, required tax validation, delivery preparation and the strengthened acceptance gate. The W3.2 grading-only commercial-test instructions below are historical; new acceptance requires complete validated shipping and tax information. Historical accepted quotes remain unchanged.

