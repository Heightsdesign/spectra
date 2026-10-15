# SPECTRA W5.1b — Internal customer operations

## Scope

W5.1b adds a read-only staff customer directory, customer-detail workspace and physical-card lookup. It extends W5.1 intake without grading, payments, carrier integration, labels, profile editing, deletion, account creation, impersonation or role management. Association with a customer account is an operational relationship, not proof of legal card ownership.

## Architecture and migration status

No database migration is required. Alembic remains at **0006 (head)**. Existing relationships provide the complete trace:

```text
PhysicalCard.parcel_id -> Parcel.id
PhysicalCard.submission_id == Parcel.submission_id -> Submission.id
PhysicalCard.entry_id -> SubmissionEntry.id (optional, same submission)
Submission.customer_id -> Customer.id
```

`backend/app/customer_operations.py` defines a separate internal read-only router. Its router-level dependency reuses W5.1 `staff()` and W2 session authentication before validating references or looking up customer records. `main.py` registers the router and applies private response/security headers, including on errors. It is excluded from the public OpenAPI schema.

The frontend uses a shared server-side staff check in `server-staff.ts`, a protected admin layout and navigation, and protected pages. Authentication is checked again by each page. React's request-scoped cache avoids duplicate layout/page checks; it is not a cross-user authentication cache. Personal data is loaded through authenticated, uncached internal APIs. Frontend route protection supplements backend enforcement.

## Routes

| Staff page | Purpose |
| --- | --- |
| `/admin` | Existing W5.1 intake workspace |
| `/admin/customers` | Paginated directory and search |
| `/admin/customers/[customerId]` | Account, saved shipment addresses, paginated submission history |
| `/admin/cards` | Exact physical-card lookup |
| `/admin/submissions/[submissionId]` | Direct URL for the existing intake workspace |

All new API routes are GET-only under `/internal/customer-operations`:

| Endpoint | Result |
| --- | --- |
| `/customers?search=&limit=25&offset=0` | Minimal customer summaries and pagination metadata |
| `/customers/{customerId}` | Allowlisted account fields and bounded saved shipment addresses |
| `/customers/{customerId}/submissions?limit=25&offset=0` | Submission history, quantities, states and return-address provenance |
| `/cards/{reference}` | Card, parcel, submission, declared entry if associated, and customer identity |

The Next proxy preserves the internal namespace. There is no public customer directory endpoint and existing customer submission APIs do not acquire internal `PC-` tracking references.

## Search and pagination

- Customer reference is the existing canonical hyphenated UUID. A valid reference search uses UUID equality, not a partial match.
- Name and email searches are case-insensitive literal substring searches. The name expression uses stored first and last names. Nonempty text searches require 2–254 characters after trimming; control characters are rejected.
- SQL LIKE metacharacters (`%`, `_`) are escaped. They cannot become unrestricted wildcard patterns. SQL values are parameterized.
- Empty search returns a bounded directory page. API page size is 1–50 (default 25); offset is 0–100,000. Both directory and history return `{items, limit, offset, has_more}` without an unrestricted result set or total-count query.
- Directory and history sort by creation date descending, then UUID for deterministic ties. The UI uses 25 records per page, Previous/Next buttons, and resets the page when searching.
- The directory exposes only UUID, first name, last name, email, account status and creation date. Shipment addresses and verification flags are not included in list/search results.

## Customer detail and address provenance

The account schema stores UUID, first/last names, email, email verification, active/disabled status and registration date. There is **no account phone field**. The interface explicitly says so. Phone numbers are displayed only as shipment contact numbers alongside the relevant recipient address.

