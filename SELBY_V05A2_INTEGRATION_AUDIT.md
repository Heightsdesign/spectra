# SELBY V0.5a.2 — Existing Portal & Workstation Integration Audit

Date: 2026-10-25. Status: analysis and design only; integration not implemented.

## 1. Existing architecture inventory

**Keep FastAPI as the central backend. PostgreSQL already exists. Neither Django nor a replacement backend/database is justified by the inspected integration requirements.** Keep the desktop SQLite registry and saved grading dossiers in their existing roles.

The repository contains more operational functionality than the initial mission context lists:

| Component | Existing implementation | Persistence / responsibility |
| --- | --- | --- |
| Customer portal | Next.js App Router, React, TypeScript; FR/EN accounts, submissions, pricing and delivery | Calls FastAPI through Next rewrites; no separate frontend database found |
| Central API | FastAPI, SQLAlchemy, psycopg, Alembic | PostgreSQL customer declarations, commercial snapshots, staff intake, physical cards, custody and evidence metadata |
| Staff web tools | `/admin` and `/admin/inspection` | Existing receiving/reconciliation, customer lookup, labels and protected inspection |
| Workstation V0.5a/.1 | PySide6 unified desktop; Orders, Inspection, Grading, Settings | SQLite registry plus saved/versioned JSON dossiers and referenced image/report evidence |
| Originals | Private backend image directory; local scanner/session files | Backend SHA-256 metadata and generated storage keys; desktop pinned saved-session hashes |
| Research | Boundary, centering, frame semantics, physical-reference experiments | Separate research artifacts; outside integration scope |

No existing desktop-to-FastAPI connector, desktop token flow, durable cross-system mapping, incremental change feed, payment implementation, or central commercial `orders` table was found. Backend physical intake, label printing and QR parsing **were** found; they must be reused rather than recreated. Desktop Labels and Scanner navigation remain disabled future features.

Scope: static inspection of the current working tree, models, migration sources, routes, tests and documentation. No live database was queried, no application/registry constructor was run, no migrations were applied, and no test suite was executed. Actual deployed schema revision, database contents, catalog publication, storage availability and production topology remain unverified. PostgreSQL is established by code/configuration and migration features, not by a live server check.

Preservation: the tree already contains extensive staged, unstaged and untracked work, including staged backend inspection migration `0007`, untracked desktop modules and research directories, and a changed PSD. Those files were treated as current audit inputs without staging, resetting, deleting or editing them. This report is the sole intended addition. Git inspection used a command-scoped `safe.directory` exception; no global Git setting was changed. No `AGENTS.md` was found by the repository file search.

## 2. Relevant file paths and documentation

Paths below are repository-relative.

| Area | Primary evidence |
| --- | --- |
| API wiring/config/database | `backend/app/main.py`, `config.py`, `database.py`; `backend/requirements.txt`; `backend/alembic/env.py`, `backend/alembic/versions/0001_cards_and_images.py` through `0007_inspection.py` |
| Customer auth | `backend/app/auth.py`, `auth_schemas.py`, `passwords.py`, `customer_models.py`, `staff_bootstrap.py`; `AUTHENTICATION.md` |
| Submissions | `backend/app/submissions.py`, `submission_models.py`, `submission_schemas.py`; `SUBMISSIONS.md` |
| Commercial/delivery | `backend/app/pricing.py`, `pricing_api.py`, `pricing_models.py`, `checkout.py`, `checkout_api.py`, `checkout_models.py`, pricing/shipping schemas and catalog CLIs; `PRICING.md`, `CHECKOUT_PREPARATION.md` |
| Receiving/identity | `backend/app/intake.py`, `intake_models.py`, `customer_operations.py`, `physical_identity.py`; `INTERNAL_OPERATIONS.md`, `CUSTOMER_OPERATIONS.md` |
| Labels/inspection | `backend/app/physical_labels.py`, `inspection.py`, `inspection_models.py`, `inspection_eligibility.py`, `inspection_commercial.py`; `PHYSICAL_LABELS.md`, `INSPECTION_OPERATIONS.md` |
| Legacy cards/images | `backend/app/cards.py`, `models.py`, `boundary_storage.py`, `boundary_review.py` |
| Portal implementation | `frontend/next.config.ts`, `frontend/package.json`, `frontend/src/app/account/submissions/[id]/page.tsx`, `frontend/src/components/submissions.tsx`, `account-area.tsx`, `inspection-workstation.tsx`; `frontend/src/lib/submissions.ts`, auth/pricing/checkout/intake/inspection helpers |
| Desktop registry/UI | `scanner_agent/selby_workstation/orders.py`, `orders_ui.py`, `desktop.py`, `app.py`, `__main__.py`; `scanner_agent/selby_desktop.pyw`, `Launch_SELBY.vbs` |
| Desktop evidence/grading | `scanner_agent/selby_workstation/session.py`, `grading.py`, `inspection.py`, `condition.py`, `policies/`, authorization JSON files |
| Desktop specifications | `scanner_agent/SELBY_WORKSTATION_V05A.md`, `SELBY_WORKSTATION_V05A1.md` and corresponding `_VALIDATION.md` reports; V0.4 guide/validation |

