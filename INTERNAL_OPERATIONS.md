# SPECTRA W5.1 — Internal operations

## Architecture

`/admin` is a dynamic, server-authenticated Next.js staff workspace. It proxies the existing FastAPI application's `/internal/intake` namespace. Every backend handler checks the existing verified, active customer session and a separate `staff_memberships` row. Session authentication establishes identity; membership establishes operational permission. Ordinary account responses contain no staff flag. There is no public `/api/admin` route, customer privilege field, staff registration endpoint or administrative navigation in the customer interface.

This milestone records custody and reconciliation only. Customer submissions and declarations, pricing revisions, accepted quotes and delivery snapshots are read without modification. Existing internal `cards`, image storage, integrity checks and boundary/grading prototypes are unchanged. No payment, carrier API, shipping label, certification number, printing, grading calculation or return-processing operation is introduced. Official V2 assets and the shared logo component are unchanged.

## Data model and migration

Alembic `0006_intake.py` follows head `0005`. Its PostgreSQL DDL is frozen in the migration; upgrades do not import mutable application models. No staff memberships, intake receipts or payment events are seeded.

| Table | Purpose |
| --- | --- |
| `staff_memberships` | Customer FK, `admin` or `operator` role and creation timestamp; absence means non-staff |
| `submission_intakes` | One operational state per submitted submission, optional explicit override reason, creation/update timestamps |
| `intake_parcels` | UUID, unique `PI-<uppercase full UUID hex>` custody reference, submission, receiving actor/time, carrier, tracking, condition notes, status, update timestamp, request key and original request data |
| `physical_cards` | Individual UUID, unique `PC-<uppercase full UUID hex>` tracking reference, submission/parcel FKs, optional declared-entry FK, receiving actor/time, notes/status/update timestamp and idempotency data |
| `intake_discrepancies` | Submission, optional individual card/entry, kind, quantity, notes, open/resolved/acknowledged state, resolution, creating/resolving actors and audit timestamps |
| `intake_audit_events` | Immutable UUID events, actor, optional submission, action, entity UUID, timestamp, bounded operational payload and optional reason |

For parcels and inventory, `received_at` is the immutable creation/intake timestamp; `updated_at` records subsequent state or association changes. PostgreSQL enforces reference uniqueness, request-key uniqueness per submission and entity type, bounded states, positive discrepancy quantities and foreign keys. API checks enforce same-submission links and declared slot capacity. References use the full UUID to avoid shortened-reference collisions; a customer's entry ID is never an inventory identifier. Quantity five requires five individual card-creation operations and five independently traceable records.

`physical_cards.grading_card_id` is a nullable, unique FK reserved for a future explicit association with existing internal grading records. No W5.1 endpoint accepts or populates it. Physical tracking references have their own `PC-` namespace and are not certification numbers.

