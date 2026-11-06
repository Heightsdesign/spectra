# SELBY V0.5a.2c — validation report

Date: 2026-10-25. Scope: local repository, isolated PostgreSQL test database, production Next build, headless Chrome with a synthetic HTTP backend, and real offscreen PySide6 Workstation tests. No production deployment or production migration was performed.

## Executed checks

| Command | Actual result |
| --- | --- |
| Backend `.venv/Scripts/python.exe -m pytest -q` | **363 passed**, 22 existing deprecation/configuration warnings |
| Backend `.venv/Scripts/python.exe -m pytest tests/test_submission_photos.py tests/test_submissions.py tests/test_tcg_catalog.py -q` | **43 passed**, 2 existing warnings |
| Frontend `npm.cmd test` | **68 passed** |
| Frontend `npm.cmd run typecheck` | Passed |
| Frontend `npm.cmd run lint` | Passed |
| Frontend `npm.cmd run build` | Passed, Next.js 16.4.0 production build |
| Frontend `node tests/catalog-browser.mjs` | Passed against the final production build in Chrome, including real file-input selection and image decoding |
| Workstation `QT_QPA_PLATFORM=offscreen .venv-analysis/Scripts/python.exe -m pytest tests/test_selby_incoming.py tests/test_selby_orders.py -q` | **29 passed**, including actual Qt image preview/disconnect behavior |
| `git diff --check` | Passed; existing CRLF normalization notices only |

The default Workstation `.venv` run initially yielded 23 passed / 6 skipped because PySide6 was absent there. The already available `.venv-analysis` contains PySide6; the Qt-enabled run above exercised all 29 tests without skips. No packages were installed for this change.

Existing warnings concern Starlette/httpx compatibility, Alembic path separator configuration and Next ignoring an unrelated lockfile outside this repository. They did not fail the checks.

## Audit and migration evidence

Inspected existing Next declaration/catalog fields, versioned server drafts, confirmation guard, image validation/exclusive-write helpers, private inspection original reads, authenticated intake detail, role/ownership/CSRF enforcement and Workstation GET-only/background Qt preview contracts before implementation.

Migration **0009**, following 0008, adds only `customer_submission_photos` with copy/side/size checks, private original metadata and a unique active-slot index. Existing submission tables, values and catalog identifiers are not rewritten. Optional expansion/number are a schema/API relaxation to empty strings in existing columns. The repository's test fixture applied migrations only to the isolated PostgreSQL database: its safety checks require a different database name from development and a `_test` suffix. No production migration was applied.

## Coverage

`backend/tests/test_submission_photos.py` verifies:

- Manual declarations with no catalog, expansion or collector number; multiple entries and preserved quantities; successful confirmation with no photos.
- Front/back slots, two independently photographed copies, exact original reads, inferred MIME, hashes, server timestamps, provenance and absence of exposed storage keys.
- Replacement with a new photo UUID, retained prior tombstones, removal and denied reads of inactive originals.
- Frozen confirmed references, rejected confirmed replacement/removal, idempotent confirmation, and photo writes leaving pricing revision unchanged.
- Customer ownership, cross-entry/submission ID rejection, unauthenticated denial, nonstaff denial and authorized staff preview without receiving or reconciling physical cards.
- Malformed base64, invalid filename, fake/corrupt/truncated images, SVG/GIF/TIFF, animated PNG, excessive decoded pixels and oversized bytes.
- Stale versions, CSRF rejection, invalid copy/side, quantity reduction protection and reduction after explicit removal.
- Storage and database failure rollback, cleanup of only the newly written original, intact previous attachments, continued confirmation availability, missing-file errors and hash mismatch detection.

The complete backend suite retains existing authentication, submission conflicts/immutability, pricing, checkout, intake, inspection and Workstation preview-contract regressions. Existing catalog tests were updated to omit read-only photo metadata when constructing entry writes, preserving strict extra-field rejection.

`frontend/tests/submission-photos.test.mjs` covers client format/size validation, private route construction, JSON/CSRF transport, progress, upload errors, timeout and cancellation. Existing catalog and submission state/request tests remain green.

`frontend/tests/catalog-browser.mjs` now verifies manual-first editable/required/optional fields before opting into catalog help. It retains existing catalog printing, pagination, keyboard/mouse, network-error, localization and reset checks. It additionally creates a manual quantity-two entry with empty expansion/number, uses CDP to select a real PNG through the file input, checks a local preview and camera-capture attribute, saves front/back, replaces front, removes back, attaches a separate copy-two front, exercises upload failure without blocking the declaration, reloads/decodes a saved private image and confirms read-only attachment controls. Its fixture routes serve image bytes without text conversion. The browser's backend is synthetic; PostgreSQL endpoint/security tests are separate.

`scanner_agent/tests/test_selby_incoming.py` adds private photo GET, provenance/hash/MIME/size checks, Qt metadata/copy display, actual PNG preview and disconnect clearing. Existing Incoming legacy entries and order tests retain GET-only access, in-memory credentials, expiration/redirect behavior, physical-ID distinctions and `SLB-C-…` numbering. Customer images never enter the local grading store.

## Issues found and corrected during work

An existing catalog test built write payloads from every response field; after additive read-only metadata was introduced, strict payload validation correctly rejected it. The test now projects writable fields. The expanded browser fixture's global select-index assumption broke when photo copy selectors were added; the test now addresses the labeled catalog-language control. The final browser and regression runs passed after those corrections.

