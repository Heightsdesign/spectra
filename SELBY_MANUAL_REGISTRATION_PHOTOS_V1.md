# SELBY V0.5a.2c — manual registration and optional pre-shipment photos

## Audit and scope

Inspected the Next submission form, catalog fields/comboboxes, submission schemas/models/routes, existing image upload helpers in `backend/app/cards.py`, private inspection storage/read conventions in `inspection.py`, authentication/CSRF helpers, intake detail endpoints, migration/test fixtures, and Workstation Incoming preview HTTP/Qt contracts.

The previous form required catalog selection unless a customer selected manual mode. Expansion and collector number were required by the input schema, but no separate pricing, grading or intake business rule required them. They are now optional strings, defaulting to `''`; their existing PostgreSQL columns already support empty strings, so no declaration-table migration is needed.

Existing original-image storage is suitable: decoded-image verification, opaque random keys, exclusive creation with flush/fsync, a private `card_image_dir`, hashes, and guarded original reads. The original card-upload endpoint is not suitable for customer attachments because it targets internal grading cards and lacks customer ownership checks. This version reuses its storage/validation primitives and the authenticated inspection API's JSON/base64 transport pattern. It does not create another storage directory, public file mount, object-store integration or image provider. Customer photos have separate metadata because they are not inspection evidence.

## Customer workflow

New card entries default to manual text. Game, card name, language and the existing quantity range (1–100) are required. Expansion and collector number may be omitted or empty. All declaration fields remain editable even when optional catalog assistance is open. Editing a catalog-populated field clears its catalog reference, preserving an honest manual declaration; selecting a specific catalog printing fills the existing fields and retains its optional UUID.

Catalog search remains available through an optional checkbox. It uses the existing name-first game/language API and optional set filter. No catalog or image request is needed to save a valid manual entry.

Save a card entry first, then open **Customer pre-shipment photos (optional)** on that saved entry. Choose the declared copy number, then attach front and/or back. File selection and a separate mobile-camera input are offered. The browser shows a local preview and explicitly marks it unsaved until **Save photo** succeeds. A file may be replaced or removed while the submission remains a draft. Review and confirmation show saved references only; unsaved local previews are never silently attached. Photos are not required to review or confirm.

Uploads show byte-transfer progress followed by server validation/saving feedback, and may be cancelled. Failures release the form so manual registration can continue. A network interruption/cancellation can be ambiguous if the server already committed; reload to inspect saved references before retrying or confirming. Existing optimistic versions prevent a stale confirmation from silently accepting a concurrently committed attachment. File/preview selections are local component state, not persisted across reloads. Saved drafts and attachments persist in PostgreSQL.

## Declared physical-copy boundary

A specific customer-declared physical copy is identified by **(submission entry UUID, copy number)**. For quantity three, copy numbers are 1, 2 and 3. Each copy has at most one active front and one active back. The front/back images for copy 2 never stand for all three copies. Customers should keep their own physical copies distinguishable when using this feature; a photograph or ordinal does not prove a match to a received card.

This is a declaration identity, not a received physical-card UUID, backend PC reference, or Workstation `SLB-C-…` ID. It does not create physical intake cards or reconciliation matches. Copy numbers remain stable while quantities increase. Reducing quantity below an actively photographed copy is rejected with `photo_quantity_conflict`; remove those attachments explicitly first. Photo-free entries retain existing grouped-quantity behavior.

## Persistence and migration

Migration **0009** follows 0008 and creates only `customer_submission_photos`:

| Field | Purpose |
| --- | --- |
| `id` UUID | Exact original/version reference; each replacement gets a new UUID |
| `entry_id` FK | Saved declaration entry; draft entry deletion cascades its metadata |
| `copy_number`, `side` | Specific declared copy and front/back slot |
| `uploaded_by`, `uploaded_at` | Authenticated uploader and server upload timestamp |
| `removed_at` | Draft replacement/removal tombstone |
| `original_filename`, `mime_type`, `file_size` | Original metadata and decoded media type |
| `sha256`, `storage_key` | Content integrity and private opaque disk key |

Constraints enforce front/back, copy range 1–100, positive size, unique storage keys and one active image per `(entry_id, copy_number, side)` via a partial unique index. Existing entries/confirmed submissions are not rewritten or backfilled; they expose an empty photo list. No AI/recognition, physical-card or catalog tables are added or removed.

Replacement writes a new original and metadata row, marking the previous slot inactive. It does not overwrite bytes or change a prior original's hash, uploader or upload timestamp. Storage/transaction failures roll back the tombstone and clean up only the newly created file. Removed/superseded originals are retained privately, while reads of their inactive IDs return 404. Deleting an entire draft entry cascades its attachment metadata; retained unreferenced files require an operator retention/cleanup policy before large-scale operation. No automated purge is introduced here.

Uploads, removals, entry edits and confirmation all serialize through the existing submission-row lock and optimistic version. Once submitted, attachment changes return 409, including attempted replacement with identical bytes. The active photo UUIDs, copy/side, hash and upload metadata at confirmation are therefore frozen by the same API immutability boundary as declared fields. Originals are served only after checking their byte count/hash. This is application-level immutable evidence referencing, not a claim that a customer photo establishes identity, possession, authenticity or condition.

