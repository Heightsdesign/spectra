Multi-card order workflow: PASS

Validated on **2026-10-26** against the actual local Next.js portal, FastAPI and PostgreSQL using a fictional customer. No API interception, fake backend or in-memory order store was used for the mandatory acceptance journey.

## Result

- SP: **SP-26445DCF040A4CAFB367173C2F77E2FC**.
- Route: `/account/submissions/26445dcf-040a-4caf-b367-173c2f77e2fc`.
- Account: `client03@selby.test`, initially zero SP orders.
- SP submissions created by the operation: **1**. Global local count changed **8 → 9**; the test customer's count changed **0 → 1**.
- Different card copies added: **3**, one each for Pokémon, One Piece and Dragon Ball. Each entry has quantity one and its own owned-copy UUID.
- One optional front photograph uploaded through the existing customer photo controls.
- Whole-order confirmation POSTs: **1**. Final state: **submitted**, three immutable declarations.
- New PC/ORD/SLB-C identities: **0**. No physical receipt, payment, grading or inspection action occurred.
- Remaining blockers for AC1–AC7: **none**. Commercial quote/payment readiness remains governed by the existing configuration and restrictions.

The confirmed fictional order is intentionally retained for inspection. No historical customer orders were deleted, reset, merged or converted.

## Mandatory inspection and exact change

Order creation starts in `/account`, rendered by `AccountArea` and `Submissions`. The existing `POST /api/submissions` creates an empty SP draft and navigates directly to `/account/submissions/[id]`. The dynamic route renders `SubmissionPage`/`Submissions` in `frontend/src/components/submissions.tsx`.

The APIs already existed: `library-register`, `library-copies`, entry DELETE, configuration/quotes and confirm. The problem was presentation: the dashboard placed the library first, the draft exposed an always-open registration form rather than an explicit Add action, and configuration/checkout forms appeared before the card-building sequence was clear.

The fix places My Orders first and introduces explicit cards → registration/selection → cards → configuration/review states within the same order page. Add a card opens the existing manual/catalog fields with the originating SP reference. Save closes that panel, updates the same order from the API response and returns focus to its card list. Choosing an existing library copy does the same. Configuration and checkout appear after Continue to quote; no duplicate speed/label controls are introduced. Selected cards use a responsive grid, clear count and existing optional photo controls.

No backend endpoint, identity model or migration was added or changed for this fix. Existing PostgreSQL exclusivity and immutability rules remain the security boundary. Older API responses without the library capability retain their legacy editing presentation for compatibility.

## Acceptance evidence

| Criterion | Result and demonstrated evidence |
| --- | --- |
| AC1 — one order, multiple cards | One browser create-order action; exactly one `POST /api/submissions`; three successive Add/Save actions on that SP. PostgreSQL confirms one customer order, three rows and sum(quantity)=3. Dashboard visibly shows `Cartes : 3`. |
| AC2 — originating order navigation | After every save the browser remained at the same `/account/submissions/{id}` route, the registration panel closed, and the new card appeared immediately. No library-page redirect or extra SP creation occurred. |
| AC3 — existing library | After adding the third copy, the browser removed it, verified it was available in My Cards, then selected that same CC UUID back into the same draft. No library pre-registration was needed for the first cards. |
| AC4 — exclusivity | A live duplicate assignment was rejected with 409. Direct PostgreSQL checks confirm `uq_copy_active_assignment` is unique with the active-row predicate, three distinct active assignments for this SP and zero global duplicate active copy assignments. The existing independent-connection two-order regression also passed: one competing assignment succeeds and the other is rejected. No second live SP was created merely to test this rule. |
| AC5 — persistence | Full page reload retained all three cards. The browser then signed out, signed back in through the real login form, saw the same single dashboard order with count three, and reopened the same SP with all cards. A later separate browser session read the same confirmed order. |
| AC6 — whole-order confirmation | Continue to quote opened the existing configuration/quote panel. At most one speed and one slab-label selector were present. Review/Confirm sent one confirmation for all three cards. UI became read-only; a subsequent entry DELETE returned 409, and the full confirmed API snapshot remained identical. The actual authenticated Workstation preview loaded three declared cards, zero received cards and the private photo with matching bytes/integrity. |
| AC7 — visible UI | Empty/one/three-card screenshots show SP reference, Brouillon, card list/count, Ajouter une carte, Choisir dans mes cartes, remove actions and Continuer vers le devis. French live flow passed; English synthetic regression passed. Real mobile readback at 390px had no horizontal overflow. |

## Screenshots

All are actual Chrome captures of the live local portal; none was generated or edited.

