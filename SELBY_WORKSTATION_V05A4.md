# SELBY Workstation V0.5a.4 — physical intake and reconciliation

## Follow-up audit and hardening — 2026-10-31

The requested workflow was already present in this working tree. This follow-up inspected its implementation against the current backend, preserved the existing implementation and unrelated staged/unstaged work, renamed the Incoming Orders action to **Start / resume reception…**, and fixed Escape dismissing an intake dialog during an outstanding backend request. Qt calls `reject()` directly for Escape, bypassing the existing close-event guard. The dialog now waits for the worker result before either close path can dismiss it. A regression test blocks an actual worker, sends Escape, then releases it and verifies normal dismissal becomes available.

The native Qt integration test now supports `SELBY_INTAKE_QT_PLATFORM=windows`, asserts the actual platform, and reopens the reconciled order using the same journal. Default automated runs remain offscreen. This is a test against the actual FastAPI application via a loopback HTTP relay and isolated local PostgreSQL transactions; it does not use the separately running development server or existing customer orders.

Additional audit evidence: `backend/alembic/versions/0006_intake.py` installs a PostgreSQL trigger rejecting UPDATE, DELETE and TRUNCATE on intake audit records. Each successful intake write commits the state change and audit together. `app/auth.py` validates an active, email-verified customer and a nonexpired, nonrevoked session; writes check JSON, exact configured Origin, client header and session-derived CSRF. Membership is rechecked by the backend on every intake request. Only override requires the administrator role; both staff roles may match, resolve or acknowledge issues and complete reconciliation under existing policy. Drafts are excluded by `Submission.status == 'submitted'` in both listing and the locked submission lookup used for every mutation.

Adjacent audited APIs, intentionally not invoked by reception: `/internal/labels/cards/{reference}/pdf` (GET), `/internal/labels/submissions/{sid}/pdf` (POST), and `/internal/labels/calibration/pdf` (GET) produce labels under staff authorization. QR parsing uses the full opaque PC identity. `/internal/inspection/lookup` (GET), `/{reference}/command` (POST), `/{reference}/images` (POST), and `/{reference}/images/{image_id}` (GET), all under `/internal/inspection`, manage a separate custody dossier. Inspection commands have request keys and version checks; these do not confer idempotency on intake transitions or discrepancies. Inspection eligibility independently checks intake, associations, discrepancies, quote acceptance, payment and custody state. Reconciliation does not bypass those checks.

**Production linkage remains blocked and incomplete.** The local registry schema is version 1, with immutable order/card identities, immutable card order/position, append-only audit, and a unique grading session association. `external_reference` is mutable arbitrary text without a uniqueness constraint. Neither a backend-origin/registry identity contract nor a uniquely constrained SP/PC → ORD/SLB-C bridge exists. Backend `PhysicalCard.grading_card_id` points to the backend `cards.id` UUID, not to a local card. Safely adopting pre-existing local identities and grading links therefore requires an explicit bridge schema and conflict/adoption rules. This slice creates no ORD/SLB-C identities, changes no grading links, and claims no completed production mapping. Existing confirmed declarations and reconciliation history are preserved.

## Audit and implementation plan

The existing FastAPI `/internal/intake` service is the authority for custody. All writes authenticate an active session, check staff membership, require Origin/client headers and CSRF, lock the confirmed submission row, and append PostgreSQL audit events. Confirmed declaration snapshots are not changed. Existing parcel/card creation accepts a UUID request key scoped uniquely to the submission and rejects reuse with a different payload.

Actual contracts:

| Existing route suffix under `/internal/intake/submissions/{sid}` | Payload and behavior |
| --- | --- |
| GET root | Complete declaration, parcels, physical cards, discrepancies, audit history and commercial flags |
| POST `/parcels` | `request_key`, optional carrier/tracking/notes; creates `PI-…`, changes intake to partially_received; existing request replays before state restrictions |
| POST `/transition` | action + required reason; hold/resume/begin/complete/override; returns detail |
| POST `/cards` | `request_key`, parcel_id, notes; creates exactly one unidentified `PC-…` copy; only in reconciliation_pending |
| POST `/cards/{cid}/match` | entry_id or null + reason; explicit assignment/unassignment; enforces declared quantity capacity |
| POST `/discrepancies` | kind, optional entry_id/card_id, quantity, notes; missing requires entry, all other kinds require one physical card |
| POST `/discrepancies/{did}/resolve` | resolved or acknowledged + reason; only open issues during reconciliation |