Photo writes advance the submission version but do not change quantities, services, pricing revision, commercial acceptance or inspection eligibility. No payment, grading, custody, reconciliation or physical-label policy changes were made.

## API, limits and authorization

All customer photo routes live in the existing `/api/submissions` namespace. Mutations use existing session, verified/active-account checks, ownership, Origin/client headers, JSON content type, CSRF and submission version checks. Staff access uses existing operator/admin membership checks and only submitted submissions. Image IDs are scoped to the requested entry/submission; guessing an ID does not bypass ownership.

| Route | Behavior |
| --- | --- |
| `POST /api/submissions/{sid}/entries/{eid}/photos` | JSON `{version, copy_number, side, filename, data}`; `data` is base64; add/replace a draft slot; returns updated submission |
| `DELETE /api/submissions/{sid}/entries/{eid}/photos/{photo_id}` | JSON `{version}`; remove an active draft slot; returns updated submission |
| `GET /api/submissions/{sid}/entries/{eid}/photos/{photo_id}` | Owner-only original bytes, including after confirmation |
| `GET /internal/intake/submissions/{sid}/pre-shipment-photos/{photo_id}` | Staff-only original bytes for a submitted declaration |

Existing customer/intake detail responses add `pre_shipment_photos` per entry. Each metadata object includes its IDs, copy, side, uploader/time, name/type/size/hash, `provenance: customer_pre_shipment`, and `identity_verified: false`. Storage keys and public image URLs are never returned. The GET paths are authenticated private endpoints, not publicly accessible file URLs; responses use `private, no-store`, inline disposition and `nosniff`.

Accepted originals: **single-frame JPEG or PNG, at most min(8 MiB, configured `max_image_size_bytes`), at most 20 million decoded pixels**. GIF, SVG, TIFF, HEIC, animation, malformed base64, invalid filenames, corrupted/truncated data and decompression bombs are rejected. MIME is inferred from decoded bytes, not trusted from an extension or browser header. Originals, including any original embedded metadata, are preserved exactly in the same private directory as existing image storage. Reads are bounded and hash-checked. No recognition, transcoding, image optimization or shared cache is involved.

## Workstation

Incoming Submissions still renders legacy declared entries, received cards and discrepancies using the same IDs/statuses. It now lists customer photo metadata separately and offers a bounded background GET into an in-memory preview. The heading explicitly says **Customer pre-shipment photographs — unverified customer declarations, not SELBY inspection evidence**. No image is imported into local grading storage, no local card is created and no payment/inspection restriction is lifted. Selecting another photo/submission, refreshing or disconnecting clears the preview; existing GET-only, credential-in-memory and redirect protections are reused. Older entries without the metadata field remain supported.

## Future photo-assisted registration boundary

No recognition provider, model, inference pipeline or recognition table is implemented. The current boundary supports it without conflating assertions and predictions:

- Inputs can refer to exact immutable photo UUIDs/hashes and the declared-copy composite key. A result for a replaced image must not be silently reused for the new image.
- Existing declaration fields remain customer-entered/customer-confirmed assertions. A future service must return suggestions separately and must never write directly into a confirmed submission.
- A future response may contain `source_photo_ids`, candidate field values (`name`, `expansion`, `collector_number`, `language`, optional catalog UUID), per-candidate/per-field confidence and explicit confirmation state (`pending`, `accepted`, `rejected`, with actor/time on acceptance). These are a proposed contract, not stored/operational fields in this version.
- Explicit customer acceptance would copy chosen candidate values into the current draft through its existing versioned entry API, reusing catalog consistency checks when appropriate. Pending/rejected candidates remain distinct from the declaration. Confidence is not verification.
- Recognition failure must remain isolated from manual declaration/confirmation, just as optional upload failure is today. The photographs and predictions never automatically become SELBY inspection evidence.

## Local setup and compatibility

Use the repository's existing PostgreSQL/backend environment. Explicitly verify `DATABASE_URL` targets the intended **local development** database before running, from `backend`:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
```

0009 is additive; no production migration or deployment was performed. Use the existing private `card_image_dir` configuration and filesystem permissions; do not expose it through a static web server. Existing Next rewrites/proxy body allowance already cover this JSON/base64 upload size. Start FastAPI and Next normally. No provider credentials or additional packages are required.

Rollout requires backend migration and code before using the new portal upload UI. Older clients/Workstations ignore the additive metadata and continue to work. Strict clients that construct write payloads by echoing every response field must omit read-only `pre_shipment_photos`; the server deliberately refuses client-forged photo metadata. No empty-string rewrite of historical declarations occurs. Rollback of 0009 drops photo metadata and must be preceded by any required metadata/storage backup; it does not delete original files.

Actual tests, manual verification instructions and remaining limits are in `SELBY_MANUAL_REGISTRATION_PHOTOS_V1_VALIDATION.md`. No production-readiness or complete real-device validation claim is made.
