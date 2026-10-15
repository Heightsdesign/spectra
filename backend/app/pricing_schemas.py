"""Validated operator configuration; no prices are supplied by customers."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.auth_schemas import Payload
from app.submission_schemas import Notes, ShortText, Version

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
Minor = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]
BasisPoints = Annotated[int, Field(strict=True, ge=0, le=10_000)]


class Localized(Payload):
    FR: Notes
    EN: Notes

    @model_validator(mode="after")
    def nonempty(self):
        if not self.FR or not self.EN:
            raise ValueError("Both translations must be nonempty")
        return self


class Tier(Payload):
    name: Localized
    description: Localized
    price_adjustment_minor: Minor
    estimated_turnaround: Localized | None = None
    available: bool = Field(strict=True)
    display_order: int = Field(strict=True, ge=0, le=10_000)


class LabelPresentation(Payload):
    position: Literal["front"]
    show_overall_grade: Literal[True]
    subgrades: list[Literal["centering", "corners", "edges", "surface"]] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def categories(self):
        if len(set(self.subgrades)) != 4:
            raise ValueError("All four subgrades must be displayed")
        return self


class Upgrade(Payload):
    name: Localized
    description: Localized
    price_minor: Minor
    group: Identifier
    available: bool = Field(strict=True)
    display_order: int = Field(strict=True, ge=0, le=10_000)
    incompatible_with: list[Identifier] = Field(default_factory=list, max_length=64)
    allowed_tiers: list[Identifier] | None = Field(default=None, min_length=1, max_length=64)
    label_presentation: LabelPresentation | None = None


class OptionGroup(Payload):
    min_selected: int = Field(strict=True, ge=0, le=16)
    max_selected: int = Field(strict=True, ge=1, le=16)


class Discount(Payload):
    id: Identifier
    min_quantity: int = Field(strict=True, ge=1, le=10_000)
    rate_bps: BasisPoints


class VolumePrice(Payload):
    id: Identifier
    min_quantity: int = Field(strict=True, ge=1, le=10_000)
    unit_price_minor: Minor


class Catalog(Payload):
    schema_version: Literal[1] = 1
    name: ShortText
    currency: Literal["EUR"] = "EUR"
    development_only: bool = Field(default=True, strict=True)
    approval_reference: ShortText | None = None
    base_price_minor: Minor
    tiers: dict[Identifier, Tier] = Field(min_length=1, max_length=64)
    upgrades: dict[Identifier, Upgrade] = Field(min_length=1, max_length=64)
    groups: dict[Identifier, OptionGroup] = Field(min_length=1, max_length=64)
    discounts: list[Discount] = Field(default_factory=list, max_length=100)
    volume_prices: list[VolumePrice] = Field(default_factory=list, max_length=100)
    customer_gross_prices: bool = Field(default=False, strict=True)
    tax_validation_reference: ShortText | None = None
    discount_scope: Literal["base", "all"] = "base"
    tax_mode: Literal["exclusive", "inclusive", "exempt", "pending"]
    tax_rate_bps: BasisPoints
    tax_description: Localized
    quote_lifetime_seconds: int = Field(strict=True, ge=60, le=604_800)

    @model_validator(mode="after")
    def consistent(self):
        if self.customer_gross_prices and self.tax_mode == "exclusive":
            raise ValueError("Customer-facing amounts require inclusive or explicitly exempt treatment")
        if self.volume_prices:
            thresholds = [p.min_quantity for p in self.volume_prices]
            if self.discounts or min(thresholds) != 1 or len(set(thresholds)) != len(thresholds) or len({p.id for p in self.volume_prices}) != len(thresholds):
                raise ValueError("Volume prices must start at one, be unique and cannot stack with discounts")
            if any(p.unit_price_minor > self.base_price_minor for p in self.volume_prices):
                raise ValueError("Volume price cannot exceed base price")
        if not self.development_only and not self.approval_reference:
            raise ValueError("Commercial catalogs require an operator approval reference")
        if self.tax_mode == "exempt" and self.tax_rate_bps:
            raise ValueError("Exempt catalog must have a zero tax rate")
        if "label" not in self.groups or self.groups["label"].min_selected != 1 or self.groups["label"].max_selected != 1:
            raise ValueError("Exactly one slab label is required")
        if any(g.min_selected > g.max_selected for g in self.groups.values()):
            raise ValueError("Invalid group selection limits")
        for key, upgrade in self.upgrades.items():
            if upgrade.group not in self.groups or any(i not in self.upgrades or i == key for i in upgrade.incompatible_with):
                raise ValueError("Invalid upgrade group or incompatibility")
            if upgrade.allowed_tiers and any(t not in self.tiers for t in upgrade.allowed_tiers):
                raise ValueError("Unknown allowed tier")
        classic = self.upgrades.get("classic")
        if classic is None or classic.group != "label" or classic.price_minor != 0:
            raise ValueError("Classic label must remain included")
        if len({d.min_quantity for d in self.discounts}) != len(self.discounts) or len({d.id for d in self.discounts}) != len(self.discounts):
            raise ValueError("Discount thresholds and identifiers must be unique")
        return self


class Configuration(Version):
    processing_tier: Identifier
    upgrade_ids: list[Identifier] = Field(min_length=1, max_length=16)
