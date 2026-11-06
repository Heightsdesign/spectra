# SELBY — Customer Return Preparation UX V1

## Audit and resulting behavior

Inspected the customer order/return panel and address book, checkout schemas/models/routes, shipping eligibility/calculation, versioned pricing/shipping publication, quote acceptance/snapshots, internal intake/custody, customer operations, reference creation, Workstation order identifiers, and the relevant backend/frontend/browser tests.

The customer return form previously collected `weight_g`, `length_mm`, `width_mm` and `height_mm`. Its save handler always sent those fields, while the API reset omitted delivery fields to schema defaults. Removing inputs alone would therefore erase saved parcel data. The fix changes customer payloads to address, estimated value and an explicitly present service selector; the API now preserves omitted fields. Explicit existing API payloads remain supported for compatibility.

The customer now sees:

- Return address selection and the existing address-management link.
- **Estimated total card value (EUR)** with an explanation that this is the combined collectible value for all cards, separate from grading charges and not a coverage/compensation guarantee.
- An explanation that SELBY packages the cards after encapsulation and staff records parcel measurements.
- A service selector only when configured services are available for the selected address country. Otherwise, a clear message says the address/value can be saved while return pricing and payment remain unresolved.
- Explicit development-estimate and pending-tax messaging, rather than presenting tax placeholders as validated zero tax or development subtotals as payable totals.

No parcel measurement inputs or hidden measurement fields are present in the current customer form, and its payload builder ignores such fields even if added to FormData. Existing saved measurements and an unavailable saved service are not silently cleared when those controls are absent. No carrier, insurance guarantee, delivery time, new price or tax treatment was invented.

## Existing rules preserved

| Area | Existing rule / result |
| --- | --- |
| Addresses | Session ownership, versioning, ISO country and phone validation, at most 100 saved addresses; address deletion is blocked when selected by a submission. |
| Estimated card value | Stored as integer minor units; nonnegative schema rules remain unchanged. It can be omitted during preparation, but an eligible service requires a value within its configured coverage ceiling. No new valuation or insurance rule was introduced. |
| Customer card confirmation | Still freezes card declarations. Return preparation has a separate delivery version and may continue after card confirmation until commercial terms are accepted. |
| Commercial acceptance | Requires confirmed cards, a current/unexpired quote, complete checkout readiness and non-development pricing. Accepted quote/address/shipping snapshots remain immutable. |
| Payment | Still unavailable in the UI; no payment endpoint/integration was added. Complete readiness is not payment authorization. |
| Shipping eligibility | Requires configured/available tracked service, supported country, verified trading-card coverage/reference, value within coverage, required phone, and any configured parcel limits. |
| Custody/inspection | No received-card identities, reconciliation statuses, custody transitions, grading evidence or inspection/payment restrictions changed. |

The authoritative backend readiness and financial calculations were not changed. A frontend presentation guard now refuses to show a payable amount when readiness/shipping is incomplete, pricing is development-only, or tax is unresolved, even if a response contains a numeric placeholder. Pending tax/net values are labeled pending validation. Actual configured financial amounts continue to come from the backend.

## Operator parcel preparation

The audit found parcel schemas/storage, but no separate authorized operator screen for return measurements. A minimal preparation panel was added to the existing staff intake detail, reusing `SubmissionDelivery.parcel`, the existing `Parcel` validator and delivery version. It exposes the same weight/dimensions and ranges: 1–100000 g and 1–5000 mm, with optional blank measurements.

New internal routes, excluded from public OpenAPI like other intake routes:

| Route | Behavior |
| --- | --- |
| `GET /internal/intake/submissions/{uuid}/return-parcel` | Staff-only preparation version, stored parcel and accepted-terms lock flag. |
| `PUT /internal/intake/submissions/{uuid}/return-parcel` | Staff/session/CSRF-protected `{version, parcel, reason}` update for a submitted declaration before commercial acceptance. |

Each staff update serializes on the existing submission row, checks the delivery version, increments that version and appends `return_parcel_prepared` to the existing intake audit with actor, reason, before/after and server timestamp. Existing quote-context checks invalidate older unaccepted quotes. It does not register receipt, authorize dispatch, create an intake state or change card declarations. The panel/route refuses to edit accepted terms; it is **preparation**, not a complete outbound fulfillment workflow.

For API/data compatibility, the legacy customer delivery endpoint still accepts explicitly supplied parcel payloads under its existing ownership/version rules. Current portal customers cannot enter/send these fields. Existing values must not be described as independently verified operator measurements merely because they exist. The new staff route records its authorship through the audit trail. No authorization tightening of legacy clients or parcel-provenance backfill was silently introduced.

## Shipping architecture audit and smallest future approach