Review also removed the old invisible catalog validation prerequisite, guarded quantity reductions involving photographed copies, bounded private reads, protected committed originals from cleanup on a later serialization error, and clears a Workstation image when another photograph is selected so a previous copy's image cannot remain under a new selection.

## Files changed for this slice

| Area | Files |
| --- | --- |
| Backend schema/persistence | `backend/app/submission_schemas.py`, `submission_models.py`, `submissions.py`, `backend/alembic/versions/0009_submission_photos.py` |
| Private photo API and staff reads | `backend/app/submission_photos.py`, `main.py`, `intake.py` |
| Portal | `frontend/src/components/catalog-fields.tsx`, `submissions.tsx`, new `submission-photos.tsx`, `frontend/src/lib/submissions.ts`, new `submission-photos.ts`, `frontend/src/app/globals.css` |
| Workstation | `scanner_agent/selby_workstation/incoming.py`, `incoming_ui.py` |
| Tests | `backend/tests/test_submission_photos.py`, `test_tcg_catalog.py`, `frontend/tests/submission-photos.test.mjs`, `catalog-browser.mjs`, `scanner_agent/tests/test_selby_incoming.py` |
| Documentation | `SELBY_MANUAL_REGISTRATION_PHOTOS_V1.md`, this report |

## Local/manual validation instructions

1. Back up any local data you need. Verify `DATABASE_URL` points to the intended local database, then from `backend` run `.venv/Scripts/python.exe -m alembic upgrade head`. Use the existing private image directory; do not expose it as a static asset directory. Start FastAPI and Next using the repository's normal setup.
2. Sign in as a customer, create a draft and enter only game, card name, language and quantity. Save with blank expansion/number and no catalog interaction. Add another entry and reload; both must persist.
3. Optionally open catalog assistance. Select a known printing, edit a populated field and verify saving remains possible as a manual declaration. Catalog/provider availability must not control manual saving.
4. On a saved quantity-two entry, open optional photos. For copy one choose a JPEG/PNG, verify its local unsaved preview, then save front and back. Switch to copy two and attach a distinct front. Switch back and verify the pairs remain distinct. Test the camera picker on a real phone; browser automation checks only the capture attribute.
5. Replace copy-one front and remove back before confirmation. Reload and verify only the active originals appear. Attempt to reduce quantity below an actively photographed copy: remove that copy's images first, then retry.
6. Try an oversized file, SVG/HEIC or corrupt image. Simulate an upload/storage/network failure and verify that the customer can still save/confirm a manual declaration without optional photos. On uncertain timeout/cancellation, reload to see whether the server already committed before retrying.
7. Sign in as a different customer and request a known photo endpoint; expect denial. Anonymous requests must fail. A customer account without staff membership must not access the staff image route. Do not treat an opaque URL as authorization.
8. Review and confirm a test submission. Image-upload/removal controls must disappear. Reusing draft POST/DELETE requests must return 409. Existing photo bytes, hashes and references must remain identical, including on confirmation retries.
9. Connect Workstation Incoming Submissions using an existing authorized staff session. Select the submitted entry, view each customer photo/copy and verify the separate pre-shipment label. Refresh/select another photo/disconnect and verify the old preview clears. Verify received cards, reconciliation statuses, local order IDs and grading restrictions remain unchanged. Also open a historical submission with no photos.

Reproduce automated browser checks from `frontend` after `npm.cmd run build` with `node tests/catalog-browser.mjs`. It uses ports 18171–18173, `CHROME_PATH` or the default Windows Chrome install, and ignored `.visual-review/catalog-profile` fixture/profile files. Workstation Qt checks can use the existing `.venv-analysis` with `$env:QT_QPA_PLATFORM='offscreen'` in PowerShell.

## Compatibility risks and remaining limits

- Backend code requires migration 0009 before rollout; no production rollout occurred. Strict clients must project writable fields rather than echo the new read-only photo list. Existing clients that omit it continue to work.
- The declared-copy key is an ordinal within an entry, not a received-card identity or proof of which physical card was later sent. No automatic photo-to-received-card mapping or reconciliation rule was added.
- Photos attach to already saved entries. Local unsaved files do not survive reloads and are not included by review/confirmation. Saved drafts/images persist.
- JPEG/PNG only; HEIC/TIFF/GIF/animation are not accepted. Original embedded metadata is retained privately. There is no thumbnail derivative, recognition, compression or automatic format conversion.
- The browser byte limit is 8 MiB; a smaller configured server limit can reject a file the picker initially accepts. Server validation remains authoritative.
- Replaced/removed originals remain private for retention; no purge/quota-management interface is included. Deleting draft-entry metadata can leave unreferenced private files. Retention, backup and large-volume storage planning remain operational work.
- The Workstation's existing bounded JSON preview limit still applies to submissions with extremely large attachment metadata. Full-size original previews can be expensive; large-scale performance is unmeasured.
- Browser checks use a synthetic backend; backend checks use PostgreSQL separately. No full production-like browser → FastAPI → PostgreSQL/storage → Workstation deployment was validated end to end. No real mobile-camera capture, exhaustive accessibility/device review, real customer inventory validation or production-readiness claim is made.
- Future photo recognition is documented as a separate candidate/confidence/customer-confirmation boundary only. No AI provider, inference or recognition storage was introduced, and no photograph/prediction is treated as verified identity, possession or condition.