Saved addresses come from `customer_addresses`, scoped to that customer. The response is bounded to 100 saved addresses (the existing customer API's address limit) and exposes a truncation flag if historical/imported data exceeds that bound. Account contact identity is visually separate from shipment recipient identity.

History includes draft and submitted submissions, creation/confirmation dates, submission state, intake state when available, and summed declared quantities. The SQL quantity expression does not load all card entries into Python. Submitted records link to the existing intake workspace; drafts have no intake action.

Return-address sources are explicit:

| Source | Meaning |
| --- | --- |
| `accepted_snapshot` | Return address copied from the accepted quote's immutable checkout snapshot |
| `current_selection` | Current saved address selected for an unaccepted submission; not a historical snapshot |
| `not_recorded` | Accepted legacy record without a historical return address; the UI does not substitute today's address |
| `null` | No return address selected/recorded |

Only return-address fields are forwarded from snapshot JSON. Pricing, commercial configuration, quote internals and arbitrary JSON keys are excluded. Editing a saved address cannot change the accepted snapshot displayed here. A current address selection is joined only when it belongs to the same customer. No historical snapshots or frozen intake records are modified or recalculated.

## Physical-card lookup

Enter an exact `PC-` reference followed by 32 hexadecimal characters. Input is trimmed and normalized to uppercase. Partial references, wildcard queries, other prefixes and malformed references are rejected.

Lookup returns the physical-card reference/state, parcel reference, submission reference/state, associated declared card information if present, and customer name/email. It supplies customer-profile and intake navigation links. An unidentified physical card can still be traced through its parcel and submission without claiming a declared-entry association.

Before resolving customer identity, the backend checks that the parcel and any associated entry belong to the card's recorded submission. Inconsistent relationships produce `409 trace_inconsistent`; staff should stop and request an operational review. Lookup performs no reassignment or repair. Existing W5.1 matching endpoints retain their submission-scoped checks.

For authorized callers: malformed references return 422; absent customers/cards return 404. Unauthorized callers receive the existing 401/403 staff/session responses before reference validation or entity lookup, including for malformed identifiers.

## Staff permissions and personal data

- Both existing `admin` and `operator` memberships may read customer operations. The acting account must be active, email-verified and have a valid, unrevoked, unexpired W2 session.
- Unauthenticated, disabled/unverified staff and revoked sessions are denied. Ordinary customer accounts and accounts whose staff membership has been removed are denied. Authorization does not depend on frontend visibility or the target customer's status.
- Responses use `Cache-Control: private, no-store`, `Referrer-Policy: no-referrer` and backend `X-Content-Type-Options: nosniff`. Admin HTML is dynamic and uncached; internal API fetches use `cache: no-store`.
- Directory/detail fields are explicitly allowlisted. Password hashes, sessions, authentication/verification/reset tokens and arbitrary quote snapshots are never serialized by these endpoints.
- Customer names/emails/addresses are not automatically copied into intake audit payloads. These reads create no audit event and make no intake, commercial, shipping or customer-account changes.
- URLs for navigation use only record identifiers. Search uses GET query parameters on the internal API; operational HTTP/proxy logs should redact these query strings and must not be shared as if free of personal data.
- No new state-changing API is introduced. Existing W2/W3/W5.1 Origin, CSRF, idempotency, audit and finalization behavior remains in place. No CORS or authorization policy is broadened.

## Operational workflows

1. Open **Clients / Customers** in protected admin navigation. Search by a name, email, or exact customer UUID. Open the name or the customer action.
2. Review account verification/status separately from saved shipment recipients. Use submission history to open a submitted record's intake workspace.
3. Expand a history row's return address to check whether it is a historical accepted snapshot or today's selection. Never treat the latter as the address accepted in a past agreement.
4. From intake detail, use the labeled associated-customer link. Each inventory record also links directly to that customer profile; section navigation and reconciliation controls remain intact.
5. Use **Recherche de carte / Card lookup** for a physical `PC-` reference. Follow the customer or submission link, and compare the associated declared card if present.
6. On an inconsistent trace, do not infer a customer from a conflicting parcel or silently reassign a card. Request an operational review through the existing company process.

## UX and limitations

The UI follows the monochrome operational style and retains the official V2 assets unchanged. Pages support FR/EN, semantic table headers/captions, labeled controls, keyboard focus, responsive page gutters and focusable horizontal table regions. A shared admin language context keeps the protected navigation and page content in the selected language during navigation, initialized from the staff account preference without editing it. Customer names and submission references are links in the first column so mobile staff need not scroll to the final action column. Existing inventory forms remain compact and expandable.

- No account phone, legal ownership record or unsupported profile field is invented. No CRM editing features are provided.
- Only historical return addresses actually stored in accepted checkout snapshots can be displayed. Legacy records may have none. No new carrier/shipping event history is synthesized.
- Pagination uses bounded offsets, not a frozen result snapshot. New registrations/submissions between page requests can shift page boundaries; very large datasets may eventually need indexed text search and cursor pagination.
- Saved-address detail is capped at 100. There is no bulk directory export, fuzzy matching or partial physical-card reference search.
- Browser verification uses synthetic responses; PostgreSQL/HTTP integration exercises the real backend separately. Screen-reader and real staff acceptance of W5.1b remain manual checks. W5.1 receiving/reconciliation regressions remain covered by the existing suite.

## Validation results — 2026-10-14

| Check | Exact result |
| --- | --- |
| New backend directory/traceability tests | **46 passed** |
| Actual Uvicorn-process HTTP/PostgreSQL integration | **1 passed** |
| Full backend suite | **298 passed**, 21 existing dependency deprecation warnings |
| Full frontend suite | **48 passed** |
| ESLint (`npm run lint`) | Passed with zero warnings |
| TypeScript (`npm run typecheck`) | Passed |
| Production Next build (`npm run build`) | Passed; all four new staff pages dynamic |
| Headless Chrome (`npm run test:admin-browser`) | Passed at **1440×1000** and **390×844** |

Backend coverage includes authorization before lookup/validation, non-staff denial, revoked/disabled/unverified staff, removed membership, literal name/email/UUID search, wildcard escaping, bounds and pagination, minimal response fields, address/quote isolation, historical/current/legacy address provenance, card/parcel/entry integrity, unknown/malformed references, no public tracking leakage, and unchanged finalized/audit/commercial/customer records after reads.

The HTTP test launches a fresh Uvicorn process against a uniquely generated schema in the guarded `_test` PostgreSQL database, uses real HTTP requests and disposes only that test schema. The operational database is neither reset nor seeded.

Frontend tests render actual components and verify translations, account/shipment separation, escaping, navigation destinations, snapshot labels, exact reference validation, no-store read requests, localized errors and live empty/loading feedback. Browser coverage exercises directory search and both pagination directions, detail/history rendering, direct submission/customer routes, inventory/customer links, exact/invalid/unknown card lookup, FR/EN, empty/error/retry states, protected navigation, anonymous redirect, admin response headers, and no page-level mobile overflow. The previous 36-card inventory, footer mouse/keyboard navigation, finalization confirmation, CSRF, stable retry keys, frozen controls and operator restrictions are rechecked.

Screenshots are stored locally under `frontend/.visual-review/admin/` (ignored by Git). Reproduce with `npm run build` then `npm run test:admin-browser`; the latter requires installed Chrome (or `CHROME_PATH`) and free local ports 18091–18093. It uses synthetic fixtures and a separate browser profile. Builds may report the existing parent `package-lock.json` warning; tests report Node's experimental type-stripping warning. These do not fail validation.

## Files changed for W5.1b

- `backend/app/customer_operations.py`, `backend/app/main.py`
- `backend/tests/test_customer_operations.py`, `backend/tests/test_customer_operations_http.py`
- `frontend/src/lib/customer-operations.ts`, `frontend/src/lib/server-staff.ts`, `frontend/src/lib/intake.ts`
- `frontend/src/components/customer-operations.tsx`, `frontend/src/components/admin-navigation.tsx`, `frontend/src/components/admin-language.tsx`, `frontend/src/components/intake-workspace.tsx`
- `frontend/src/app/admin/layout.tsx`, `frontend/src/app/admin/page.tsx`
- `frontend/src/app/admin/customers/page.tsx`, `frontend/src/app/admin/customers/[customerId]/page.tsx`
- `frontend/src/app/admin/cards/page.tsx`, `frontend/src/app/admin/submissions/[submissionId]/page.tsx`
- `frontend/src/app/globals.css`, `frontend/next.config.ts`
- `frontend/tests/customer-operations.test.mjs`, `frontend/tests/tsx-render.mjs`, `frontend/tests/admin-ui.test.mjs`, `frontend/tests/admin-browser.mjs`
- `frontend/README.md`, `CUSTOMER_OPERATIONS.md`
