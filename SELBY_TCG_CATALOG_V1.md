# SELBY TCG catalog V1.1 — customer search UX

V1.1 extends the existing V0.5a.2b catalog. No new database migration, provider, catalog store, or submission API is introduced.

## Repository audit and chosen slice

Audited before implementation: `frontend/src/components/submissions.tsx`, `frontend/src/lib/submissions.ts`, FastAPI `submission_models.py`, `submission_schemas.py`, `submissions.py`, migrations 0001–0007, PostgreSQL fixtures in `backend/tests/conftest.py`, frontend Node test conventions, Next rewrites, Workstation `incoming_ui.py`, `incoming.py`, and `orders.py`.

The existing portal saves each card explicitly into a versioned server draft, supports multiple entries, and confirms that draft irreversibly. There was no card catalog or card-data integration. Pricing and shipping catalogs have different responsibilities and remain separate. Customer game keys are `pokemon`, `one-piece`, `dragon-ball`, `naruto`; internal grading cards currently accept Pokémon only. This change does not expand internal grading policy.

The smallest slice is a persistent PostgreSQL catalog, an operator-only single-set Pokémon import, authenticated local reads, and searchable selection in the existing form. The existing manual declaration fields remain authoritative snapshots. No research artifacts, payments, grading rules, or physical identifier generation were changed.

## Architecture and schema

Migration **0008**, following 0007, creates `tcg_games`, `tcg_expansions`, and `tcg_cards`. The four existing game keys are seeded as stable game IDs. Expansions/cards have internal UUIDs and unique `(provider, external_id, language)` identities. Localized records have their own stable UUIDs; no translation is fabricated. Expansion metadata includes provider code and nullable release year. Collector numbers are opaque strings, not integers or synthesized fractions.

`customer_submission_entries.catalog_card_id` is a nullable foreign key. Legacy rows require no backfill. Existing `game`, `card_name`, `expansion`, `card_number`, and `language` columns remain the declared snapshot. Catalog-assisted writes validate these fields against the selected local record. Switching to manual entry detaches the reference. Older clients can omit it. Confirmation uses the existing immutable state/version guards and does not resolve or refresh catalog data.

Imports update catalog rows in place while retaining UUIDs and external identities. They never update submission entries. Missing provider records are not deleted automatically. Physical-card UUIDs, backend PC references, and Workstation `SLB-C-…` numbering remain independent. Incoming Submissions continues reading the same declared fields.

## Provider evaluation and terms

No existing provider was available to reuse. Pokémon uses TCGdex only. Other games retain manual entry until a source and its terms are reviewed; no completeness claim is made.

Sources reviewed 2026-10-25:

- Database license: https://github.com/tcgdex/cards-database/blob/master/LICENSE — MIT, copyright (c) 2021 TCGdex. Preserve its copyright and permission notice with redistributed data.
- Project disclaimer: https://github.com/tcgdex/cards-database — unofficial and unaffiliated with Nintendo/The Pokémon Company. Its software/data license does not transfer rights to third-party trademarks or artwork. This slice imports identification metadata only, no card art, logos, prices, attacks, or scans.
- API usage: https://tcgdex.dev/faq — no API key and no published hard rate limit; considerate usage and local caching are requested.
- Set endpoint: https://tcgdex.dev/rest/set — a set response contains brief cards, local IDs, and release metadata.

The CLI performs one HTTPS request per explicit operator invocation, has a 20-second timeout and 5 MB response ceiling, and makes no automatic retries. HTTP 429 and downtime fail the import before any writes. Operators must space invocations, respect Retry-After when returned, and avoid parallel bulk runs. There is no scheduled bulk importer in V1. Every successful import is persisted atomically. No credentials are needed or exposed to the browser. Searches never call TCGdex. Existing local records remain usable during outages. An initially empty database returns empty results, with explicit manual fallback.

TCGdex data notice (retain with imported/distributed data):

```text
MIT License
Copyright (c) 2021 TCGdex

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Local setup

Use the existing backend virtual environment, dependencies and PostgreSQL configuration. Explicitly verify `DATABASE_URL` targets a disposable/local development database before migration. From `backend`:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m app.tcg_import --language fr --set swsh3
# Run separately, after spacing requests, if English data is wanted:
.venv/Scripts/python.exe -m app.tcg_import --language en --set swsh3
```

These commands are operator actions, not application startup hooks. No production migration or production import was executed. Rollback 0008 removes the catalog and optional reference, so export any needed data first. Start FastAPI and Next with the existing documented commands. Next forwards `/api/catalog/:path*` to `SPECTRA_BACKEND_URL` alongside existing submission/auth rewrites.

