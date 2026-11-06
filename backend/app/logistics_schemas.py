"""Colissimo C1 contracts. No real tariffs, tax rates or guarantees are defaults."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.auth_schemas import Payload
from app.checkout_schemas import Address, Parcel
from app.pricing_schemas import BasisPoints, Identifier, Localized, Minor

Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
PostalCode = Annotated[str, StringConstraints(pattern=r"^[0-9]{5}$")]
Positive = Annotated[int, Field(strict=True, ge=1, le=100_000_000)]
Direction = Literal['inbound', 'return']
PREPARATORY_RETURN_MINIMUM_MINOR = 15_000  # User hypothesis only, not a carrier guarantee.


class Period(Payload):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode='after')
    def ordered(self):
        if self.start >= self.end:
            raise ValueError('Invalid validity period')
        return self


class Evidence(Payload):
    reference: Reference
    sha256: Annotated[str, StringConstraints(pattern=r'^[0-9a-f]{64}$')]


class Tax(Payload):
    mode: Literal['inclusive', 'exclusive', 'exempt']
    rate_bps: BasisPoints
    validation_reference: Reference

    @model_validator(mode='after')
    def exempt(self):
        if self.mode == 'exempt' and self.rate_bps:
            raise ValueError('Exemption requires zero tax rate')
        return self


class Charge(Payload):
    name: Localized
    amount_minor: Minor | None = None
    tax: Tax | None = None
    source_reference: Reference | None = None
    cost_basis_reference: Reference | None = None


class Zone(Payload):
    territory: Literal['FR_METROPOLITAN'] = 'FR_METROPOLITAN'
    postal_codes: list[PostalCode] = Field(min_length=1, max_length=10000)
    validation_reference: Reference | None = None

    @model_validator(mode='after')
    def unique(self):
        if any(code.startswith(('97', '98')) for code in self.postal_codes):
            raise ValueError('Only metropolitan postal codes may be configured')
        if len(set(self.postal_codes)) != len(self.postal_codes):
            raise ValueError('Duplicate postal code')
        return self


class WeightBand(Payload):
    id: Identifier
    origin_zone: Identifier
    destination_zone: Identifier
    min_weight_g: Positive
    max_weight_g: Positive
    transport: Charge
    supplements: dict[Identifier, Charge] = Field(default_factory=dict, max_length=32)
    source_reference: Reference | None = None

    @model_validator(mode='after')
    def ordered(self):
        if self.min_weight_g > self.max_weight_g:
            raise ValueError('Invalid inclusive weight bounds')
        return self


class Coverage(Payload):
    direction: Direction
    level: Literal['minimum', 'extra']
    # Extra limit is the TOTAL replacement limit; never added to the minimum.
    total_limit_minor: Minor | None = None
    per_item_limit_minor: Minor | None = None
    eligible_categories: list[Identifier] = Field(default_factory=list, max_length=64)
    eligibility_reference: Reference | None = None
    conditions_reference: Reference | None = None
    included_in_transport: bool = Field(default=False, strict=True)
    premium: Charge | None = None
    incremental_premium_reference: Reference | None = None

    @model_validator(mode='after')
    def included(self):
        if self.included_in_transport and self.premium is not None:
            raise ValueError('Included coverage cannot be charged again')
        return self


class Product(Payload):
    direction: Direction
    name: Localized
    carrier_product_code: Reference | None = None
    signature: bool = Field(strict=True)
    delivery_mode: Literal['domicile', 'contractual_inbound']
    eligible_categories: list[Identifier] = Field(default_factory=list, max_length=64)
    eligibility_reference: Reference | None = None
    # Only exact integer grams supported; no invented rounding/volumetric rule.
    weight_rule: Literal['exact_grams'] = 'exact_grams'
    weight_rule_reference: Reference | None = None
    max_length_mm: Positive | None = None
    max_width_mm: Positive | None = None
    max_height_mm: Positive | None = None
    dimension_reference: Reference | None = None
    bands: list[WeightBand] = Field(default_factory=list, max_length=256)
    coverage_ids: list[Identifier] = Field(default_factory=list, max_length=64)
    uninsured_allowed: bool = Field(default=False, strict=True)
    uninsured_reference: Reference | None = None

    @model_validator(mode='after')
    def coherent(self):
        if self.direction == 'return' and (not self.signature or self.delivery_mode != 'domicile' or self.uninsured_allowed):
            raise ValueError('Return requires Domicile with signature and coverage')
        if len({b.id for b in self.bands}) != len(self.bands):
            raise ValueError('Duplicate weight band')
        for i, a in enumerate(self.bands):
            for b in self.bands[i + 1:]:
                if (a.origin_zone, a.destination_zone) == (b.origin_zone, b.destination_zone) and max(a.min_weight_g, b.min_weight_g) <= min(a.max_weight_g, b.max_weight_g):
                    raise ValueError('Overlapping inclusive weight bands')
        return self


class PackingProfile(Payload):
    reference: Reference
    direction: Direction
    parcel: Parcel
    card_count: Positive
    eligible_categories: list[Identifier] = Field(min_length=1, max_length=64)
    validation_reference: Reference | None = None


class ColissimoCatalog(Payload):
    schema_version: Literal[1] = 1
    carrier: Literal['colissimo'] = 'colissimo'
    currency: Literal['EUR'] = 'EUR'
    provenance: Literal['provisional', 'synthetic_test', 'contractual'] = 'provisional'
    period: Period | None = None
    contract_reference: Reference | None = None
    documents: list[Evidence] = Field(default_factory=list, max_length=64)
    validation_reference: Reference | None = None
    future_cost_commitment_reference: Reference | None = None
    return_minimum_minor: Minor | None = None
    return_minimum_validation_reference: Reference | None = None
    selby_address: Address | None = None
    zones: dict[Identifier, Zone] = Field(default_factory=dict, max_length=64)
    products: dict[Identifier, Product] = Field(default_factory=dict, max_length=32)
    coverages: dict[Identifier, Coverage] = Field(default_factory=dict, max_length=64)
    packing_profiles: dict[Identifier, PackingProfile] = Field(default_factory=dict, max_length=128)

    @model_validator(mode='after')
    def links(self):
        postals = [code for z in self.zones.values() for code in z.postal_codes]
        if len(set(postals)) != len(postals):
            raise ValueError('Geographical zones overlap')
        for product in self.products.values():
            for band in product.bands:
                if band.origin_zone not in self.zones or band.destination_zone not in self.zones:
                    raise ValueError('Unknown tariff zone')
            if len(set(product.coverage_ids)) != len(product.coverage_ids):
                raise ValueError('Duplicate coverage')
            for key in product.coverage_ids:
                if key not in self.coverages or self.coverages[key].direction != product.direction:
                    raise ValueError('Invalid product coverage')
        return self


class DeclaredItem(Payload):
    card_key: Reference
    category: Identifier
    inbound_value_minor: Minor
    return_value_minor: Minor


class LegSelection(Payload):
    product_id: Identifier | None = None
    parcel: Parcel = Field(default_factory=Parcel)
    packing_profile_id: Identifier | None = None
    minimum_coverage_id: Identifier | None = None
    extra_coverage_id: Identifier | None = None


class LogisticsSelection(Payload):
    catalog_version: UUID | None = None
    customer_origin: Address | None = None
    selby_destination: Address | None = None
    customer_return: Address | None = None
    items: list[DeclaredItem] = Field(default_factory=list, max_length=10000)
    inbound: LegSelection = Field(default_factory=LegSelection)
    return_leg: LegSelection = Field(default_factory=LegSelection)

    @model_validator(mode='after')
    def unique_items(self):
        if len({i.card_key for i in self.items}) != len(self.items):
            raise ValueError('Duplicate declared card')
        return self


class SelectionInput(Payload):
    version: int = Field(strict=True, ge=0)
    selection: LogisticsSelection
