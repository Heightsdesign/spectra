# Personal card library and order assignment — V1

## Repository audit and minimal design

There is no existing persistent customer-owned card-copy identity. `tcg_cards` describes provider printings; `customer_submission_entries` describes one declaration with quantity 1–100; `physical_cards` is the staff-created received PC identity. Local ORD/SLB-C records are a fourth, independent production namespace. Existing SP submissions are draft/submitted only and are suitable as commercial orders. There is no completed/returned customer order lifecycle.

The existing routes already lock submissions, check customer ownership/version, preserve confirmed declarations and invalidate pricing revisions when quantities change. Customer photographs use validated private originals with per-entry/copy slots; staff previews reuse those immutable snapshots. Configuration, quote, address, payment and inspection gates remain authoritative. The working tree contains earlier unrelated work and must be preserved.

Minimal additive schema: customer library copies, historical assignments, and optional library parent on the existing photo model. A partial unique PostgreSQL index on active assignment copy_id prevents duplicate reservation, with copy-row locks serializing competing customer actions. Each new library-backed submission entry has quantity one and an assignment link; existing grouped entries are not rewritten. Removed draft assignments retain history and release the copy. Existing confirmed entries, SP/PC identities and intake mappings remain unchanged. Library edits are blocked while reserved; draft entry identity editing cannot bypass this.

Photographs reuse existing validation/storage and private-response helpers. Assignment clones current library photo originals and provenance into existing submission-photo rows: confirmed evidence remains independent of later library edits. No recognition, proof-of-possession claim or new upload provider is added.

New API families: `/api/library/copies` for owned copies/photos, existing submission routes extended with explicit library registration/selection, and a narrow audited administrator return boundary. There is no inferred automatic release on confirmation, reconciliation or quote acceptance. Migration 0010 was tested against the dedicated PostgreSQL test database before being applied to the verified loopback development database. No production migration or deployment is authorized.

## Schema and identity contracts

`customer_card_copies`: customer owner, immutable UUID (displayed as CC-UUID), optional existing catalog ID, the existing manual declaration fields/notes, version and creation timestamp. Quantity is deliberately absent: one row is one customer-declared physical copy. This is not verified ownership, condition or card identity.

`customer_copy_assignments`: copy UUID, SP submission UUID, optional entry UUID, assignment timestamp and release timestamp/actor/reason. A unique partial index `uq_copy_active_assignment(copy_id) WHERE released_at IS NULL` is the PostgreSQL exclusivity boundary. Entry IDs are unique in assignment history. An active assignment must retain its entry. The entry FK is SET NULL only after an explicit draft release, preserving history when a draft entry is deleted.

`customer_submission_photos`: the existing image record now has an optional customer_copy_id and nullable entry_id; a check requires exactly one parent. A partial index permits one active front/back original per library copy. Existing rows keep their entry parent. The private storage, JPEG/PNG/size/pixel validation, upload metadata and original integrity checks are reused.

No schema changes to PC identities, local SQLite registries, grade evidence or catalog records. No backfill of anonymous grouped entries. The CC identity is not a PC/ORD/SLB-C identity. New receipts on a later SP use the existing per-submission PC workflow and retain the earlier PC as history; the historical assignment links each declaration episode to the same CC. There is no inferred merging of received records.

## API and transaction behavior

All customer endpoints use existing active/verified session authentication, ownership filters, Origin/client-header checks and CSRF. Lists support literal name/set search, bounded page sizes, offset navigation and deterministic timestamp/ID ordering. Missing/foreign copies return 404. Library changes require the copy version and no active assignment.

| Endpoint | Behavior |
| --- | --- |
| GET/POST `/api/library/copies` | List own copies or register one unassigned copy |
| PUT `/api/library/copies/{id}` | Edit an available copy using its version |
| POST `/api/library/copies/{id}/photos` | Optional front/back upload, copy_number=1, version required |
| GET/DELETE `/api/library/copies/{id}/photos/{photo_id}` | Private owner-only read; remove only when available and version matches |
| POST `/api/submissions` | Existing explicit empty draft order creation; unchanged SP identity |
| POST `/api/submissions/{id}/library-copies` | Reserve one copy using copy_id and current order version |
| POST `/api/submissions/{id}/library-register` | Register quantity 1–100 distinct copies and assign them atomically; order version required |
| DELETE `/api/submissions/{id}/entries/{entry}` | Existing draft removal, now also releasing a linked CC reservation |

Assignment locks the owned SP row first, then the owned copy row, verifies availability, creates a quantity-one declaration snapshot and assignment, and commits once. Competing orders serialize on the copy row; the unique index additionally prevents two active reservations. New copies inherit the order's common commercial configuration. Mixed historical per-card exceptions require explicit existing configuration normalization; they are never overwritten. Adding/removing copies increments the existing pricing revision and invalidates stale quotes through existing quote rules.