## API and form

All catalog endpoints require the existing customer session. Responses use no-store browser caching; PostgreSQL is the persistent provider cache.

| Endpoint | Parameters / behavior |
| --- | --- |
| `GET /api/catalog/games` | Existing four game IDs, sorted by ID |
| `GET /api/catalog/expansions` | Required `game`, `language=fr`, `q`, `offset=0`, `limit=20` |
| `GET /api/catalog/cards` | Optional `expansion_id`; without it, both `game` and `language` are required. Also accepts `q`, `offset=0`, `limit=20`. |
| `GET /api/catalog/cards/{uuid}` | One localized catalog record or 404 |

List responses are arrays. Limits are 1–100; offsets are nonnegative. Search is literal case-insensitive substring matching on name/code or name/collector number; `%` and `_` are escaped. Name ordering has UUID tiebreakers; cards also use the opaque collector number. Pagination is offset-based, so concurrent imports can move page boundaries. An exact multiple of the page size can expose one final empty page.

The form offers game and catalog language, followed by an optional expansion filter and immediately available card search. Opening either combobox with an empty query fetches available local records. Both use scrollable listboxes, ArrowUp/ArrowDown, Enter to select an explicitly highlighted row, Escape to close, mouse selection and input focus retention. No first result is automatically selected. Card rows show name, localized expansion name/code, opaque collector number and language; same-name printings retain distinct catalog UUIDs.

Comboboxes fetch 20 records per page with a 300 ms debounce and AbortController cancellation. Explicit **Load more results** appends further pages without hiding earlier rows. Loading, empty, error and retry states replace the old zero counter and arrows. An exact full page allows another fetch to discover the end. Closed dropdowns do not fetch. Clearing the expansion removes its filter; changing game, catalog language or expansion invalidates dependent card selection. An interface-label language change alone preserves the filter and catalog language. A selected catalog card is validated through the visible card combobox, with no invisible required input.

Card list and detail responses add `game`, `expansion_name` and `expansion_code`; existing card fields and list-array response shapes remain. Legacy requests using only `expansion_id` still work without a language argument. Supplied game/language filters are applied alongside an expansion filter, so incompatible combinations return an empty list. Unscoped `/cards` requests return 422 rather than searching across games/languages accidentally. Existing ordering and authentication remain.

Manual mode requires no expansion selection. It detaches the catalog ID and keeps declared text. Returning to catalog mode retains that text plus unrelated quantity, notes and service choices until the user explicitly selects another printing or changes a parent. No catalog ID is fabricated and no query text is interpreted as a selected record.

Draft persistence remains explicit **Save card**, using existing PostgreSQL draft writes. Saved catalog and manual entries restore on reload, independently for multiple cards. Unsaved keystrokes are not persisted across browser reloads, matching prior behavior; no sensitive localStorage draft copy was added. Review/confirmation and Workstation display continue using saved snapshots.

## Limits and future work

Operational after local migration/import: stored set/card metadata, authenticated filtering/search/detail API, form assistance and manual fallback. The repository ships no invented sample inventory and no imported production data. Only operator-selected Pokémon FR/EN sets are supported by the importer. No full-game coverage, language equivalence mapping, variant disambiguation, automatic synchronization, retired-record handling, import history UI, or upstream freshness SLA is claimed. Large-catalog substring search may need PostgreSQL trigram indexing after measurement. Full browser/end-to-end and production validation status is recorded separately.

## V1.1 implementation files

| Files | Change |
| --- | --- |
| `backend/app/tcg_api.py` | Compatible game/language card search and printing context in list/detail responses |
| `backend/tests/test_tcg_catalog.py` | Game-wide scope, printings, optional expansion, language and complete pagination regressions |
| `frontend/src/components/catalog-combobox.tsx` | Shared accessible dropdown, pagination, request cancellation and feedback |
| `frontend/src/components/catalog-fields.tsx` | Name-first search, optional expansion, parent resets and manual/catalog mode integration |
| `frontend/src/lib/catalog.ts` | Populate expansion from a selected game-wide card result |
| `frontend/src/app/globals.css` | Scrollable dropdown, active/focus styles and flexible control layout |
| `frontend/tests/catalog.test.mjs`, `frontend/tests/catalog-browser.mjs` | State and browser regressions |
| This document and `SELBY_TCG_CATALOG_V1_VALIDATION.md` | Architecture delta, results, boundaries and manual validation |