1. [Empty SP draft](frontend/.visual-review/order-builder-live/01-empty-draft.png)
2. [Same order with one card](frontend/.visual-review/order-builder-live/02-order-one-card.png)
3. [Same order with three cards](frontend/.visual-review/order-builder-live/03-order-three-cards.png)
4. [Dashboard: one order, three cards](frontend/.visual-review/order-builder-live/04-dashboard-one-order-three-cards.png)
5. [Existing configuration and quote step](frontend/.visual-review/order-builder-live/05-configuration-and-quote.png)
6. [Confirmed order](frontend/.visual-review/order-builder-live/06-confirmed-order.png)
7. [Mobile confirmed-order readback](frontend/.visual-review/order-builder-live/07-mobile-confirmed-order.png)
8. [Focused dashboard readback](frontend/.visual-review/order-builder-live/08-dashboard-viewport.png)

Machine-readable proof is in the ignored local `frontend/.visual-review/order-builder-live/progress.json`; it records the SP reference, request methods/paths, per-criterion results, PostgreSQL checks, Workstation readback and screenshot paths. It contains no passwords, cookies or response bodies. The credentials document was read locally by the opt-in runner and was not printed or modified.

## Tests actually executed

- Targeted backend submission/library/concurrency/photo/configuration/Workstation contracts: **59 passed**, 3 existing dependency/configuration warnings, 4.60 seconds.
- Existing frontend unit suite: **72 passed**.
- TypeScript: **passed**.
- ESLint with zero warnings: **passed**.
- Production Next webpack build: **passed**, with the existing outside-repository lockfile warning.
- Real Chrome/local PostgreSQL journey: **passed**, including real form login, one SP, three manual registrations, private photo, removal/library selection, refresh/logout/login, configuration and one confirmation.
- Real read-only Chrome session: **passed**, persisted order, mobile overflow check and dashboard screenshot; no additional SPs created.
- Synthetic library browser regression: **passed**, all 12 scenario groups after adapting it to the explicit Add/Continue controls.
- Existing catalog/photo/configuration browser regression: **passed**, all four reported scenario groups, including legacy quantities, optional photos, catalog keyboard/mouse behavior, one speed/label pair and payment restrictions.
- Direct live PostgreSQL verification: **passed**, as described above.
- Actual desktop authentication/Incoming/photo readback: **passed**, using a temporary validation vault so the existing Windows Credential Manager entry was preserved.

The first live runner attempt timed out at login and recorded no order-creation request. The runner now explicitly waits for the React login form to be hydrated. The successful run and later database checks demonstrate exactly one SP was created across the attempts. The runner saves the ID immediately and never deletes prior data to make a test pass.

Commands:

```powershell
# backend: existing guarded dedicated _test database
.venv/Scripts/python.exe -m pytest tests/test_library.py tests/test_library_concurrency.py tests/test_submissions.py tests/test_submission_photos.py tests/test_order_configuration.py tests/test_workstation_preview_contract.py -q

# frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build
node tests/library-browser.mjs
node tests/catalog-browser.mjs

# Explicit live test, only after verifying local DB/auth/origin and preparing its guard.
# For the completed evidence above, rerunning now performs read-only readback.
$env:SELBY_LIVE_ORDER_BUILDER_TEST='1'
node tests/order-builder-live-browser.mjs
```

The live runner is excluded from ordinary unit-test globs, requires explicit opt-in and a PostgreSQL preflight guard, and permits only the known fictional customer addresses on localhost. Once its verified confirmed result exists, it takes a read-only path instead of creating another order. Do not point it at production, reset a database, or delete an existing order to fabricate an empty dashboard.

## Files changed for this fix

- `frontend/src/components/submissions.tsx`: explicit order-builder actions/states, same-order return, selected-card list/count, staged configuration/review and focus handling.
- `frontend/src/components/account-area.tsx`: My Orders before My Cards.
- `frontend/src/app/globals.css`: scoped summary/action/grid/empty-state responsive styling.
- `frontend/tests/library-browser.mjs`: existing regression adapted to the explicit builder actions.
- New `frontend/tests/order-builder-live-browser.mjs`: opt-in real-service acceptance runner and safe readback mode.
- This validation report. Build-generated Next declarations may be refreshed by the required production build. Earlier unrelated repository changes were preserved.

No production deployment or migration. No backend/Workstation implementation change, grading evidence change or protected research-artifact change.

## Manual reproduction

1. Open the local portal and sign in with an authorized fictional customer. Go to Mes commandes and create a draft.
2. On its SP page, use Ajouter une carte, fill game/name/language and save. Confirm the same SP reference and count one. Add two more different copies the same way; count becomes three.
3. Optionally upload front/back photographs from each saved card. Remove a draft card, choose it again from Mes cartes and verify it returns to that same order. Reserved copies must remain unavailable elsewhere.
4. Reload, sign out/in and reopen the same order. Verify all three cards and dashboard count.
5. Choose Continuer vers le devis, use the existing configuration/quote controls as available, review the complete order and confirm once. Verify the read-only snapshot and Workstation declared quantities. Payment/inspection clearance is not implied by customer confirmation.

The validated fictional SP listed above is already confirmed; inspect it read-only. A new full manual acceptance pass should use a separate authorized test operation and record its own baseline, not modify that confirmed evidence.