| Capability | Repository status |
| --- | --- |
| Shipping configuration | Versioned immutable `ShippingConfiguration` JSON documents and a current-version pointer, published by a trusted operator CLI. |
| Rates | One fixed `charge_minor` per configured service; destinations, coverage, tax and optional maximum parcel limits. No weight-band/tiered carrier rate engine. |
| Weight estimates | None. No card/slab/packaging mass estimates or dimensional model exists. |
| Declared-value eligibility | Existing service coverage ceiling/reference and required declared value. No automatic insured value calculation or guarantee. |
| Actual measurements | Existing parcel fields, now accessible through the authorized preparation panel. The accepted preparation record remains locked. |
| Carrier integration/dispatch | None; no carrier API, labels for customer returns, tracking purchase or shipping-time promise added. Existing physical labels are independent. |

The smallest future customer flat-rate approach can reuse the current fixed service charge and quote snapshot, once the business explicitly approves destination/quantity/value eligibility, charge, coverage terms and tax treatment. It does not require a carrier integration merely to quote a business-approved flat customer charge. Do not remove parcel eligibility limits simply to force checkout readiness; any pre-measurement pricing basis must be an explicit commercial decision.

Actual packed measurements belong after encapsulation. They must eventually be recorded on an authorized outbound fulfillment/shipment record linked to the immutable accepted quote and received-card inventory. The accepted quote/address/customer charge should not be rewritten to reflect later carrier costs or measurements. The current delivery record cannot serve both mutable post-acceptance fulfillment and immutable commercial terms; the new panel deliberately preserves its lock. Add that separate operational boundary only when outbound shipping is actually implemented. Any variance/requote policy requires a business decision; none is assumed here.

## Pricing/tax placeholder audit

- `backend/pricing/development-example.json`: development-only synthetic grading amounts, `tax_mode: exempt`, numeric zero rate. It is an example, not an approved exemption; commercial acceptance rejects development snapshots and production publication rejects development catalogs.
- `backend/pricing/spectra-v1.json`: existing grading amounts with `tax_mode: pending`, zero numeric placeholder and null tax-validation reference. The publisher blocks pending tax and commercial records without validated fiscal references. The zero is not an asserted VAT rate or exemption.
- `backend/pricing/shipping-unconfigured.json`: no services, destinations or receiving address. No return price, coverage or carrier is available to invent.
- Shipping services independently require configured tax treatment and validation references. Nothing here determines jurisdictional VAT, tax exemptions, coverable goods, compensation or delivery time from an address alone.

No pricing/shipping catalog document or publication state was changed. All numeric rate/coverage/tax examples in tests remain isolated synthetic fixtures.

## Order references and synchronization

Online submissions use immutable `SP-` plus uppercase 32-digit UUID hex (35 characters). Portal URLs/API ownership use the submission UUID. Intake parcels/cards have separate `PI-…` / `PC-…` references. The local Workstation has its own `ORD-000001` and `SLB-C-000001` namespaces; its existing Incoming preview is GET-only and does not make these online/local identities interchangeable.

A shorter customer reference is feasible only as an additional collision-checked, uniquely constrained alias mapped to the same submission UUID. Existing references, URLs, audit entity IDs and Workstation external-reference links must remain intact. A future alias may have its own generation/backfill policy and uniqueness migration; do not truncate a UUID or reuse the local ORD counter and claim uniqueness. This slice leaves all identifiers unchanged and labels the full existing submission reference clearly. No shorter alias or reference migration was introduced.

## Commercial decisions still required

Before any payable customer return quote: approve actual destination/service configuration, charge and pricing basis; verify trading-card coverage, limits and exclusions; decide declared-value bands and handling of unsupported values; validate tax treatment/references and receiving address; and define any packing/measurement variance policy. Later outbound fulfillment needs its own authorized lifecycle and accepted-quote linkage. Payment remains a separate unimplemented capability.

## Setup, files and compatibility

No migration or new dependency is required; no production migration/deployment or catalog publication was performed. Start FastAPI/Next with existing configuration. The existing `/internal/intake` rewrite and staff authentication cover the new panel. Existing customer address, submission and quote APIs retain their namespaces and identifiers. Saving without optional fields now preserves those fields; sending explicit null/parcel values remains an explicit change under existing rules.

Changed production files: `backend/app/checkout_api.py`; `frontend/src/components/checkout-panel.tsx`, `return-parcel-panel.tsx`, `intake-workspace.tsx`, `pricing-panel.tsx`; `frontend/src/lib/checkout.ts`, `pricing.ts`. Tests and this audit/validation report accompany the changes. Models, migrations, carrier code, pricing/shipping data and Workstation code were not changed for this slice.

Actual checks and manual validation steps are in `SELBY_CUSTOMER_RETURN_PREPARATION_UX_V1_VALIDATION.md`. No production-readiness or live commercial-shipping validation claim is made.