Documentation is milestone-specific. Root README statements that submissions/payments are outside the current milestone and that the frontend is informational are stale for submissions. `SUBMISSIONS.md` describes W3.1 before W5.1 physical linkage existed. `CHECKOUT_PREPARATION.md` supersedes earlier grading-only acceptance assumptions. Prefer current routes/models and later milestone documents. Historical test counts are recorded results, not validation of this audit or the current tree.

## 3. Existing API endpoints

These are existing routes, not proposed integration endpoints. Identifiers are UUIDs unless a route explicitly takes a reference. Internal intake, inspection and label routes are hidden from generated OpenAPI; absence from `/docs` does not mean absence from the application.

| Namespace | Methods and paths |
| --- | --- |
| Health | `GET /api/health` (availability only) |
| Auth | `POST /api/auth/register`, `/verification/request`, `/verify-email`, `/login`, `/logout`, `/password/change`, `/password/reset/request`, `/password/reset`; `GET /api/auth/me`, `/csrf`; `PATCH /api/auth/profile` |
| Customer submissions | `POST, GET /api/submissions`; `GET, PATCH /api/submissions/{identifier}`; `POST .../{identifier}/entries`; `PUT, DELETE .../{identifier}/entries/{entry_id}`; `POST .../{identifier}/confirm` |
| Pricing | `GET /api/submissions/catalog`; `PATCH /api/submissions/{identifier}/configuration`, `.../entries/{entry_id}/configuration`; `POST, GET .../{identifier}/quotes`; `GET .../{identifier}/quotes/{quote_id}`; `POST .../{identifier}/quotes/{quote_id}/accept` |
| Delivery | `GET, POST /api/addresses`; `PUT, DELETE /api/addresses/{identifier}`; `GET /api/submissions/{identifier}/order-summary`; `PUT .../{identifier}/delivery` |
| Staff intake reads | `GET /internal/intake/me`, `/submissions`, `/submissions/{sid}` |
| Staff intake commands | `POST /internal/intake/submissions/{sid}/parcels`, `/cards`, `/cards/{cid}/match`, `/discrepancies`, `/discrepancies/{did}/resolve`, `/transition` |
| Staff customer tracing | `GET /internal/customer-operations/customers`, `/customers/{identifier}`, `/customers/{identifier}/submissions`, `/cards/{reference}` |
| Staff labels | `GET /internal/labels/cards/{reference}/pdf`, `/calibration/pdf`; `POST /internal/labels/submissions/{sid}/pdf` |
| Staff inspection | `GET /internal/inspection/lookup?reference=...`; `POST /internal/inspection/{reference}/command`, `.../{reference}/images`; `GET .../{reference}/images/{image_id}` |
| Legacy internal grading cards | `POST /api/cards`; `GET /api/cards/{card_id}`; `POST, GET /api/cards/{card_id}/images` |
| Opt-in boundary research review | Under `/internal/boundary`: `POST /images/{image_id}/analyses`; `GET /runs`, `/runs/{run_id}`, `/runs/{run_id}/diagnostics/{name}`, `/images/{image_id}/preview`, `/review`; `POST /runs/{run_id}/reviews` |