Upgrade from `backend`:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
```

The migration preserves historical rows. The migration regression test upgrades legacy declarations through `0006`, verifies zero automatic staff/inventory/intake rows, then downgrades through prior milestones. A downgrade removes W5.1 custody/audit history; it is a trusted database maintenance operation, never an application endpoint. Back up before considering a non-test downgrade.

## Staff authorization and first administrator

Both roles may inspect submitted submissions, register parcels, reconcile cards, record/close discrepancies and hold/resume/complete intake. Only `admin` may authorize processing without payment/commercial readiness. Every existing and newly registered customer remains non-staff unless a trusted operator explicitly creates a membership. Registration and profile schemas reject unknown privilege fields. Disabling the underlying account, revoking its session or removing its membership denies subsequent staff requests.

The first administrator is bootstrapped on a trusted application host using its private database configuration. First create a normal account, complete email verification and independently establish that it belongs to the intended operator. Then, from `backend`:

```powershell
.venv/Scripts/python.exe -m app.staff_bootstrap --email operator@example.com --reason "Initial administrator authorization approved by company operator"
```

Replace the example with the existing verified operator's address. The CLI creates no account, chooses no password and emits no secrets. It requires an active verified account, a nonempty bounded reason and **zero existing staff memberships**. A PostgreSQL transaction advisory lock serializes simultaneous bootstrap attempts; exactly one succeeds. Authorization and its audit event commit atomically. All previous sessions for that account are revoked; sign in again and open `/admin` directly.

Database credentials and trusted-host access are the authority for bootstrap; possession of an email address alone is not sufficient. Do not expose this command as a web route, deployment hook taking public input or a customer action. Once any membership exists, bootstrap fails closed. Additional membership administration/recovery is deliberately a trusted database-operator responsibility; there is no staff-management HTTP UI in W5.1. Production should separate migration/owner credentials from the application role, deny audit UPDATE/DELETE/TRUNCATE privileges, protect database backups and restrict who can execute privileged maintenance.

## API

All paths below start with `/internal/intake` and are excluded from public OpenAPI documentation. All require verified active session identity and current staff membership. Every POST additionally requires exact configured Origin, JSON, `X-Spectra-Client: 1` and the session-bound `X-CSRF-Token` from `/api/auth/csrf`.

| Method/path | Body or behavior |
| --- | --- |
| GET `/me` | Staff ID, role and FR/EN language only; used by protected SSR |
| GET `/submissions` | Submitted orders only; `search` reference substring, `status`, `offset`, `limit` (1–100, default 50) |
| GET `/submissions/{submission}` | Declaration quantities, inventory, parcels, discrepancies and ordered audit history |
| POST `/submissions/{submission}/parcels` | `{request_key, carrier?, tracking?, notes?}`; 201 `{id, reference}` |
| POST `/submissions/{submission}/cards` | `{request_key, parcel_id, notes?}`; exactly one individual physical card, 201 `{id, reference}` |
| POST `/submissions/{submission}/cards/{card}/match` | `{entry_id: UUID or null, reason}`; match or explicitly remove association |
| POST `/submissions/{submission}/discrepancies` | `{kind, notes, entry_id?, card_id?, quantity?}` |
| POST `/submissions/{submission}/discrepancies/{issue}/resolve` | `{status: resolved or acknowledged, reason}`; closes an open issue |
| POST `/submissions/{submission}/transition` | `{action: override, begin, hold, resume or complete, reason}` |

Mutations other than parcel/card creation return the current full detail representation. There are no DELETE or audit-edit routes. Unknown payload fields, malformed UUIDs, invalid enums, excessive lengths, noninteger/bool quantities, invalid Unicode and control characters are rejected with redacted 422 responses. Notes/reasons allow ordinary line breaks/tabs. Missing and foreign-scoped entities return 404; absent sessions 401; non-staff or CSRF failures 403; conflicting state/count/idempotency operations 409. Private responses, including failures, use no-store/no-referrer/nosniff.

## Intake lifecycle and commerce

No intake row means `awaiting_receipt`. Only a staff-entered physical receipt creates a parcel. A tracking reference, customer confirmation, quote acceptance or shipping configuration never creates custody records.

| Action | Allowed source | Result |
| --- | --- | --- |
| Register parcel | Awaiting, partial or reconciliation pending | `partially_received`; recorded parcel remains `received` |
| Begin | Partially received, with admin override recorded | `reconciliation_pending`; current parcels become `reconciling` |
| Hold | Any nonfinal state except already held | `on_hold` |
| Resume | On hold | `partially_received` if any parcel exists, otherwise `awaiting_receipt` |
| Complete | Reconciliation pending, all validation rules satisfied | `reconciled`; all parcels become `reconciled` |
| Override | Any nonfinal state; administrator only | State unchanged; authorization reason and immutable event recorded |

`reconciliation_pending` means the staff operator has begun reviewing received material; it does not assert every declared card arrived. Multiple parcels may arrive at different times. Registering another parcel returns the submission to partial receipt and requires another explicit Begin before inventory/matching/discrepancy work continues. Held intake blocks parcel/card creation and reconciliation edits. Final reconciled intake blocks every new change except exact creation retries, which return their existing identifiers without new events.

Physical parcels must remain recordable even if a submitted order has no accepted quote: custody records must reflect an actual arrival. However, **all processing beyond parcel registration requires an explicit administrator override in W5.1**, including commercially accepted orders, because W4 payment evidence does not exist. This conservative gate supports local development and explicitly approved exceptional receiving without inventing payment. The override authorizes custody reconciliation only, persists its reason, and never sets any paid/commercial flag, changes a quote or authorizes grading. Responses report `payment_status: not_implemented`; commercial acceptance is separately derived from its existing immutable row.

## Reconciliation rules

1. Register each received physical card separately in its actual parcel, even if its identity is unknown. Match against the original declared entry only after physical review. Matching beyond that entry's quantity is rejected; extra cards stay individually traceable and can be recorded as unexpected. Matching can be corrected or cleared with a reason before completion.
2. Record missing cards against a declared entry with a positive quantity and **no physical card ID**. Unexpected, mismatched, damaged and unresolved-identification issues require one physical card ID and quantity one. Optional entry links are checked against the same submission.
3. An open issue prevents completion. `resolved` means the operator corrected/investigated the condition; `acknowledged` means an explicitly described remaining discrepancy is accepted for custody reconciliation. Both require a reason and resolving actor. Closed issues cannot be rewritten; record a new issue if later observations require clarification.
4. For **each entry**, matched inventory count plus the sum of **acknowledged missing** quantities must exactly equal its original declared quantity. Resolved missing issues contribute zero: if the card was found, register and match it. Excess or duplicate missing acknowledgements block completion instead of hiding overcounting.
5. Every unlinked physical card requires its own acknowledged unexpected, mismatch or unresolved issue. Merely resolving an identity issue does not establish an unknown card's identity. A damage acknowledgement alone does not account for an unexpected/unidentified card.
6. All issue states must be closed, including damaged/questionable arrivals on matched cards. Completion means receiving discrepancies have been investigated or explicitly accepted for this operational stage; it does not certify authenticity, condition, grading readiness or commercial eligibility.

No rule silently changes customer declarations. Correctly received cards are represented by their explicit declaration matches. Uncertain identification retains the physical UUID, parcel and tracking reference throughout. Damage and identification concerns are retained as linked discrepancy history rather than overwriting declared descriptions.

## Concurrency and idempotency

Lock order is authenticated staff customer, then the target submission (`FOR UPDATE`). All creation, matching, discrepancy and transition writes serialize on the submission, including requests from different operators. Customer commerce still uses its existing locks; intake never locks or updates the submission owner's profile. Transactions commit inventory/state and audit events together; errors roll back together.

Parcel and single-card creation require a client-generated UUID `request_key`, unique per submission and operation type. Same key plus same normalized payload returns the same ID/reference with no extra audit event, including after completion. Same key with different data returns 409. Unique constraints additionally enforce the key at the database boundary. Different keys mean genuinely distinct receiving operations; a tracking number is optional and is never used as a parcel deduplication identifier. Callers must retain the original key for retries after an ambiguous network response.

The frontend retains a creation key for a failed/ambiguous request while that workspace is open. A successful creation clears it so the next physical card receives a new key. Refresh/navigation does not preserve pending form input or retry keys; operators must inspect existing inventory before re-entering an uncertain receipt. Request-level idempotency cannot establish that two differently keyed requests represent the same physical object. Barcode/scanner support and a durable offline receiving queue are future work.

## Audit trail and privacy

Events cover parcel registration, physical-card creation, card-to-declaration changes, discrepancy creation/closure, state transitions, administrator override and bootstrap. Before/after data is recorded for matches, transitions, issue closure and override presence; creation events link immutable generated identifiers. Actor and timestamps are server-derived. Events have no normal write/delete/update API.

A PostgreSQL trigger rejects UPDATE, DELETE **and TRUNCATE**, including direct application SQL. Foreign keys prevent deleting referenced operational submissions or actors. Only privileged schema/owner maintenance can bypass a trigger or drop history; protect those credentials. Audit events are operational evidence, not a cryptographic external ledger.

The dashboard uses opaque customer UUID references, not names, email, telephone or postal addresses. Detail exposes only declaration/custody information needed for receiving. Audit payloads do not copy account profiles, addresses, passwords, sessions, pricing snapshots or original image metadata. Staff must keep free-text notes/reasons operational and avoid unnecessary personal data. Protect the database, access logs and backups; no request-body/session logging is added.

## Local workflow

Use the existing configuration and verified account setup in `AUTHENTICATION.md`, `SUBMISSIONS.md`, `PRICING.md` and `CHECKOUT_PREPARATION.md`. Keep the private `.env` intact. Apply migration head, bootstrap a verified operator, then restart/sign in after session revocation. Start backend on loopback port 8000 with `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, and frontend with `npm.cmd run dev`. Use a matching `AUTH_ORIGIN`; production Next rewrites require the intended backend URL at build time as well as runtime.

