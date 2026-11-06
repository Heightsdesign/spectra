# SELBY — Single customer order configuration V1

## Audit and resulting sequence

The customer page rendered the same processing/label `Choices` component through three paths: card registration (`EntryServiceFields`), apply-to-all configuration and one editable form per saved entry. Card and submission notes also shared the generic “Notes” label despite having separate persistence scopes. The backend already had atomic apply-to-all configuration, per-entry configuration, versioned entry updates, immutable confirmation and quote invalidation.

The V1 customer sequence is now:

1. Register card identification, quantity and **Card notes (optional)**. The existing optional photo panels remain associated with saved declared copies. Registration has no processing-speed, slab-label or upgrade configuration inputs.
2. Use one **Order configuration** form for the effective processing speed, slab-label style and **Order notes (optional)**. One save stores the order choices and order notes together. Existing configured extra upgrades, if any, also appear only in this same form.
3. Generate/recalculate a quote from saved choices and prepare the return using the existing workflow.
4. Review and confirm. Configuration and order notes become read-only; historical per-card information remains readable.

There is one editable speed selector and one editable slab-label selector in a normal priced draft with saved cards. Empty drafts show the same pair disabled until the first card is saved. Unavailable pricing shows no invented choices and still permits order-note saves. Review and confirmed submissions show zero editable configuration selectors.

## Persistence without a duplicate configuration store

The existing per-entry `processing_tier` and `upgrade_ids` remain the persisted source of truth. No global-settings table, migration, schema backfill or localStorage copy was added. An order-wide effective configuration is inferred only when every saved entry has the same tier and the same upgrade IDs, comparing upgrades independent of their array order.

The current portal omits configuration fields from card registration/edit payloads:

- On create, the backend inherits the shared configuration when both configuration fields are omitted and existing entries are uniform. First cards retain the existing `standard` / `classic` defaults. The read and insert occur under the existing submission lock/version check.
- Existing identification/quantity/card-note edits continue preserving omitted configuration fields, including historical exceptions.
- Explicit legacy per-entry configuration values remain supported. If a create caller supplies either configuration field explicitly, the other retains its previous schema-default behavior rather than being unexpectedly inherited. Per-entry configuration PATCH remains available.
- For a mixed legacy draft, the old API’s omitted-field create defaults remain compatible; the V1 portal itself disables adding a new entry until the mixed draft is explicitly converted. No automatic normalization is performed on reads.

Configuration persistence across refresh/navigation therefore uses PostgreSQL entry values. If every entry is deleted, no order-wide preference remains to inherit: a subsequent first card uses the existing defaults. Choosing services for an empty order is intentionally disabled; its order notes can still be saved.

## Explicit compatibility policy for mixed legacy drafts

A mixed configuration includes differences in processing speed **or any upgrade**, not only label style, so historical extra options cannot be discarded unnoticed.

- Display each existing entry’s configuration read-only, with a clear mixed-draft warning.
- Keep the single global selector pair disabled until the customer checks **I want to replace the existing configuration of every card with these choices**. Checking the box alone sends no request.
- While unchecked, the same order form offers **Save order notes**. This calls the existing notes PATCH and preserves every per-card exception. Identification/card-note edits and explicit card removal also remain available.
- Block new card creation, V1 quote generation and V1 review/confirmation while the draft remains mixed. This prevents the new journey from presenting conflicting choices as a single order configuration.
- After explicit opt-in, the customer can choose the one configuration and save it with order notes. The existing apply-to-all endpoint replaces draft configurations only at that explicit save. Existing immutable quote snapshots retain their former contents; stale quotes are invalidated.
- A confirmed legacy mixed submission is never converted. Its values remain read-only, and the existing backend can continue pricing its actual historical per-entry configurations rather than inventing a uniform configuration.

This is a V1 customer-journey policy. Existing authenticated per-entry APIs and legacy mixed quote/confirmation capabilities are retained for compatibility/future use. The old apply-to-all API remains an explicit replacement operation; it does not acquire a new mandatory acknowledgement field that would break existing clients. No migration rewrites historical exceptions. After an explicit conversion, V1 offers no per-card editor to restore exceptions; that capability remains in the backend.

## Notes and atomic saves

Card notes use entry `notes`, are labeled by scope and are saved once with that card. Order notes use submission `notes` and appear in one order textarea (`order_notes` in the DOM). The redundant standalone submission-note form/save was removed.

`PATCH /api/submissions/{uuid}/configuration` now accepts optional `notes` alongside its existing `version`, `processing_tier` and `upgrade_ids`. The server validates all input/options before saving notes and all entry configurations in one versioned transaction. Omitting `notes` preserves existing order notes for older clients; explicitly sending an empty string clears them. Card notes are never overwritten by this operation. The per-entry configuration schema/route is unchanged.

The existing `PATCH /api/submissions/{uuid}` remains available for notes-only saves: unavailable pricing, no saved cards, or an unconverted mixed draft. Those saves do not modify configurations. The order form uses the appropriate endpoint automatically, with one clearly labeled save action for the information being saved.

## Pricing, immutability and concurrent changes

The price engine, commercial catalog files, fees, tax rules, shipping readiness and acceptance/payment restrictions are unchanged. Saving settings or notes advances the existing pricing revision; old quotes become invalidated without changing their snapshots. New quotes use the persisted effective configuration for every physical quantity. New entries inherit it and naturally invalidate prior quantity-based quotes.

The UI blocks review/quote actions while order settings are unsaved or a save is in flight. Existing server submission locks and optimistic versions prevent stale writes from silently overwriting concurrent work. Confirmation retains its immutable guard; configuration/notes writes to a submitted order remain rejected. Confirmed legacy mixed values and accepted quote snapshots remain unchanged.

## Files and local use

Production changes:

- `frontend/src/components/submissions.tsx`: identification-only registration, scoped card notes, no separate order-note form, review after order/return preparation, mixed-draft progression guard.
- `frontend/src/components/pricing-panel.tsx`: one order form, persisted initial values, order notes, explicit legacy conversion, notes-only fallback and read-only historical display; removed the registration configuration renderer and individual editable forms.
- `frontend/src/lib/pricing.ts`, `submissions.ts`: shared-configuration detection and FR/EN scope/policy messages.
- `backend/app/submissions.py`, `pricing.py`: inheritance only for compatible omitted-field creates, without mutating legacy values.
- `backend/app/pricing_api.py`: backward-compatible optional order notes on the global configuration operation.

Use the normal local FastAPI/PostgreSQL/Next setup. No new dependency or migration is required. Deploying a new portal against an older backend would reject the newly supplied `notes` field on global configuration, so roll out compatible backend code before this UI. No deployment or production-data modification was performed.

Actual checks, browser steps and limitations are in `SELBY_ORDER_CONFIGURATION_UX_V1_VALIDATION.md`.