Next rewrites proxy auth, submissions, addresses and the four staff namespaces to `SPECTRA_BACKEND_URL` (default loopback port 8000). Legacy `/api/cards` is not included in those rewrites. Its router has no customer/staff authentication dependency; do not use it as a desktop ingestion shortcut or expose it as a trusted operator integration. Boundary review has a separate opt-in loopback restriction.

Authentication uses random opaque session cookies with SHA-256 token hashes persisted centrally, expiry/revocation, active verified customers, and scrypt passwords. Production uses an HttpOnly Secure `__Host-spectra_session` cookie; development uses `spectra_session`. Staff are existing customers with `staff_memberships` (`admin` or `operator`). Writes require JSON, the configured exact Origin, `X-Spectra-Client: 1`, and a session-bound `X-CSRF-Token`. Customer routes scope access by authenticated ownership. Staff routes enforce membership separately. Neither a bearer-token workstation credential nor local operator text is currently a central authenticated identity.

## 4. Current database models and relationships

Central database: PostgreSQL via SQLAlchemy and `postgresql+psycopg`; UUID keys, JSONB snapshots, timezone-aware timestamps, PostgreSQL locking and trigger functions. It is not a SQLite backend waiting for conversion to PostgreSQL.

| Tables | Relationships and semantics |
| --- | --- |
| `customers`, `customer_sessions`, `customer_auth_tokens`, `auth_rate_buckets` | Customer 1:N sessions/tokens; verification/reset token purposes; rate buckets independent |
| `customer_submissions` | UUID PK, unique `SP-<32 uppercase UUID hex>` reference, customer FK, draft/submitted status, notes, optimistic version, pricing revision, timestamps |
| `customer_submission_entries` | UUID PK, submission FK; customer description, game, language, quantity 1–100, tier and upgrade IDs. One row may describe many copies |
| `pricing_catalogs`, `pricing_state` | Versioned JSONB catalog and singleton active pointer |
| `submission_quotes`, `quote_acceptances` | Submission 1:N immutable quote snapshots; at most one acceptance per submission, unique accepted quote FK. Quote binds pricing revision/catalog, expiry and commercial/delivery snapshot |
| `customer_addresses`, `submission_deliveries` | Customer 1:N mutable versioned addresses; submission 0:1 independently versioned delivery record with address, value, service and parcel data |
| `shipping_configurations`, `shipping_state` | Versioned shipping JSONB and active pointer |
| `staff_memberships` | Customer 0:1 role record |
| `submission_intakes` | Submission 0:1 intake state, override reason and timestamps |
| `intake_parcels` | Submission 1:N parcels, unique `PI-<UUID hex>` reference; receiver; per-submission request key/payload for retries |
| `physical_cards` | Submission/parcel FKs, unique `PC-<UUID hex>` reference; nullable declaration-entry FK, nullable unique legacy grading-card FK; received actor/time and request key/payload. Each row is one physical object |
| `intake_discrepancies`, `intake_audit_events` | Submission issues optionally referencing entry/card; kind/quantity/resolution/actors. Audit records action/entity/data/reason |
| `cards`, `card_images` | Separate legacy internal card UUIDs; card only supports `pokemon` and `registered`; originals unique per card/side, SHA-256/size/storage metadata |
| `inspections`, `inspection_custody_events`, `inspection_images` | At most one inspection per physical card; versioned custody state; idempotent custody commands; image uniqueness by inspection/side/version, immutable image metadata and private original storage |

Migration chain: `0001` cards/images → `0002` customers → `0003` submissions → `0004` pricing → `0005` checkout → `0006` intake → `0007` inspection. `0007` and its model/router changes are present in the uncommitted staged work; do not assume it has been applied anywhere. Startup does not apply central migrations.

