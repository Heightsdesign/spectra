# SELBY V0.6a — configuration contracts

No new commercial configuration was published. Existing documents are retained; accepted snapshots are never rewritten. New service names, prices, tax assertions, turnaround wording, shipping rates, coverage and terms require approval before commercial use.

## Service catalog

Machine-readable contract: [service-catalog.schema.json](backend/pricing/service-catalog.schema.json). Validation model: `app.pricing_schemas.Catalog`. Use **schema_version: 2** for the new absolute-service-price format; version 1 remains supported for existing catalogs.

| Field | Meaning |
| --- | --- |
| `tiers` dictionary key | Stable internal service identifier, lowercase identifier grammar; persisted as existing `processing_tier` |
| `name`, `description` | Public FR/EN text, both required |
| `price_minor` | Absolute configured service unit price in integer EUR minor units |
| `available` | Active/inactive; unavailable and unknown identifiers cannot be selected for quoting/confirmation |
| `estimated_turnaround` | Optional FR/EN advertised target; no default promise |
| `tax.mode` | `inclusive`, `exclusive`, `exempt` or `pending` |
| `tax.rate_bps` | Explicit tax rate in basis points; exempt requires zero |
| `tax.validation_reference` | Approved tax-treatment evidence reference, required before publication |
| `commercial_terms_version` | Required for a complete acceptable quote; no default terms are invented |
| `development_only` | Development catalogs cannot be accepted commercially or published in production |
| `approval_reference` | Required for a non-development catalog; approval is an operator governance responsibility |
| Published catalog UUID | Assigned by existing immutable `PricingCatalog`; shared by all service lines in that quote |

The existing `base_price_minor`, `price_adjustment_minor`, aggregate tax-description fields, label groups and upgrades remain in the schema for compatibility. For schema 2, service prices replace the legacy base-plus-speed calculation; legacy volume prices/discounts cannot be mixed into this format. Existing upgrades are added to the selected service and use that service's explicit tax treatment. The global legacy tax mode is not used to tax schema-2 service lines. No upgrade-specific alternative tax rule is assumed.

A grouped entry's selected service applies to each declared copy in its quantity. Identical cards with different services use separate entries; the library already represents individual customer copies as separate entries. New-schema drafts without an explicit/inherited service retain an internal empty selection and cannot be quoted or confirmed. Customers cannot submit an empty identifier through the configuration API or inject prices/taxes.

Publication validates every service's explicit tax treatment, records a new immutable catalog, and changes only the current-version pointer under a lock. It does not update accepted terms. Optional turnaround text is preserved as approved text; the system makes no delivery guarantee from it.

From `backend`:

```powershell
.venv/Scripts/python.exe -m app.pricing_catalog validate path/to/approved-catalog.json
.venv/Scripts/python.exe -m app.pricing_catalog publish path/to/approved-catalog.json
```

`validate` does not publish. A syntactically valid document with pending tax is reported as non-publishable. A nonempty approved terms version is also required at checkout, even if the catalog is otherwise publishable. No sample document with invented commercial service values is supplied; tests contain clearly synthetic fixtures.

## Return shipping policy

Machine-readable contract: [return-shipping.schema.json](backend/pricing/return-shipping.schema.json). Validation model: `app.checkout_schemas.ShippingCatalog`. Existing operator CLI and immutable `ShippingConfiguration` versioning are reused.

| Field | Meaning |
| --- | --- |
| `currency` | EUR only |
| `supported_destinations`, service `countries` | Explicit allowed ISO destination countries |
| Service dictionary key, `name` | Stable selected return service and public FR/EN name |
| `zone` | Optional policy zone identifier, captured in pricing inputs |
| `charge_minor` | Required configured initial return price; omission is invalid, not zero |
| `available`, `tracked` | Service availability and tracking requirement; untracked rates do not pass existing checkout policy |
| `trading_cards_coverage_verified`, `coverage_reference` | Explicit verified coverage assertion and supporting evidence; no actual coverage is supplied by the application |
| `coverage_minor`, `coverage`, `exclusions` | Approved declared-value limit and customer-facing explanation |
| `phone_required` | Destination contact requirement |
| `min_cards`, `max_cards` | Supported parcel/card-count range; no business threshold is supplied by this delivery |
| `max_weight_g`, `max_length_mm`, `max_width_mm`, `max_height_mm` | Optional parcel requirements. If configured, required measurements must be provided and within bounds |
| `tax_mode`, `tax_rate_bps`, `tax_validation_reference` | Explicit inclusive/exclusive/exempt shipping tax treatment |
| `additional_card_charge_minor` | Optional approved incremental per-additional-card charge for this same return service; null means supplementary pricing is unavailable. Explicit zero is possible only through configuration |
| `receiving_address` | Customer instructions once approved/configured; not synthesized |

Initial checkout requires the selected destination, declared value, eligible service, coverage, tracking, applicable parcel inputs, service tax and reliable price. Any unresolved requirement leaves the payable total null and acceptance blocked. Flat/card-count rules and size-dependent services can be represented through explicit service/range configurations; no carrier API or inferred shipping/insurance estimate is used.

Supplementary pricing reevaluates the total original-plus-accepted-additional declared value and card count, using explicit staff-provided parcel inputs. It requires a configured incremental rate and preserves the original destination. A different shipping service requires review instead of assuming a price delta. Competing unaccepted supplementary quotes become stale after another supplement is accepted. Original paid shipping is never changed.

From `backend`:

```powershell
.venv/Scripts/python.exe -m app.shipping_catalog validate path/to/approved-shipping.json
.venv/Scripts/python.exe -m app.shipping_catalog publish path/to/approved-shipping.json
```

The existing `shipping-unconfigured.json` remains a safe unavailable policy. It is not replaced with an invented zero rate. New configuration versions do not change accepted destinations, prices or coverage snapshots.

## Dispatch policy configuration

The operational window is fixed at the confirmed 30 calendar days after verified initial payment. V0.6a uses UTC and preserves the verified time of day; approve the customer-facing cutoff/timezone wording in the terms before launch. The optional environment setting `DISPATCH_REMINDER_LEAD_DAYS` selects a reminder lead of 1–30 days. Unset means no approaching reminder candidate; passed-deadline and receipt indicators remain available. This setting creates no scheduler or messages.
