# W3.1 — Customer submissions

Customer submissions are independent of internal grading cards/images. Existing authentication requires an active, verified account; this workflow reuses its HttpOnly session, Origin/client header guard and session-bound CSRF token. No customer ownership, price or status field is accepted from the client. Unknown payload fields are rejected.

## Data and concurrency

Alembic `0003` (after `0002`) creates `customer_submissions` and `customer_submission_entries`, indexed by customer/submission. UUID IDs and unique `SP-<uppercase UUID hex>` references are generated server-side. Submission notes, timestamps, confirmation time and a monotonically increasing version are persisted. Card count sums quantities, not entry rows.

Games are an application catalog (`pokemon`, `one-piece`, `dragon-ball`, `naruto`), not a database enum or check. Extending the catalog and frontend labels requires no database migration. Status transitions are an application map; currently only draft → submitted is allowed. No operational statuses are implemented.

Every mutation locks the authenticated customer using the existing authentication helper, then the owned submission using PostgreSQL `FOR UPDATE`. All edit and confirmation requests carry the version from their most recent response. Stale drafts return 409 `submission_conflict`. Child lookup includes the parent submission ID. Confirmation checks for at least one entry and atomically writes status, timestamp and version in the same transaction. A repeated confirmation returns the existing submitted representation without changing timestamps or version. Submitted records reject every customer editing endpoint with 409.

Limits: 100 entry rows per submission, quantity 1–100 per entry, names/sets 200 characters, game/number/language 64, notes 2,000. Text is trimmed, encoding checked and control characters rejected (notes allow newlines/tabs). Quantity and version require strict integers. Lists use bounded offset/limit pagination (default 50, maximum 100).

Future grading linkage should use a separate association from an internal physical card record to `customer_submission_entries.id`, with a unit index where quantity exceeds one. Keep the submitted customer description as an intake snapshot, with separate internal grading attributes. No linkage or grading workflow is created in W3.1.

## API

All routes require the existing customer session. Mutations additionally require JSON, configured Origin, `X-Spectra-Client: 1` and `X-CSRF-Token` from `/api/auth/csrf`.

| Method | Route | Body |
| --- | --- | --- |
| POST | `/api/submissions` | `{}` |
| GET | `/api/submissions?offset=0&limit=50` | — |
| GET | `/api/submissions/{id}` | — |
| PATCH | `/api/submissions/{id}` | `{version, notes}` |
| POST | `/api/submissions/{id}/entries` | `{version, game, card_name, expansion, card_number, language, quantity, notes}` |
| PUT | `/api/submissions/{id}/entries/{entry_id}` | Same complete entry payload |
| DELETE | `/api/submissions/{id}/entries/{entry_id}` | `{version}` |
| POST | `/api/submissions/{id}/confirm` | `{version}` |

Creation returns 201; other mutations return the complete updated submission (adding an entry returns 201). Foreign/missing IDs return 404. Private responses use no-store; validation errors omit submitted input. Responses never include internal cards/images, session secrets or customer ownership fields.

## Frontend

`/account` lists references, quantity totals, translated status and localized creation dates, with a New submission button and pagination. This action creates a persisted empty draft and opens `/account/submissions/{id}`. Cards can be added, edited and removed; each successful action saves immediately. Submission-level notes are saved separately. Unsaved card or notes changes disable review; save or explicitly reload/cancel first. Review shows every saved entry and submission notes, with an explicit immutable-confirmation warning. Submitted details provide read-only entries. Errors, loading states and empty states are translated through the existing FR/EN dictionary pattern. Dashboard language follows the existing selector; detail pages include their own selector.

The shared logo component references the original official V2 PNGs. Public copies have matching SHA-256 hashes to `imgs/`. Intrinsic dimensions and transparent-margin display bounds match V2; no image assets were modified or recolored.

## Files

Created:
- `backend/app/submission_models.py`
- `backend/app/submission_schemas.py`
- `backend/app/submissions.py`
- `backend/alembic/versions/0003_submissions.py`
- `backend/tests/test_submissions.py`
- `frontend/src/lib/submissions.ts`
- `frontend/src/components/submissions.tsx`
- `frontend/src/app/account/submissions/[id]/page.tsx`
- `frontend/tests/submissions.test.mjs`
- `SUBMISSIONS.md`