Immutability has different enforcement levels: submitted declarations reject edits in application routes (no submitted-row immutability trigger found in `0003`); pricing/shipping snapshot triggers reject UPDATE; intake audit and inspection custody/image triggers reject UPDATE/DELETE/TRUNCATE. Do not interpret these protections as protection against every privileged database operation or silently strengthen them during integration.

Local registry: `scanner_agent/local_data/selby_workstation/orders.sqlite3` by default, selectable through desktop Settings. `orders.py` creates schema version 1 with `orders`, `cards`, `audit`; rejects unsupported schema versions rather than migrating them. SQLite transactions use `BEGIN IMMEDIATE`, foreign keys and `synchronous=FULL`. Local evidence resides outside this database.

## 5. Current customer submission lifecycle

1. An active verified customer signs in and creates a persisted empty draft from `/account`. The portal opens `/account/submissions/{id}`.
2. Explicit entry/notes saves immediately persist through FastAPI. Reload restores saved work; unsaved form input is not a durable draft. Maximum 100 entry rows; quantity sums determine card count, potentially 10,000 cards.
3. Mutations carry the current version; customer and owned submission locks serialize changes. Stale edits return 409. Customer-controlled IDs, ownership and status are not accepted as authority.
4. The UI requires saved input before review and warns about immutable confirmation. Confirmation requires a nonempty valid declaration and changes `draft → submitted`, sets confirmation time and increments version. Retry returns the same submitted representation without another transition.
5. Submitted card descriptions/quantities/configuration cannot be reopened by customer editing routes. Delivery preparation remains independently editable until commercial acceptance.
6. Server-generated quotes capture pricing and checkout readiness. Acceptance requires a confirmed submission, valid current non-development quote and complete checkout readiness; repeated acceptance of the same quote is idempotent, another quote conflicts. Accepted snapshots remain historical terms.

**Business meaning:** a Submission is a declaration aggregate with a draft phase and a confirmed phase. It is the existing anchor for commercial agreement and intake, not proof of payment or physical receipt. There is no distinct central commercial order table/state machine. Use its UUID as the integration aggregate key and accepted quote as the commercial agreement; describe commercial state separately. Do not relabel all `submitted` records as paid orders or treat every draft as production work.

## 6. Workstation and existing central receiving lifecycles

Desktop orders receive immutable `ORD-000001`-style IDs from a SQLite autoincrement counter. Cards receive immutable `SLB-C-000001`-style IDs from another registry-wide counter and immutable parent/position. They are unique within that registry, not globally across independently created registries. `external_reference` is free text, mutable and nonunique.

Local order transitions: `draft → received → processing → completed → shipped`; cancellation is allowed from draft/received/processing. Card transitions: `registered → processing → completed`, with cancellation from registered/processing. Completed/shipped/cancelled states have no ordinary outgoing transitions except completed order → shipped. Authorized corrections can bypass transition rules with operator and reason. Adding cards is allowed only to draft/received orders, 1–1000 per transaction. Order and child states are not a derived aggregate enforcing central custody/commercial clearance.

Local triggers prevent identity/parent/position changes, order/card deletion and audit modification/deletion. Events contain before/after snapshots, timestamp, operator text and reason. Ordinary operations can currently have empty operator text; correction authorization uses a local JSON allowlist rather than central staff membership.

Saved grading-session association is explicit: it pins path, SHA-256, session/version IDs and declared card ID, checks saved grading content, prevents sharing a session ID between cards, and verifies evidence when reopening. A different declared `SLB-C-…` is rejected. Replacement/unlink requires authorized correction. Existing session JSON is not rewritten; certification reference is reserved and constrained to NULL.

Central intake already provides the receiving authority:

