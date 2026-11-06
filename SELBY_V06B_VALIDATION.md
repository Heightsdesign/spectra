# SELBY V0.6b validation

Validation date: 2026-11-03. No Stripe network payment, real charge, configuration publication, or development/production migration occurred. Stripe is disabled locally; TEST key, webhook secret and merchant identity are not configured. Stripe CLI is installed. Actual end-to-end Stripe TEST acceptance is **NOT COMPLETE**.

## Executed checks

| Check | Result |
| --- | --- |
| Broad backend regression at implementation checkpoint | 505 passed, 269.12 seconds |
| Final focused Stripe + V0.6a foundation + migration regression after retry and refund-evidence refinements | 54 passed, 6.29 seconds |
| Frontend unit/request regression | 79 passed |
| TypeScript | Pass |
| Production Next build | Pass |
| ESLint on commercial frontend changes | Pass |
| Ruff E4/E7/E9/F/I on Stripe modules, migration, tests and commercial integration | Pass |
| Production Next + headless Chrome, synthetic API | Pass: TEST button, double-click suppression, URL cannot mark paid, authoritative pending/action/verified/restricted states, supplements, FR/EN, mobile |

The broad run preceded the final asynchronous retry and replay refinements; the focused run verifies those backend changes. Counts are not cumulative unique coverage. Warnings: existing Starlette/httpx TestClient deprecation, Alembic path_separator, Node experimental type stripping and Next's ignored parent lockfile. A sandbox browser run could not reach Chrome's debug endpoint; the same acceptance script passed outside the sandbox using the approved local headless-browser execution.

backend/tests/test_stripe_checkout.py uses a synthetic Stripe transport and isolated PostgreSQL records. Coverage includes full server amount, strict payload tampering rejection, raw-body signatures/tolerance, wrong account/environment, Session amount/currency/metadata/reference and PI amount/currency/metadata/environment, cross-session PI association, conflicting event replay, asynchronous processing/action/failure/success, duplicate and out-of-order events, partial refund after payment and restrictions before success, disputes/refund notifications, staff holds/idempotency, actual cross-customer IDOR, signed HTTP webhook success without customer cookies/CSRF, expiration, uncertain creation/cancellation response recovery, verified cancellation before replacing a failed async attempt, and independent supplementary Checkout.

Private disposable-schema tests race two Checkout requests and duplicate webhooks across independent DB connections. They assert one Session, one verified payment, one dispatch expectation and one event evidence row, and refuse a nonempty financial downgrade. The existing migration test upgrades legacy records through 0015 without changing them, then downgrades/re-upgrades empty infrastructure. Only *_test databases and throwaway schemas are migrated.

Existing V0.6a tests and broad inspection/production/custody regressions cover unpaid received PCs, original shipping baseline, explicit exact copy/PC assignment, paid absent quantities without invented PCs, additional unpaid PCs, immutable slots, and duplicate grading safeguards. The new supplemental Stripe test confirms its own verified payment cannot substitute for the original shipping payment and never establishes an initial dispatch deadline. The legacy inspection provider remains fail closed; the prepared PC adapter does not authorize grading.

Browser artifacts: [acceptance record](validation_artifacts/v06b/browser-validation.json), [desktop](validation_artifacts/v06b/checkout-desktop.png), [French mobile](validation_artifacts/v06b/checkout-mobile.png). They use a synthetic API and create no Stripe payments or customer DB writes. They prove portal behavior, not actual Stripe integration acceptance.

## Reproduction

From repository root (fresh basetemp paths):

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests -q --basetemp=test_tmp_run/v06b-full-review
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_stripe_checkout.py backend/tests/test_paid_order_foundation.py backend/tests/test_paid_order_migration.py -q --basetemp=test_tmp_run/v06b-focused-review
```

Tests require the existing guarded TEST_DATABASE_URL. The fixture rejects databases without the *_test suffix and the configured development database. Migration/race checks need schema-creation privileges. Synthetic fixtures must never be invoked against non-test registries.

From frontend:

```powershell
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
node_modules/.bin/eslint.cmd src/components/paid-order-panel.tsx src/lib/commercial.ts --max-warnings=0
node tests/stripe-checkout-browser.mjs
```

Browser checks require installed Chrome or CHROME_PATH and free loopback ports 18381?18383. They close their own processes and use workspace artifact/profile directories. The broad backend and focused tests passed; no additional scanner GUI changes were made or claimed validated.

## Remaining gaps / release boundaries

- Actual Stripe TEST credentials, merchant identity, signed live-delivery TEST webhook and real TEST Checkout acceptance are missing. Follow SELBY_V06B_CONFIGURATION.md; no operational/live-payment claim is made.
- Production/LIVE charging is deliberately hard blocked; separate approval and reviewed implementation are required.
- Prices, tax, carrier/coverage assertions and terms remain subject to existing approvals. No values were published.
- The PC adapter is prepared but the legacy inspection provider remains disabled pending separate PC-scoped integration and acceptance. Payment alone cannot unlock grading.
- Refund execution and financial restriction release are absent. All restrictions persist, including failed refunds or won disputes, until an approved reconciliation/release mechanism exists.
- No scheduled payment reconciliation worker, durable webhook queue or automated ambiguous-attempt repair exists. Monitor failures and use reviewed Stripe redelivery/recovery. Unknown/misassociated supported events return errors rather than crediting another order.
- Canonical success timestamp recovery is bounded to 2,000 Stripe events and Stripe retention. Missing timestamps fail closed. Same-second provider timestamps preceding subsecond acceptance also fail closed for review.
- Positive EUR obligations only; zero-amount exemption, commercial amendment, post-payment address/service change and automatic refund policies are not inferred.

Configuration instructions, Stripe CLI procedure, operator acceptance and production checklist are in SELBY_V06B_CONFIGURATION.md. Migration/recovery design is in SELBY_V06B.md. All actual TEST acceptance and production checklist approvals remain outstanding.
