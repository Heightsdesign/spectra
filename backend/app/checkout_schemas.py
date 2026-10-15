from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.auth_schemas import Payload
from app.pricing_schemas import BasisPoints, Identifier, Localized, Minor
from app.submission_schemas import ShortText, Text

# ISO 3166-1 alpha-2, independent of the configurable shipping destinations.
COUNTRIES = set("AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW".split())
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200, pattern=r"^[^\x00-\x1f\x7f]*$")]
Country = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]


class Address(Payload):
    recipient: Text
    line1: Text
    line2: OptionalText = ""
    postal_code: Annotated[OptionalText, Field(max_length=32)] = ""
    city: Annotated[Text, Field(max_length=100)]
    country: Country
    phone: Annotated[str, StringConstraints(strip_whitespace=True, max_length=32, pattern=r"^[+0-9 ().-]*$")] = ""
    instructions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000, pattern=r"^[^\x00-\x1f\x7f]*$")] = ""

    @field_validator("country")
    @classmethod
    def iso_country(cls, value):
        if value not in COUNTRIES:
            raise ValueError("Unknown ISO country")
        return value

    @field_validator("phone")
    @classmethod
    def phone_digits(cls, value):
        if value and not 7 <= sum(c.isdigit() for c in value) <= 15:
            raise ValueError("Provide a delivery phone with 7 to 15 digits")
        return value


class AddressUpdate(Address):
    version: int = Field(strict=True, ge=1)


class Parcel(Payload):
    weight_g: int | None = Field(default=None, strict=True, ge=1, le=100_000)
    length_mm: int | None = Field(default=None, strict=True, ge=1, le=5000)
    width_mm: int | None = Field(default=None, strict=True, ge=1, le=5000)
    height_mm: int | None = Field(default=None, strict=True, ge=1, le=5000)


class Delivery(Payload):
    version: int = Field(strict=True, ge=0)
    address_id: UUID | None
    declared_value_minor: Minor | None = None
    service_id: Identifier | None = None
    parcel: Parcel = Field(default_factory=Parcel)


class ShippingService(Payload):
    name: Localized
    available: bool = Field(strict=True)
    countries: list[Country] = Field(min_length=1, max_length=249)
    charge_minor: Minor
    tracked: bool = Field(strict=True)
    trading_cards_coverage_verified: bool = Field(strict=True)
    coverage_reference: ShortText | None = None
    coverage_minor: Minor
    coverage: Localized
    exclusions: Localized
    phone_required: bool = Field(strict=True)
    max_weight_g: int | None = Field(default=None, strict=True, ge=1, le=100_000)
    max_length_mm: int | None = Field(default=None, strict=True, ge=1, le=5000)
    max_width_mm: int | None = Field(default=None, strict=True, ge=1, le=5000)
    max_height_mm: int | None = Field(default=None, strict=True, ge=1, le=5000)
    tax_mode: Literal["inclusive", "exempt"]
    tax_rate_bps: BasisPoints
    tax_validation_reference: ShortText

    @model_validator(mode="after")
    def valid_coverage(self):
        if self.tax_mode == "exempt" and self.tax_rate_bps:
            raise ValueError("Exempt shipping requires a zero rate")
        if self.trading_cards_coverage_verified and not self.coverage_reference:
            raise ValueError("Verified coverage requires an evidence reference")
        return self


class ShippingCatalog(Payload):
    currency: Literal["EUR"] = "EUR"
    supported_destinations: list[Country] = Field(default_factory=list, max_length=249)
    receiving_address: OptionalText | None = None
    services: dict[Identifier, ShippingService] = Field(default_factory=dict, max_length=64)

    @model_validator(mode="after")
    def countries(self):
        if any(c not in COUNTRIES for c in self.supported_destinations) or any(c not in self.supported_destinations for s in self.services.values() for c in s.countries):
            raise ValueError("Unknown or unsupported destination")
        return self