- Submitted submissions appear in the staff queue; absent intake rows read as `awaiting_receipt`.
- Register parcel → `partially_received`. Hold/resume are available. Beginning reconciliation currently requires an explicit administrator custody override because payment evidence is absent.
- During `reconciliation_pending`, register each physical object, then explicitly match it to an entry. Multiple physical cards may map to the same entry up to its declared quantity. Registration retries use request keys; changed payload for the same key returns 409.
- Missing, unexpected, mismatch, damaged and unresolved issues have separate records. Completion requires no open issues, exact accounting of missing quantities through acknowledged missing issues, and acknowledged qualifying issues for unmatched physical cards. Completion sets intake/parcels reconciled; reconciled intake has no normal reopening path.
- Inspection additionally checks reconciliation, association, discrepancies, accepted quote, payment and commercial restrictions. Production commercial provider returns unverified/restricted by default; inspection mutations fail closed even with intake override. Acknowledged unexpected/mismatched concerns can still block inspection.

## 7. Incompatibilities and risks

| Finding | Integration consequence |
| --- | --- |
| Entry quantity differs from individual physical identity | Never create a received card merely because a declaration has quantity N; stage expected units separately |
| Four identity namespaces: entry UUID, physical UUID/PC, legacy card UUID, local SLB-C | Explicit typed mappings required; `physical_cards.grading_card_id` cannot hold an SLB-C string |
| ORD/SLB counters repeat across registries | Include stable registry UUID and backend-instance identity in mappings and synchronization keys; never renumber existing IDs |
| Local external reference is mutable/nonunique | Useful display/search aid only; insufficient for durable deduplication |
| Local lifecycle differs from central custody/commercial state | No automatic submitted→received, local completed→central reconciled, or shipped→payment transitions |
| Central and desktop inspection both exist | Reuse central custody/eligibility as authority; desktop remains an evidence/grading workbench. Do not create a competing inspection-state authority |
| No payment implementation; catalogs may be unconfigured | Import/preview must not grant processing clearance, assert payment or bypass existing commercial provider |
| No incremental feed; submission version misses child intake changes | Offset pages and submission timestamps cannot provide reliable exactly-once operational synchronization |
| Existing request-key protection is not universal | Parcel/card creation and custody commands have retry support; matching/discrepancy/transition APIs need command-specific replay/concurrency review before offline replay |
| Local creation APIs each commit their own transaction | A naive create-order/add-cards/write-sidecar sequence can leave duplicate or partially linked records after crashes |
| No supported card reparenting | Wrong-order imports require quarantine and explicit reviewed correction, not identity rewrites or moving existing cards |
| Legacy cards accept only Pokémon; submissions support four games | Do not coerce other games through the legacy card API |
| Local operator strings/allowlist are not staff authentication | Remote authority must derive from the server session and membership, not submitted operator names |
| Private originals and local session paths have different access semantics | Never send local absolute paths as central downloadable evidence; preserve original bytes/hashes and use existing storage rules |
| SQLite file copies and registry switching | A registry identity copied with a backup is a replica of the same registry, not a new independent writer; define restore/clone handling before multi-workstation writes |

Local audit is valuable but is not proof of an authenticated central action. Declarations are not a complete operational audit log. Multi-system commits cannot be atomic over HTTP; retries and explicit recovery are mandatory. No current mechanism guarantees that a local offline workflow obeys a subsequently imposed central hold.

## 8. Recommended integration architecture

### Authority and mapping

Keep FastAPI/PostgreSQL authoritative for customers, confirmed declarations, accepted commercial terms, receipt/reconciliation, physical identities, commercial clearance and custody. Keep SQLite authoritative for existing local ORD/SLB-C identities and their local registry history; keep the saved-session engine authoritative for desktop evidence versions and grading dossiers. Local status is a production progress observation, not a commercial or custody command.

Default to one linked local order per confirmed submission per registry. Future partial parcels remain children of the same submission/order. Link an existing manual order when the operator confirms it is the same work; do not blindly create a replacement. Local-only historical orders stay valid and unlinked.

Proposed association data, not existing columns or an implemented schema:

| Association | Required identity / uniqueness |
| --- | --- |
| Registry | Stable registry UUID; backend instance/environment UUID; installation identity separate from registry |
| Order link | Backend instance + submission UUID + registry UUID → existing local ORD; unique in both directions under the chosen one-order policy |
| Expected unit | Submission entry UUID + ordinal 1..quantity, scoped to backend instance; cached immutable declaration snapshot |
| Physical link | Backend physical-card UUID/PC ↔ registry UUID + local SLB-C; unique physical and local assignments within the active registry policy |
| Import receipt | Stable operation UUID, payload/schema version and hash, source revision, operator, timestamp and resulting links |

Expected-unit ordinal is a planning identity, not a physical serial. Central `entry_id` already represents many received copies and need not be replaced. Materialize local individual cards only for actual registered physical objects selected and confirmed by the operator. Missing units have no received SLB-C created automatically. Import unexpected physical cards only into an explicit exception workflow, with no normal processing clearance. If expected placeholders are later desired, approve distinct placeholder semantics first.

For multiple workstations, initially choose one owning registry for each active physical card; other clients may view it. Do not silently permit independent local identities for the same object across writable registries. A central assignment/claim with a unique physical-card key will be needed for that policy once multi-registry import is enabled.

Preserve `SP-`, `PI-`, `PC-`, ORD and SLB-C identifiers exactly. Display them with explicit type labels. `external_reference` may show the SP reference, but the integration link is the UUID association. Never infer matching from customer name, description, row ordering or counters. Importing corrected source metadata must not overwrite saved dossiers or operator grading attributes.

### Authentication

For the first read-only desktop prototype, reuse the existing staff session with a dedicated desktop cookie jar, explicit operator sign-in and server membership checks. Preserve the existing Origin/client-header rules and session-bound CSRF for any future writes. A desktop client can supply these headers; Origin is not proof of device identity. Do not embed passwords, copy browser cookie files, or regard a registry UUID as a credential. Keep sessions in memory initially and require reauthentication after restart/expiry; require HTTPS outside loopback development.

A later dedicated workstation authentication flow may issue short-lived scoped credentials bound to an authenticated staff actor and revocable device registration. It is absent today and requires a separately reviewed design; do not assume OAuth/JWT infrastructure already exists or disable browser protections to accommodate it. Persisted secrets should use OS credential storage, not SQLite audit/notes or session JSON. Server commands always recheck active account, membership and authorization; local allowlists retain only their existing local role.

### Duplicate prevention and transaction boundaries

Use unique database constraints on typed source mappings, not a preflight lookup alone. Repeated import of the same source returns existing links; reuse of an operation key with different data conflicts. Preview must show already linked objects and proposed links before operator confirmation.

Choose an additive integration mapping/journal attached to the existing SQLite registry transaction boundary for the durable import slice, subject to explicit schema approval. Keep orders/cards/audit structures and identity allocation behavior. A narrow transactional import service should allocate local entities, record their existing audit events and commit source links/import receipt in one SQLite transaction. This requires a reviewed service extension, not a persistence rewrite. Merely calling current independently committing methods followed by a JSON/SQLite sidecar write is not crash-safe. If the mapping must live in a separate database, design a recoverable journal protocol and prove each interruption case before use.

Central writes remain separate HTTP transactions. Persist outgoing command identity and state before transmission, then acknowledge the server result durably. A timeout means unknown outcome; replay using the same request key. Never allocate fresh local IDs on retry. Extend idempotency only where necessary and explicitly reviewed; do not pretend existing APIs all support it.

### Synchronization and offline behavior

Start with user-triggered bounded reads using existing queue/detail APIs, fetching central physical-card identities and intake state. During an initial scan, deduplicate by UUID and refresh details before confirmation; concurrent inserts can shift offset pages. Call it refresh, not lossless incremental synchronization. Store no durable cache in the first slice.

For reliable incremental synchronization later, add an authorized server change feed with opaque cursor, transaction-consistent change ordering, full initial snapshot, schema version, and explicit revocation/deletion/hold events. Child card/match/issue/custody changes must advance it. A timestamp alone, intake audit alone, or a sequence number assigned before transaction commit is insufficient to guarantee no missed updates. Define cursor expiration and full resnapshot behavior. Local cursor advances only in the transaction that commits the applied batch. Poll with bounded pages/backoff; reconnect uses overlap/deduplication where appropriate.