State transitions: initial awaiting_receipt; parcel arrival -> partially_received; begin -> reconciliation_pending only after an administrator's explicit operational override; complete -> reconciled only after server validation; hold -> on_hold; resume -> partially_received if parcels exist, otherwise awaiting_receipt. Adding another parcel during reconciliation returns the intake to partially_received, requiring begin again. Reconciled intake cannot be reopened through existing transitions. Receipt is allowed without payment clearance; beginning custody reconciliation requires override, not a payment claim.

Completion rejects open discrepancies. Each declaration's missing quantity must equal acknowledged missing-issue quantities. An unidentified physical card requires an acknowledged unexpected/mismatch/unresolved issue. A resolved missing issue alone does not satisfy missing quantity. Acknowledged exceptions are existing documented backend policy; the GUI must not silently invent matches or mark exceptions as physical receipts.

The backend `PhysicalCard.grading_card_id` references the backend `cards` UUID namespace. The local SQLite registry separately allocates immutable `ORD-…` / `SLB-C-…` identifiers and preserves session links. There is no suitable cross-system mapping contract. This slice defers production import/mapping rather than inferring identity from names or reusing an incompatible FK. No local order/card creation will occur.

Existing QR parsing/physical identity and inspection custody services are separate backend boundaries. Inspection eligibility checks reconciled intake, identified card, commercial evidence and independent payment evidence. An intake override is not payment verification or inspection authorization. This slice does not invoke inspection, change grading evidence or replace QR parsing.

Plan: reuse authenticated sessions in a separate allowlisted CSRF write client; add a technical durable request journal outside the local order registry; integrate an explicitly confirmed operator dialog with background network work; exercise native client/API and GUI contracts; run backend/Workstation regressions. No new backend endpoint or migration is planned. The substantial pre-existing working tree and protected research artifacts must be preserved.

## Delivered architecture

`intake_client.py` is a separate allowlisted write transport; the existing `PreviewClient` remains GET-only. `DesktopAuthService.intake_client()` uses the currently authenticated session in memory. No password, new token scheme, browser cookie extraction or plaintext session storage is added. Existing Windows Credential Manager behavior is preserved. Before each POST the client fetches the existing CSRF token, sends the configured Origin/client headers, disables redirects/ambient proxies and retains TLS validation. Responses are bounded; errors expose only generic messages or known backend conflict codes, not arbitrary response bodies or customer data.

`intake_ui.py` is an explicit modal physical-intake workflow opened from Incoming Orders after selecting a submission. QRunnable/queued Qt results perform all HTTP operations off the main thread. Every mutation requires a confirmation; transitions, matching and discrepancy closure require a decision reason. Ordinary list/detail/photo preview stays read-only. After the dialog closes, Incoming refreshes from the backend. The desktop version is now V0.5a.4.

`intake_journal.py` creates a **separate technical SQLite file**, `scanner_agent/local_data/selby_workstation/intake_requests.sqlite3`. It is not an order registry or a custody database. Its single pending-request table stores origin-scoped submission UUID, operation type/target, bounded UI payload, and request UUID. It stores no sessions, passwords, local order/card IDs or grading data. Pending observations/tracking may contain operational information: protect this local directory under the workstation user's normal file permissions, as with the existing local registry. Successful requests remove their pending row; this is not an archival customer-data cache.

The local journal uses committed SQLite transactions with synchronous FULL and one pending intent per configured backend scope/submission. A creation request is persisted **before** sending the POST; its UUID becomes the existing backend `request_key`. New actions are blocked while an intent is pending. Completion removes only the exact matching intent, preventing a stale callback from clearing a newer request. Disk/journal failure does not become an offline successful receipt. No technical intent is replayed automatically on startup.

No backend source, endpoint, PostgreSQL migration, registry migration or production deployment is needed. The new local journal table is initialized only when the operator opens physical intake. It does not change `orders.sqlite3`, its version, identity sequences or grading-session links.

## Operator workflow

