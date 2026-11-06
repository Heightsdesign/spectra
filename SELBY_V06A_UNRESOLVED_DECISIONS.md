# SELBY V0.6a — unresolved business and legal decisions

These items were not invented by the implementation. Charging remains disabled.

| Decision | Current safe behavior |
| --- | --- |
| Earlier complete V0.6a specification | Not present in the conversation or repository search. Clarification requested; delivery follows the confirmed November decisions and documented existing architecture |
| Actual service names, descriptions, stable IDs and prices | Configurable; no new commercial catalog published. Synthetic test tiers are not offers |
| Turnaround targets, guarantees and remedies | Optional approved catalog text only; no default target or guarantee |
| VAT registration/status, applicable rates, jurisdiction and inclusive/exclusive presentation | Explicit per-service/shipping configuration plus validation reference required; no actual VAT rate supplied |
| Treatment of upgrades/bundles and any future adjustments | Existing upgrades inherit selected-service tax treatment. No new nonzero adjustment or discount policy was invented |
| Customer-facing terms, commercial terms version and disclosures | New quote acceptance blocked without a configured terms version. Approve actual content, version governance and publication/linking before launch |
| Shipping carrier contracts, destination/zone rates and card-count/packaging rules | Explicit configuration required. Unreliable or unavailable rates leave checkout blocked |
| Insurance eligibility, actual trading-card coverage, exclusions, declared-value rules and evidence | Require configured coverage and evidence; the application provides no coverage or carrier guarantee |
| Additional-card return shipping/insurance increments | Require an explicit configured incremental rate, including an explicit zero if approved. Aggregate value/count checked; original amount unchanged |
| Return service or address changes after acceptance/payment | No silent amendment. Accepted destination and service are frozen; a different supplementary shipping service requires review. A full commercial amendment process remains to be specified |
| Dispatch deadline timezone and cutoff | Implementation uses UTC, preserving the verified payment time plus 30 calendar days. Approve wording; no penalty or forfeiture consequence is encoded |
| Reminder lead, content, consent/preferences, escalation and delivery | Optional lead setting; no default lead, emails, jobs or scheduling subsystem |
| Consequences of late/non-dispatch under approved terms and consumer law | Indicators and explicit manual review only; no automatic cancellation, retained-funds penalty, refund or missing-card classification |
| Missing-card entitlements, refund/dispute decisions and late-arriving originals | Existing explicit reconciliation remains authoritative. No automatic redistribution, repricing, refund or entitlement recycling |
| Additional-card declaration/reconciliation policy after supplementary payment | Existing physical identity preserved and other grading gates remain blocked until established authorized reconciliation permits processing |
| Service changes after declaration confirmation but before quote acceptance | Existing submitted declarations remain immutable. An inactive/unknown selected service fails closed; an approved amendment/review policy is needed |
| Financial retention, erasure, archival and administrative corrections | Append-only financial/audit records; nonempty-history downgrade refused. Approve retention and recovery procedures instead of deleting history silently |
| Stripe account, settlement semantics, payment attempts, refunds/disputes/reversals and commercial holds | V0.6b work. No provider configured and no actual charging in V0.6a |

This list identifies approval needs; it does not prescribe legal outcomes or limit statutory consumer rights. No blanket no-refund claim was added to the portal.