After an approved durable cache exists, offline mode may show last successful sync time and stale-state warnings and preserve current local evidence work. It must not assert fresh payment/custody clearance or create authoritative central physical IDs. Initially require online revalidation for imported-card processing handover, reconciliation, custody changes and shipment. Existing local-only workflows remain unchanged; any new integration gating requires explicit review. Later offline commands remain visibly pending, replay with stable IDs, and become conflicts for operator resolution when server state changed; never use last-write-wins for custody, identity or payment.

### Reconciliation, audit and labels

Use existing intake discrepancy/match/transition APIs for central reconciliation. Operator confirms parcel, PC identity, observed card and proposed entry/unit pairing. Missing units retain entry-level missing quantities; extras have physical records and explicit issues; wrong matches use reasoned unmatch/rematch while central state permits it. Closed reconciled intake currently cannot reopen: send corrections to a reviewed exception procedure, not a new hidden bypass. Existing SLB-C parent/position remains immutable when an imported association is wrong; quarantine it for reviewed resolution.

Record actor, registry/device identity, request key, source IDs/version/hash, before/after association, reason, timestamp and central acknowledgement. Retain central intake/custody events and local audit independently, linked by operation IDs. Never describe a queued command as centrally accepted. Require explicit confirmation for linking legacy manual records, disputed physical identity, and corrections. Do not auto-associate old sessions or edit frozen grading/evidence/research files.

Reuse the existing backend label PDF profiles and `physical_identity.py` contract: full `PC-<UUID hex>` or versioned QR payload `SP:PC:1:PC-<UUID hex>`. Keep this prefix compatible despite SELBY branding. Desktop lookup should dispatch explicitly between SLB-C exact IDs, PC references and the existing QR payload, then resolve through mappings. Reject malformed/unknown/ambiguous scans and show the resolved card/order before an action. Do not put names, email, payment data, grades or filesystem paths in QR payloads. Intake labels identify objects, not certificates; local certification remains NULL. Future grade labels can consume accepted presentation snapshots and validated grades through a separately reviewed publication step.

### Are database changes necessary?

**No database engine replacement or new commercial-order schema is necessary for connectivity or read-only preview.** Existing intake, physical cards, discrepancies, labels and immutable quote acceptance already cover the central business anchors.

**Durable automatic import does need additional persisted association/idempotency state somewhere.** Current free-text references and metadata do not provide adequate uniqueness or recovery. Recommend a small approved additive SQLite integration schema/service extension; do not change it during this audit. Central schema additions are not required for a single-registry read-only first slice. They are likely appropriate for cross-registry assignment, dedicated device credentials, durable command receipts or a reliable change feed, depending on the accepted scope. Neither payment tables nor new order tables should be added merely to connect the desktop. Obtain explicit migration authorization before any schema change; existing `0007` is not authorized for application by this audit.

## 9. Proposed minimal vertical implementation slices

All slices below are proposals awaiting audit review, not permission to implement now.

1. **Read-only staff queue and physical-card preview (recommended next step).** Add an isolated FastAPI client and desktop read-only view using existing staff sign-in, `/internal/intake/me`, queue/detail and existing trace/inspection lookup where needed. Show SP, declared quantities, PC cards, discrepancies and explicit commercial/eligibility state. Keep credentials/data in memory. Exercise real existing guards. No local order/card creation, status changes, evidence edits or database migrations. Acceptance: authorized operator sees a submitted record and its physical objects; unauthorized/revoked sessions fail; preview leaves registry and central records unchanged.
2. **Approve identity contract and durable import storage, then operator-confirmed import.** Review schema/transaction plan first and request explicit migration authorization. Import one existing central submission with already registered physical cards into a new or explicitly selected local ORD; retain all SLB-C identities and existing sessions. Prove repeat/restart/concurrency/crash behavior. Start with one registry; no central custody or commercial mutations. Import does not authorize inspection.
3. **Refresh and reconciliation visibility.** Refresh central changes without replacing local evidence; show differences/holds and conflicts, with operator-approved association corrections. Use the existing staff web workflow for authoritative receipt/reconciliation initially. Add desktop commands only after replay and optimistic precondition semantics are approved.
4. **Central assignment/change feed and offline recovery.** Add only the approved additive central/local schema necessary for reliable incremental synchronization and multiple clients. Validate stale holds, cursor gaps, retry conflicts, restore/clone behavior and device/session revocation.
5. **Physical lookup and labels.** Wire existing PC QR parsing and label PDFs into a deliberate desktop workflow, with print calibration/confirmation. Keep grade/certificate publication and payment implementation separate.