Open `/admin`, search a confirmed submission, register each arriving parcel with condition notes, record an administrator override with the actual justification, and Begin reconciliation. Enter one inventory record for each physical card, match reviewed cards, record missing/unexpected/damaged/mismatched/uncertain issues and resolve or acknowledge them. Review declaration counts and issue history, then Complete with a reason. Final inventory and audit history remain available read-only. No payment or shipping setup is fabricated to perform this local test.

The interface offers French and English labels, state/error messages and audit action names; server rendering uses the staff account's language. It reuses the public shell and official V2 logo, contains labelled form fields, keyboard-native controls, live feedback, responsive form grids and horizontally scrollable data tables. Mutations require a browser confirmation; completion explicitly warns that intake freezes. The raw event payload shown on expansion preserves technical field names for audit inspection.

## Validation

Commands from `backend`:

```powershell
.venv/Scripts/python.exe -m pytest tests -q --basetemp test_tmp_w51_local
```

Commands from `frontend`:

```powershell
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

After the build, from the repository root, run these **sequentially**, with backend/frontend ports 8000/13000 free and the build's default backend URL unchanged:

```powershell
backend/.venv/Scripts/python.exe frontend/tests/run-intake-integration.py
backend/.venv/Scripts/python.exe frontend/tests/run-local-integration.py
```

All database tests refuse the development database and require a dedicated PostgreSQL name ending `_test`. Ordinary backend tests roll back their outer transactions. Concurrency/bootstrap tests and the new HTTP runner create uniquely named disposable schemas in that guarded test database, migrate to head, and remove only those schemas afterward. This allows append-only audit validation without disabling audit protection for cleanup. The test database role needs schema/migration permissions. Never run database suites concurrently; prior milestone tests temporarily publish isolated test catalogs.

Results executed on 2026-10-13:

| Check | Exact result |
| --- | --- |
| Full backend suite | 243 passed, 12 warnings in 32.83s, exit 0; `pytest tests -q --basetemp test_tmp_w51_verified` |
| Full frontend suite | 35 passed, 0 failed/skipped, 142.3005 ms, exit 0 |
| ESLint | Exit 0, zero warnings |
| TypeScript | Exit 0 |
| Production build | Exit 0; 17 routes including dynamic `/admin` |
| New real production HTTP intake integration | 1 passed, exit 0; protected FR/EN SSR, customer denial, proxy CSRF, parcel/card retries, matching, completion and audit |
| Existing W2/W3 production HTTP regression | 1 passed, 0 failed/skipped, 2931.3009 ms, exit 0 |
| Whitespace check | `git diff --check`, exit 0 (existing LF/CRLF notices) |
| Official V2 assets | 4/4 public PNGs match original `imgs/` files by SHA-256 |

Backend coverage includes staff/non-staff/unauthenticated/disabled/revoked membership boundaries, forbidden profile and registration privileges, CSRF, input validation, customer ownership isolation, submitted-only access, multi-parcel custody, individual references, quantity-five representation by individual creation semantics, missing/unexpected/mismatched/damaged/uncertain reconciliation, issue resolution/acknowledgement, hold/resume/final transitions, bootstrap, exact retries/conflicts, audit immutability and migration preservation. Independent connections with different staff actors prove concurrent parcel/card retry deduplication, distinct parcels, matching capacity and concurrent first-admin authorization. All existing W2/W3/image/boundary tests remain included.

Frontend unit tests cover FR/EN dictionary parity, internal request routing, CSRF-bound writes, preserved request keys and error propagation. Production HTTP tests exercise backend plus actual Next proxy/SSR; they do not execute browser hydration. Starlette/httpx and Alembic configuration deprecation warnings, Node experimental type stripping and the ignored parent-directory lockfile remain nonfailing dependency notices.

An early intake test incorrectly assumed creation order for rows sharing PostgreSQL transaction timestamps; it now identifies the newly added discrepancy by UUID set difference. A later malformed-Unicode test initially failed in HTTPX encoding before making a request; it now submits escaped JSON so the API validation boundary is actually exercised. Neither failure is counted as a successful run, and no production rule was relaxed to satisfy a test.

## Known limitations

- Browser hydration, visual viewport/device behavior and assistive-technology QA have not been automated or claimed. The HTTP test validates rendered content and network security, not browser interaction.
- No staff invitation/management UI, MFA, fine-grained team assignment, durable receiving queue, barcode labels, physical-object deduplication or editing/deleting custody records. Operators review inventory before retries with new keys.
- Completed reconciliation is final. Late parcels/corrections require a future explicitly audited reopening/amendment workflow; W5.1 refuses them. Open/acknowledged issue history remains visible.
- List endpoints paginate; detail currently returns the whole operational history/inventory for a submission. Large operational volumes need paginated details and query tuning before high-throughput deployment.
- Trusted database operators can alter memberships or disable triggers. Deployment must protect that boundary and separately govern privileged maintenance.
- Existing prototype card/image routes and opt-in loopback boundary review keep their prior access model. The new inventory link is never exposed through those routes. This milestone does not turn the prototype backend into a generally public production service.
- No development/production migration, staff grant or commercial catalog publication was performed by automated validation; migrations and bootstrap were exercised only in the guarded test database. Actual tax, shipping configuration and receiving address remain operator-provided as documented in W3.3.