New order responses advertise `library_enabled: true`; only managed entries gain `owned_copy_id`. Anonymous legacy entries keep their old response shape and quantity semantics. Older server responses without this capability keep the existing portal entry API fallback. The current backend always advertises the feature, including on historical drafts. Existing entry PUT cannot change identification/quantity on a linked copy; remove it first, edit the available library record, then explicitly select it again. Existing configuration APIs still work.

Photo assignment verifies and copies the current library originals into new existing submission-photo records with independent storage keys. Hashes, upload timestamps, uploader and filenames retain provenance; the assignment timestamp records selection time. Failed snapshot creation rolls back the entire assignment and cleans newly written files. Order-specific draft photo changes remain order-specific and do not silently overwrite library originals. Confirmed photos and declaration strings remain immutable, including after later library edits.

## Return and resubmission boundary

The repository has no shipping-complete/returned lifecycle. This slice adds only:

`POST /internal/intake/submissions/{sid}/library-copies/{copy_id}/return` with an explicit nonempty reason.

An authenticated **admin** must attest an actual physical return. The backend requires reconciled intake, exactly one matched PC for that entry, no backend grading-card link and **no inspection dossier**. Drafts, unreceived/unreconciled copies, operators/customers, inspected copies and grading-linked copies cannot use this release. The action sets the assignment's release metadata and appends `customer_copy_returned` to the existing audit history. Retrying the same historical return is idempotent and never releases a newer order's assignment. Confirmed SP snapshots and PC records remain unchanged. An additional custody eligibility denial prevents the historical returned PC from later starting inspection.

This is an explicit administrative API, not an automatic status inference or new customer button. The existing authenticated staff API tooling can invoke it; no separate admin return screen is introduced. A full graded-card return/shipping lifecycle remains required before releasing copies that entered inspection/production. Payment and other existing inspection restrictions are preserved; return does not assert inspection or commercial clearance.

## Portal workflow

The account page exposes **My Cards / Mes cartes** and **My Orders / Mes commandes** using the existing design system. My Cards registers or edits one available copy with manual fields, optional catalog assistance and private front/back photos. It creates no SP automatically. Equal printings remain separate CC records; availability and the current order link are visible. Search and Load more navigate all owned records.

Create order explicitly creates a zero-card SP draft. Its existing detail page offers Register new copies, Choose from my cards, explicit draft Remove, selected CC references, and Continue to configuration and quote. Quantity creates that many independently identified copies. Reserved rows cannot be selected; stale races are rejected server-side. Refresh restores saved selections from PostgreSQL. Existing order-wide configuration, notes, address, quote, confirmation and payment restrictions remain in place. No local production IDs are allocated.

## Migration and local activation

Revision `0010`, parent `0009`, is additive except making the photo entry parent nullable under the new exactly-one-parent constraint. Existing rows and IDs are not rewritten. Back up the database and private original-image directory before any future rollout. Apply schema before running the new application code:

```powershell
# backend directory, approved local development database only
.venv/Scripts/python.exe -m alembic upgrade head
```

For this task, development authentication, the local allowed spectra database, loopback PostgreSQL server and current revision were verified first. The local development database was upgraded 0009 → 0010. Hashes of all original columns/rows in customers, submissions, entries, customer photos, PC records, intake and inspections were identical before/after; both new tables remained empty. No customer cards/orders were created as migration fixtures, and no production database was accessed.

Restart the existing local FastAPI and Next processes if they are not running with reload. The portal rewrite now includes `/api/library`; the production build succeeded. Existing fictional accounts can be used manually; their ignored credentials document is unchanged. Tests use isolated `_test` data and temporary private image storage.

Automatic downgrade deliberately refuses: dropping library data or confirmed photo history would be unsafe. A rollback requires an approved data-preservation/restore plan; do not blindly drop the new tables. Do not roll old anonymous order-editing code over live library assignments without a maintenance plan.

## Limits

Exclusivity applies to the persistent CC identifier. Neither a card name, a shared catalog printing nor an unverified photograph can detect a person registering the same object twice under different IDs. Existing anonymous declarations are not automatically converted, deduplicated or merged. No archive/delete-copy operation, bulk assignment selection or automatic real-customer data conversion is added. The library is paginated and bounded but has not been profiled at production scale. Photo snapshots duplicate private originals per assignment; storage capacity and an archival policy remain operational considerations. Future graded returns need the outbound custody/shipping lifecycle. See the validation report and manual acceptance procedure before deployment.

After an uncertain standalone registration response, reload/search the library before declaring another copy; standalone creation does not introduce a new request-key protocol. Order registration/assignment uses the existing SP version lock, so repeating a successful write with the old version is rejected instead of adding duplicates. Confirmed-but-never-received cancellation also needs a future explicit lifecycle decision; it is not inferred from lack of a parcel.