## 10. Tests needed to validate integration

Existing test assets inspected include backend `test_submissions.py`, `test_intake.py`, `test_intake_concurrency.py`, `test_inspection.py`, pricing/checkout/auth/card/physical-label/customer-operations suites; frontend `submissions.test.mjs`, intake/inspection/auth/pricing/checkout/label tests plus real HTTP/browser runners; desktop `test_selby_orders.py`, `test_selby_orders_gui.py`, `test_selby_desktop.py` and session/grading tests.

Existing assertions cover persisted drafts, idempotent confirmation, immutable customer edits, stale versions, ownership/CSRF, quantity reconciliation, registration retries, staff revocation, audit immutability, inspection eligibility, local allocation rollback/restart/concurrency, immutable IDs/positions and pinned session association. Review these as regression protection, not a replacement for cross-system tests.

| Slice / risk | Required validation |
| --- | --- |
| Read-only client | Actual cookie login/expiry/revocation, active verified staff roles, customer/nonstaff denial, TLS/origin handling; no secrets in logs; correct base URL/environment handling |
| Preview | Draft excluded; confirmed-but-unpaid explicit; quantities versus entry count; multiple parcels and same-description copies; pagination while queue changes; missing/extra/mismatch display; no writes on success/failure/cancel |
| Mapping | SP/PC/SLB namespaces distinct; N copies → N expected units but only received objects → local cards; manual-order link confirmation; different backend instances; registry switch/restore/clone; no accidental cross-order pairing |
| Idempotent import | Same import twice, concurrent import workers, same key/different payload; failure at every allocation/link/audit/commit boundary; restart after ambiguous result; no orphan unlinked committed entity or duplicated local identity |
| Evidence preservation | Existing ORD/SLB unchanged; saved dossier/image/policy/research hashes unchanged; association rejects another declared SLB-C, shared session, changed/missing evidence; no automatic legacy JSON edits |
| Authority | Import never marks paid/reconciled/received; acknowledged anomalies and commercial holds remain visible; backend inspection still fails closed without trusted payment; local operator string cannot impersonate central staff |
| Synchronization | Child-only updates, same timestamps, transaction commit reordering, duplicate/out-of-order delivery, expired cursor, reconnect/full resnapshot, mid-batch crash, hold/revocation during offline work |
| Commands | Stable retry keys and returned results; rejected stale preconditions; auth revoked before replay; local pending versus accepted distinction; reasoned correction/audit correlation; no cross-submission associations |
| Labels/scanning | Existing QR round trip and plain PC/SLB dispatch, malformed/unknown/environment-mismatched scan, keyboard-wedge whitespace, calibration and PDF profiles; labels contain no PII or certificate claim |

Do not run existing full backend/integration runners as part of an unapproved schema-free audit: `backend/tests/conftest.py` calls Alembic `upgrade head` on the configured dedicated `_test` database. Later execution must explicitly authorize that migration or use an approved already-provisioned fixture strategy. Desktop tests use temporary registries; keep them isolated from real local data. Test results cited in old validation documents remain historical; this audit makes no new passing-test claim.

### Review decision requested by this report

Approve slice 1 as a separate implementation task: an authenticated read-only desktop submission/physical-card preview against the existing FastAPI API, with no schema changes. Review and separately authorize the minimal mapping/journal schema and import transaction design before slice 2. The audit itself authorizes no implementation or migration.
