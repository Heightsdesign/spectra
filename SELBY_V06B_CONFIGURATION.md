# SELBY V0.6b configuration and acceptance

## Local TEST configuration

Keep credentials in backend environment or an ignored backend/.env, never frontend NEXT_PUBLIC variables, source, screenshots, command history or logs. Existing commercial catalogs remain unconfigured until separately approved. Accepted snapshots must contain reliable complete shipping, taxes and approved terms; this integration does not publish or fabricate them.

Set STRIPE_ENABLED=false initially. Configure STRIPE_MODE=test, STRIPE_SECRET_KEY (a sk_test_ key), STRIPE_WEBHOOK_SECRET (the whsec_ signing secret), STRIPE_ACCOUNT_ID (the exact acct_ merchant identity), STRIPE_API_VERSION=2025-02-24.acacia, and AUTH_ORIGIN matching the frontend origin. The implementation uses httpx for Stripe API v1 form requests and the documented Stripe HMAC signature protocol; no additional SDK installation is required. API requests have a 15-second timeout and never follow redirects. Review the pinned API version and webhook snapshot format together before changing either.

STRIPE_ENABLED=true is permitted only in the existing development authentication environment with TEST credentials. Both live mode and production authentication charging are hard blocked. There is no flag that approves production charging. A subsequent reviewed release must implement any LIVE capability.

## Stripe CLI webhook testing

Use a dedicated Stripe TEST/sandbox account. Authenticate the installed Stripe CLI locally with stripe login, confirm the selected merchant and TEST mode in Dashboard, and keep the generated credentials private. Start the backend on loopback port 8000 and the frontend with the matching AUTH_ORIGIN. Do not expose development authentication publicly.

```powershell
stripe listen --events checkout.session.completed,checkout.session.expired,checkout.session.async_payment_succeeded,checkout.session.async_payment_failed,payment_intent.succeeded,payment_intent.processing,payment_intent.requires_action,payment_intent.payment_failed,payment_intent.canceled,charge.refunded,charge.dispute.created,charge.dispute.updated,charge.dispute.closed,charge.dispute.funds_withdrawn,charge.dispute.funds_reinstated,refund.created,refund.updated,refund.failed --forward-to http://127.0.0.1:8000/api/stripe/webhook
```

Copy that listener's signing secret privately into STRIPE_WEBHOOK_SECRET, restart the backend, then enable TEST initiation. CLI and Dashboard endpoint signing secrets are different. The endpoint is on the backend; no Next rewrite is necessary for CLI forwarding. Use a direct HTTPS backend webhook destination for a separately reviewed hosted test environment.

Generic stripe trigger checkout.session.completed fixtures have no SELBY obligation/attempt metadata and must be rejected. They are not end-to-end acceptance. Create Checkout through the authenticated SELBY button, and complete the actual TEST Session using Stripe's documented TEST payment details. Never use a real payment card. Refer to https://docs.stripe.com/testing for success, authentication, decline and delayed payment scenarios.

For an already received event, redeliver using the TEST Dashboard delivery panel. CLI redelivery to a registered TEST webhook destination can use: stripe events resend EVENT_ID --webhook-endpoint=WEBHOOK_ENDPOINT_ID. That command requires the registered endpoint's own signing secret at the receiver; it is not the ephemeral listener secret. Do not use --live.

## Operator acceptance record ? not yet executed

Record revision, operator, time, TEST merchant identity, API/webhook version, approved test configuration references, submission/quote/obligation IDs, attempts, Stripe Session/PaymentIntent/event IDs and outcomes. Exclude keys and secrets.

1. Verify migrations in an isolated acceptance database; review catalog, tax, shipping/coverage and terms configuration. Use synthetic fixtures only in isolated databases, without publishing a real offer. Verify the full amount includes grading, original return shipping and tax exactly once.
2. Accept an initial quote with a verified TEST customer. Double click Checkout: one durable active attempt/Session. Change browser amounts/quote IDs/ownership: requests fail without creating a payable Session. An unsigned webhook fails. Another signed merchant/environment must fail.
3. Complete a real Stripe TEST Checkout. Return before webhook delivery: status stays pending. Deliver the verified event: one VerifiedPayment and one 30-day dispatch expectation. Reload with paid=true or a fabricated success URL: no extra payment. Resend the event and deliver earlier failure events: no duplicate credit or deadline.
4. Exercise Stripe TEST authentication and declines, delayed-payment success/failure with an eligible configured TEST payment method, cancellation and Session expiration. Pending async completion must not credit payment. A terminal async failure's previous PaymentIntent must be cancelled before a fresh attempt. Verify uncertain network response recovery and the aged-attempt review block.
5. In TEST Dashboard issue partial/full refunds, create a supported TEST dispute and redeliver refund/dispute events before/after success. Confirm durable restricted status. Apply a staff manual hold with a reason; replay it idempotently. Do not automatically clear restrictions after a dispute closes.
6. Receive/reconcile test PCs through the established intake workflow. Unpaid received PCs remain blocked; paid but absent cards never get PC identities or grading authorization. Additional PCs require their own accepted supplement, explicit assignment, verified supplemental payment AND original shipping payment. Restrict either payment and verify blocking. Inspection remains fail closed even when commercial evidence is complete.
7. Repeat supplementary Checkout with a distinct obligation and verify it never resets the initial dispatch deadline. Verify cross-customer reads/writes, service/copy-slot preservation and no duplicate grading authorization. Record browser FR/EN/mobile behavior and return URL handling.
8. Review webhook errors/retries, backup/restore and ambiguous-attempt procedures. Sign and attach results before calling actual Stripe TEST acceptance complete.

## Production release checklist ? all pending

- Actual end-to-end Stripe TEST acceptance signed off, including async methods, refunds/disputes, ownership and concurrency.
- Commercial/legal approvals for service prices, VAT, shipping/carriers/insurance, terms, consumer remedies and dispatch timezone wording; legacy accepted orders reviewed individually.
- Separate security/release approval for LIVE capability and production credentials. The current hard gate must remain until a reviewed implementation change.
- Merchant settlement/payment-method/refund/dispute policies, evidence retention and authorized restriction-release/reconciliation procedures approved.
- PC-scoped inspection integration separately implemented/reviewed; no order-wide payment adapter substituted.
- Production migration/backup/restore plan approved, least-privilege DB and Stripe credentials reviewed, HTTPS webhook destination/version/signing-secret rotation validated.
- Monitoring, event redelivery, aged-attempt reconciliation, operational ownership and incident procedures accepted.
- Production deployment explicitly approved. Never infer that TEST success authorizes real charges or configuration publication.
