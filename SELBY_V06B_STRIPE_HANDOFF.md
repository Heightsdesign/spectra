# SELBY V0.6b — Stripe integration handoff

V0.6a deliberately contains no Stripe SDK, Checkout session creation, provider HTTP callback, live charge, refund execution or payment-success simulation. No settings flag can turn charging on. Customer and supplementary payment actions remain disabled, and the existing inspection commercial provider still fails closed.

## Existing foundation to reuse

- `SubmissionQuote` is the immutable price/terms/shipping snapshot. Initial quotes have no PC scope; additional-card quotes point to an existing PC within the same submission.
- Primary `QuoteAcceptance` and supplementary acceptance record explicit customer consent independently from payment.
- `PaymentObligation` pins the **complete** EUR amount, including return shipping and tax. Do not use the legacy root quote `total_minor`, which is grading-only.
- `VerifiedPayment` records one trusted full confirmation per obligation, with globally unique provider event and payment identifiers. Records cannot be rewritten or deleted.
- `commercial.record_provider_confirmation` accepts raw provider input only through a trusted server-side `ProviderVerifier.verify` implementation. None is wired into V0.6a. Synthetic implementations exist only in guarded isolated tests.
- `DispatchExpectation` is created exactly once for the verified accepted initial quote; supplementary payments never restart its deadline.
- Explicit `EntitlementAssignment` binds one accepted quote/copy slot to one exact PC, without changing physical status or custody. Supplementary PCs cannot consume initial quote slots. Slot reuse and rebinding are blocked.

## Required V0.6b work before enabling payment

1. Approve and publish service, tax, shipping and terms configuration. Review legacy acceptances; do not backfill paid state or assume old grading-only agreements contain a complete payable amount.
2. Add server-owned payment-attempt/Checkout-session lifecycle and idempotency. Use the accepted obligation and server-selected customer/order/quote IDs. The browser must not supply authoritative amounts, currency, prices or payment-success flags.
3. Implement a trusted Stripe verifier. Verify signatures using the raw body, correct account/environment, event type and settled state. Independently check provider session/payment linkage, immutable quote identity, full amount, EUR currency, merchant account and final settlement. Browser redirects and acceptance callbacks are not confirmation.
4. Feed only validated `ProviderConfirmation` results to the existing transactional seam. Commit payment, first dispatch expectation and audit together. The seam checks an existing accepted obligation, exact amount/currency, aware nonfuture payment time after acceptance, replay/conflict rules and duplicate payment identity. It does not itself implement Stripe signature verification.
5. Preserve replay handling and out-of-order event safety across independent DB connections. Add explicit durable refund/dispute/reversal/hold state and policy before using a recorded payment as current unrestricted evidence. A historical confirmation alone is insufficient when later restrictions exist.
6. Keep refunds, consumer rights, missed-deadline consequences and missing-card adjustments under approved terms and legal review. No automatic forfeiture, redistribution, repricing or refunds should be inferred from V0.6a state.
7. Only then connect a **PC-scoped** commercial evidence adapter to the established inspection eligibility boundary. The current legacy provider signature is order-acceptance-scoped; it must not grant an additional PC clearance merely because an original order was paid. Check exact assignment, quote, service, all relevant payments, current restrictions and the original shipping baseline. Preserve all custody, reconciliation, association, discrepancy and existing grading gates.
8. Implement an approved operational policy for reconciling additional PCs to declarations without rewriting original paid quantities or evidence. A supplementary commercial quote does not resolve an unmatched physical card or alter its custody status.
9. Expose Checkout initiation only after server, webhook, replay, concurrency, security and operational tests pass. UI success must continue to depend on authoritative state, never a query parameter or client callback.

## Payment timestamps and dispatch

`ProviderConfirmation.paid_at` means the trusted provider's verified payment/settlement timestamp, not a customer date or quote-acceptance time. V0.6a stores it as `verified_at`, alongside a separate recording timestamp. The initial deadline is exactly 30 UTC calendar days later. Approve the timezone/cutoff wording before launch; do not change already-recorded expectations silently.

Customer-declared shipment time is a distinct, unverified field. Carrier acceptance and physical receipt remain different evidence. Notification hooks are candidates only; message delivery, recipient preferences, deduplication and scheduling are future work.

## Production release boundary

Apply migrations before the updated backend. Use approved configuration and a reviewed rollout, not synthetic fixtures. Do not run V0.6a test verifiers against development or production records. Current `card_commercial_state` describes the foundation's entitlement/payment completeness; it is **not** a replacement for current provider restrictions or inspection authorization.