Modified:
- `backend/app/main.py` — router registration and private response/validation handling
- `backend/alembic/env.py` — model metadata discovery
- `frontend/next.config.ts` — submission API proxy
- `frontend/src/components/account-area.tsx` — dashboard workflow
- `frontend/src/components/brand-logo.tsx` — official V2 files and dimensions
- `frontend/src/lib/i18n.ts` — remove outdated submission-unavailable messages
- `frontend/src/app/globals.css` — responsive submission forms and V2 display bounds
- `frontend/tests/auth.integration.mjs` — real HTTP submission tests and concurrency races
- `frontend/tests/run-local-integration.py` — isolated configurable ports and test-submission cleanup

Existing working-tree changes were preserved. No payment, shipping, admin, grading, certification or image schemas were added or changed.

## Local use

1. Configure PostgreSQL in `backend/.env` as described in `AUTHENTICATION.md`. `TEST_DATABASE_URL` must point to a separate database ending in `_test`. Existing dependencies are sufficient.
2. In `backend`, run `.venv/Scripts/python.exe -m alembic upgrade head`, then `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
3. In `frontend`, run `npm.cmd run dev`. Ensure `AUTH_ORIGIN` matches the frontend origin and `SPECTRA_BACKEND_URL` points to the backend (default `http://127.0.0.1:8000`). Register, verify using the configured email delivery, and sign in.
4. Open `/account`, create a submission, save several cards, reload to check persistence, edit/delete entries, save notes, review and confirm. Reopen the details to verify editing controls are absent. Switch FR/EN using the language selector.
5. Backend suite: from `backend`, `.venv/Scripts/python.exe -m pytest tests -q --basetemp test_tmp_w31_check` (use a fresh temporary name if directory permissions differ).
6. Frontend suite: from `frontend`, `npm.cmd test`, `npm.cmd run lint`, `npm.cmd run typecheck`, `npm.cmd run build`.
7. Real HTTP integration: after a production build, run `backend/.venv/Scripts/python.exe frontend/tests/run-local-integration.py` from the repository root. Ports 8000 and 13000 must be free. For alternative ports, build with `SPECTRA_BACKEND_URL=http://127.0.0.1:18031`, then run the runner with `SPECTRA_TEST_BACKEND_PORT=18031` and `SPECTRA_TEST_FRONTEND_PORT=13031`. Backend destination is baked into the Next production build; rebuild with your intended URL afterward.

## Validation scope and limitations

Backend tests exercise PostgreSQL migration/application integration, persistence, all editing operations, ownership, unauthenticated access, CSRF, immutable submissions, validation, stale versions, supported games and the entry cap. Frontend unit tests exercise FR/EN message coverage and CSRF/request/error behavior. The real Next production-server integration checks FR/EN protected page output, submission proxy operations, simultaneous stale edits, editing versus confirmation, concurrent repeated confirmation and the unchanged W2 authentication flow.

No browser automation or visual viewport checks were run; client interactions and responsive visual appearance still need browser QA. Language and card numbers are bounded customer-entered text, not a card-catalog lookup. Saving is explicit; unsaved input is not persisted across navigation. References use the complete UUID to preserve uniqueness without a database sequence. Read requests inherit the existing account lock, which serializes requests per customer; revisit this if account traffic requires higher concurrency. No additional backend lint configuration exists; frontend ESLint is the repository lint check. Known dependency warnings are recorded in the final test results below.

## Exact results (2026-10-12)

- Backend full suite: `.venv/Scripts/python.exe -m pytest tests -q --basetemp test_tmp_w31_release` — **160 passed, 2 warnings in 20.05s**. Migration 0003 was applied by the test fixture to the separate PostgreSQL test database.
- Frontend full unit suite: `npm.cmd test` — **15 passed, 0 failed, 0 skipped**.
- Frontend ESLint: `npm.cmd run lint` — **exit 0**, zero warnings.
- TypeScript: `npm.cmd run typecheck` — **exit 0**.
- Production: `npm.cmd run build` — **exit 0**; account submission detail route included.
- Real HTTP integration with isolated ports 18031/13031: **1 passed, 0 failed, 0 skipped**. Includes the existing W2 assertions plus submission persistence, FR/EN protected output and concurrent edits/confirmation.
- Existing warnings: Starlette/httpx deprecation, Alembic missing `path_separator`, Node experimental type stripping and Next ignoring a package-lock outside this repository. None failed the checks.
- An initial pytest invocation from the repository root failed collection; rerunning from `backend` with the configured test directory resolved it. The default HTTP integration ports were occupied; rebuilding/running with isolated ports resolved it. The final production build restores the default backend destination.

