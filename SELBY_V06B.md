# SELBY V0.6b ? Stripe TEST Checkout

Implemented on the existing V0.6a commercial ledger. Charging is OFF by default. LIVE mode and charging under AUTH_ENVIRONMENT=production are rejected. No commercial configuration was published, no development/production migration was applied, and no real Stripe payment was made.

## Architecture audit

Read SELBY_V06A.md, SELBY_V06A_CONFIGURATION.md, SELBY_V06A_VALIDATION.md, SELBY_V06B_STRIPE_HANDOFF.md and SELBY_V06A_UNRESOLVED_DECISIONS.md. Inspected commercial.py/commercial_api.py, immutable commercial/pricing models and migrations 0013/0014, quote acceptance, intake ownership/locking, inspection_commercial.py and the physical entitlement checks.

Submission, SubmissionQuote, QuoteAcceptance/SupplementaryAcceptance, PaymentObligation, VerifiedPayment, DispatchExpectation and EntitlementAssignment remain authoritative. There is no parallel order or credit ledger. A Checkout attempt references exactly one obligation by its quote primary key. Amount is PaymentObligation.amount_minor, checked against checkout.final_payable_minor; the legacy grading-only quote total is never charged.

The new StripeAttempt stores the server attempt UUID, pinned merchant account, return origin, unique Session/PaymentIntent identities and operational status. Reservation commits before network access. Existing order locks and a partial unique index prevent multiple active attempts. A lost response retries identical parameters and the same Stripe idempotency key; after 23 hours an unidentified Session fails closed for review because Stripe may prune keys after 24 hours. Expiration is verified before replacing an attempt. Failed asynchronous Checkout requires verified PaymentIntent cancellation before a replacement can be created. Cancellation redirects alone do not cancel a payable Session.

## Interfaces

- POST /api/submissions/{id}/stripe-checkout ? authenticated, CSRF protected, strict body containing only quote_id. Checks customer ownership, actual acceptance, complete immutable snapshot, positive EUR obligation and financial restrictions. Initial and supplementary quotes use this same endpoint.
- GET /api/submissions/{id}/payments/{quote_id} ? authenticated backend status; ownership and order linkage checked.
- POST /api/stripe/webhook ? raw body, timestamped HMAC SHA256 Stripe-Signature verification, 300-second tolerance, constant-time signature comparison and 1 MiB limit. This route alone has no browser CSRF requirement.
- POST /internal/intake/submissions/{id}/payment-hold ? existing staff authentication/CSRF/order locking; quote_id, request_key UUID and reason. Append-only, idempotent evidence. There is deliberately no hold-clear or refund execution endpoint.

The webhook verifies TEST mode, endpoint merchant account through the authenticated Stripe account API, optional event account, persisted attempt account, current Session, PaymentIntent, charge, full amount, EUR, customer/order/quote/obligation/attempt metadata and Session-to-PaymentIntent linkage. Only a paid Session plus succeeded, fully received PaymentIntent and paid/captured matching charge can enter record_provider_confirmation. The canonical payment_intent.succeeded event provides the provider success timestamp. No redirect credits payment.

If a non-success event arrives first after settlement, the handler searches up to 2,000 recent canonical success events. Stripe event retention and this bound mean old/unrecoverable timestamps fail closed with 503; operator reconciliation is required. A refund/dispute is recorded without requiring a recoverable historical success timestamp. Events without supported types are acknowledged without a payment transition. Supported foreign/unassociated payment events fail closed; use a dedicated TEST account or filtered destination for SELBY and monitor retries.

## Restrictions and workstation

StripeEvidence is append-only, deduplicated by event identity and checked against a canonical event digest to reject conflicting replay. Refunds (including partial and failed refund notifications), disputes, fund withdrawals/reinstatements and manual holds conservatively restrict the obligation. Closed/won disputes and failed refunds do not automatically restore eligibility. Every restriction requires an approved future reconciliation/release policy; there is no automatic release. Historical VerifiedPayment and dispatch timestamps remain intact.

card_commercial_state checks restrictions on both the exact assigned quote and original shipping baseline. pc_commercial_evidence(db, physical_card) prepares the PC-scoped adapter. It is NOT installed into the legacy order-scoped CommercialProvider: inspection remains fail closed. Payment never allocates a PC or grading session, consumes an unrelated copy slot, resolves a discrepancy, proves physical receipt, or bypasses custody/reconciliation/inspection/grading gates.

The customer panel exposes TEST Checkout only for server-authorized accepted obligations, shows pending/action/failed/expired/cancelled/verified/restricted states, suppresses simultaneous clicks and reloads backend state on return. Pending/action states refresh every five seconds; manual Refresh remains available. Supplementary quotes have independent controls/status. An expired or cancelled attempt may need another click to start a replacement. Browsers never submit money or payment-success assertions.

## Migration 0015: operator review required

Review backend/alembic/versions/0015_stripe_checkout.py before any non-test use. It adds stripe_attempts and stripe_evidence, indexes, immutable identity/evidence triggers, and a one-active-attempt-per-obligation partial index. It performs no backfill, repricing, payment confirmation or identity remapping. Existing records remain unchanged.

Release plan: back up and verify restore; review schema diff and lock impact in a disposable clone; stop old writers; apply 0015 once as an explicit operator action; verify Alembic head, tables, indexes and triggers; deploy backend and frontend with STRIPE_ENABLED=false; complete configuration and TEST acceptance separately. Application startup does not migrate.

From backend, after explicit database-target review: .venv/Scripts/python.exe -m alembic upgrade 0015. This command was NOT run against development or production during implementation. Test fixtures migrate only a guarded *_test database and disposable schemas.

Downgrade to 0014 refuses if either new table contains rows. For an unused installation only, an operator can downgrade before restoring the previous application. With financial history, disable initiation, preserve webhook processing/retries and evidence, back up, then recover forward. Never delete attempts, clear identities, recycle keys or erase financial evidence to make a downgrade pass. Restore recovery requires reconciling every Stripe Session/PaymentIntent since the backup before reopening initiation.

## Recovery

For Stripe outages, keep the durable attempt and retry within its safe idempotency window. If Session creation succeeded but persistence failed, repeat initiation to recover using the same key; webhooks return 503 until linkage is durable. For attempts older than 23 hours with no saved Session, use Stripe TEST Dashboard metadata/client_reference_id and request logs to identify the original Session; reconcile it through a reviewed operational repair. There is no automated ambiguous-attempt repair tool. Do not mark paid or generate a new attempt speculatively.

Monitor 400/503 webhook responses, missing confirmations, restricted obligations and aged creating/pending attempts. Stripe delivery retry is the recovery mechanism; there is no durable queue or scheduled reconciliation worker in this release. Use Stripe Dashboard/CLI redelivery after correcting the cause. Do not log signing secrets, keys, raw webhook bodies or customer checkout payloads.

See SELBY_V06B_CONFIGURATION.md for CLI testing and acceptance, and SELBY_V06B_VALIDATION.md for executed checks and remaining gaps.