1. Use the existing V0.5a.3 Settings/sign-in workflow. Open Incoming Orders, select a confirmed submission, then **Start / resume reception…**. The dialog loads fresh staff identity and backend detail.
2. Inspect expected entries and quantities. Record optional carrier/tracking and receipt observations; confirm **Record parcel arrival** only for a newly arrived parcel. Each parcel gets the backend's existing `PI-…` identity. Additional parcels are supported. Arrival does not assert any cards have been individually received.
3. If required, an administrator records a reason and confirms **Admin: authorize custody reconciliation**. An operator cannot grant this override. Confirm **Begin / resume reconciliation**. The backend enforces the override gate even if GUI state is stale.
4. Select the correct parcel, enter observations, then confirm **Register ONE physical copy** for each physical object. Each request creates a separate `PC-…`, initially unidentified. A declared quantity of two is not two already-received cards. Creation does not automatically use the selected declaration.
5. Select the actual PC record and the exact declared entry, verify the printing/language physically, enter a reason and confirm the match. The selector includes set/number/language and an entry-ID suffix, so equal names remain distinct. Selecting unidentified explicitly removes a match. The backend prevents overmatching a declaration's quantity.
6. Record missing issues against a declared entry and explicit missing quantity. Unexpected/mismatch/damaged/unresolved issues require an individual PC record and quantity one. Observations are required. Review the issue table and audit, select an open issue, choose **resolved** or **acknowledged**, supply a reason and confirm closure. Acknowledgement is a documented exception, not proof that the declared card arrived.
7. Confirm **Complete reconciliation** with a reason. The backend validates every quantity and discrepancy. The UI displays reconciled custody separately from production linkage and inspection clearance. On-hold and resume use the existing transitions. Already-reconciled submissions are displayed without further write controls.

The screen separates declared quantities, matched copies, quantity not yet matched, received PC inventory, discrepancies and audit history. The unfilled quantity is a comparison aid, not an automatically created missing issue. Selection remains by explicit IDs across refresh. Refresh is safe; network errors disable new mutations until fresh authoritative state is loaded. Local Orders/Inspection/Grading remain separate and usable offline.

## Retries, restart and unknown outcomes

If a parcel/card POST committed but its response or follow-up read was lost, reopening the same submission finds the pending intent. **Retry preserved parcel/card request** resends the original payload and key. The backend returns the same `PI-…`/`PC-…`, including after later state transitions, without another creation audit event. Never register that object again with a new key. Pending creations cannot be discarded through the GUI's manual-review action.

Match, transition, discrepancy creation and resolution endpoints do **not** support request keys. Their uncertain outcomes are never blindly replayed. Refresh, inspect current inventory/issues and the audit history, and explicitly confirm **I reviewed backend inventory/audit — clear pending intent** only after establishing what happened. This removes a local technical intent; it does not undo any backend event. If the operation committed, continue from its recorded result rather than repeating it. Review is disabled until a successful fresh read.

An expired/revoked session preserves pending work and clears protected detail. Close the intake window, sign in again through Incoming Orders and reopen the submission. Resolve backend hold/access/state restrictions before retrying a preserved creation. An irrecoverably invalid creation payload is deliberately not editable/rekeyable in the normal GUI; it requires trusted administrator diagnosis of the pending intent and server state. Do not delete the journal to force another receipt.

The journal is local to this workstation/configured origin. It is not a global identity detector for two operators physically handling the same unlabelled object. Coordinate physical handling and use the visible PC inventory. Different workstations deliberately issuing different keys represent different physical registrations; preventing that human identity error requires the future label/scan workflow. The server's submission lock and unique request keys remain authoritative for concurrent writes and exact retries.

## Production identity boundary and remaining work

There is intentionally **no import/mapping button**. `SP-…`, `PI-…`, `PC-…`, `ORD-…` and `SLB-C-…` namespaces retain their meanings. Existing local `external_reference` is arbitrary text, not a unique backend mapping. Backend `grading_card_id` is not a local `SLB-C-…` string. No identities or existing session links are rewritten, and no mapping is guessed from names.

A future bridge requires an agreed stable local registry identity and an explicit uniquely constrained backend-submission/PC-to-local-order/card mapping contract, with transactional import, repeat/restart handling and validation of existing grading links. Define that contract and migrations separately. Reconciled custody alone must never unlock payment-restricted inspection or grading evidence workflows.

The existing QR contract is `SP:PC:1:PC-<32 hex>` or full `PC-<32 hex>` references through `physical_identity.parse_scan`. This release does not add scanner input, printer/carrier integrations, label generation or inspection custody actions. Next steps are explicit label issuance/reprint audit, scanner lookup through existing backend identity parsing, and reviewed production mapping. Do not use abbreviated/display labels as scanner identity.

## Local setup and validation

No new runtime dependencies. Use the existing `scanner_agent` environment and authenticated local connection from [V0.5a.3 setup](SELBY_WORKSTATION_V05A3.md). Launch `Launch_SELBY.vbs` after closing old application instances. Provide writable local-data storage for the technical request journal. Do not bootstrap arbitrary customers; existing verified operator/admin membership is required. Admin custody authorization uses existing backend policy and does not assert payment.

Automated tests run against isolated test PostgreSQL and temporary files, including a real Qt-dialog-to-FastAPI workflow with synthetic data. They do not receive real customer parcels or establish production readiness. See [validation](SELBY_WORKSTATION_V05A4_VALIDATION.md) for exact commands, results and manual acceptance work.
