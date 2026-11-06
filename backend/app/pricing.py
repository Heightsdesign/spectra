"""Deterministic minor-unit pricing and catalog validation, without payments."""
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.pricing_models import PricingCatalog, PricingState
from app.pricing_schemas import Catalog


def common_configuration(cards):
    """No persisted defaults or implicit normalization of historical exceptions."""
    if not cards:
        return None
    first = cards[0]
    if any(card.processing_tier != first.processing_tier or sorted(card.upgrade_ids) != sorted(first.upgrade_ids) for card in cards):
        return None
    return {'processing_tier': first.processing_tier, 'upgrade_ids': list(first.upgrade_ids)}


def current_catalog(db, settings, required=True):
    # Publisher takes FOR UPDATE on this singleton. Keep a shared lock through
    # calculation/acceptance so a price publication cannot interleave with it.
    state = db.scalar(select(PricingState).where(PricingState.id == 1).with_for_update(read=True).execution_options(populate_existing=True))
    record = db.get(PricingCatalog, state.current_version) if state and state.current_version else None
    if record is None:
        if required:
            raise HTTPException(503, "pricing_unavailable")
        return None
    try:
        catalog = Catalog.model_validate(record.document)
    except ValidationError:
        raise HTTPException(503, "pricing_unavailable") from None
    if settings.auth_environment == "production" and catalog.development_only:
        raise HTTPException(503, "pricing_unavailable")
    from app.fictitious_checkout import require_scope
    require_scope(catalog.model_dump(), settings)
    return record, catalog


def validate_options(catalog, tier_id, upgrade_ids):
    tier = catalog.tiers.get(tier_id)
    if tier is None or not tier.available:
        raise HTTPException(422, "option_unavailable")
    if len(upgrade_ids) != len(set(upgrade_ids)):
        raise HTTPException(422, "options_incompatible")
    counts = {key: 0 for key in catalog.groups}
    for key in upgrade_ids:
        upgrade = catalog.upgrades.get(key)
        if upgrade is None or not upgrade.available:
            raise HTTPException(422, "option_unavailable")
        if (upgrade.allowed_tiers is not None and tier_id not in upgrade.allowed_tiers) or set(upgrade.incompatible_with).intersection(upgrade_ids):
            raise HTTPException(422, "options_incompatible")
        counts[upgrade.group] += 1
    if any(not group.min_selected <= counts[key] <= group.max_selected for key, group in catalog.groups.items()):
        raise HTTPException(422, "options_incompatible")


def validate_selection(db, settings, tier_id, upgrade_ids, required=True):
    configured = current_catalog(db, settings, required=required)
    if configured:
        if not required and tier_id == "":
            return  # Internal draft placeholder; explicit identifiers are validated by schemas.
        validate_options(configured[1], tier_id, upgrade_ids)
    elif tier_id != "standard" or upgrade_ids != ["classic"]:
        raise HTTPException(503, "pricing_unavailable")


def rounded_ratio(amount, numerator, denominator=10_000):
    return int((Decimal(amount) * Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def calculate(catalog: Catalog, cards):
    """Highest eligible quantity threshold wins; discounts never stack.

    Eligibility counts all physical cards. Round discount and tax once per entry
    using HALF_UP, then sum the rounded lines (including inclusive tax extraction).
    """
    quantity = sum(card.quantity for card in cards)
    brackets = [p for p in catalog.volume_prices if quantity >= p.min_quantity]
    bracket = max(brackets, key=lambda p: p.min_quantity) if brackets else None
    eligible = [rule for rule in catalog.discounts if quantity >= rule.min_quantity]
    rule = max(eligible, key=lambda d: d.min_quantity) if eligible else None
    lines = []
    for card in cards:
        validate_options(catalog, card.processing_tier, card.upgrade_ids)
        tier = catalog.tiers[card.processing_tier]
        upgrades = [{"id": key, "name": catalog.upgrades[key].name.model_dump(),
                     "description": catalog.upgrades[key].description.model_dump(),
                     "unit_minor": catalog.upgrades[key].price_minor,
                     "label_presentation": catalog.upgrades[key].label_presentation.model_dump() if catalog.upgrades[key].label_presentation else None} for key in sorted(card.upgrade_ids)]
        service_price = tier.price_minor if tier.price_minor is not None else catalog.base_price_minor
        speed_price = 0 if tier.price_minor is not None else tier.price_adjustment_minor
        unit = service_price + speed_price + sum(u["unit_minor"] for u in upgrades)
        subtotal = unit * card.quantity
        basis = (catalog.base_price_minor if catalog.discount_scope == "base" else unit) * card.quantity
        discount = ((catalog.base_price_minor - bracket.unit_price_minor) * card.quantity if bracket else
                    rounded_ratio(basis, rule.rate_bps) if rule else 0)
        discounted = subtotal - discount
        tax_mode = tier.tax.mode if tier.tax else catalog.tax_mode
        tax_rate = tier.tax.rate_bps if tier.tax else catalog.tax_rate_bps
        if tax_mode == "inclusive":
            tax = rounded_ratio(discounted, tax_rate, 10_000 + tax_rate)
            net, total = discounted - tax, discounted
        else:
            tax = rounded_ratio(discounted, tax_rate) if tax_mode == "exclusive" else 0
            net, total = discounted, discounted + tax
        lines.append({
            "entry_id": str(card.id), "card_name": card.card_name,
            "entry": {key: getattr(card, key) for key in ("game", "card_name", "expansion", "card_number", "language", "quantity", "notes")},
            "quantity": card.quantity, "processing_tier": card.processing_tier,
            "tier_name": tier.name.model_dump(), "tier_description": tier.description.model_dump(),
            "estimated_turnaround": tier.estimated_turnaround.model_dump() if tier.estimated_turnaround else None,
            "service_id": card.processing_tier, "service": tier.model_dump(),
            "service_unit_minor": service_price, "tax_mode": tax_mode, "tax_rate_bps": tax_rate,
            "tax_validation_reference": tier.tax.validation_reference if tier.tax else catalog.tax_validation_reference,
            "card_keys": [f"{card.id}:{i}" for i in range(1, card.quantity + 1)],
            "base_unit_minor": service_price,
            "base_minor": service_price * card.quantity,
            "speed_minor": speed_price * card.quantity,
            "upgrades_minor": sum(u["unit_minor"] for u in upgrades) * card.quantity,
            "volume_base_unit_minor": bracket.unit_price_minor if bracket else catalog.base_price_minor,
            "speed_unit_minor": speed_price, "upgrades": upgrades,
            "unit_minor": unit, "subtotal_minor": subtotal, "discount_basis_minor": basis,
            "discount_minor": discount, "net_minor": net, "tax_minor": tax, "total_minor": total,
        })
    return {
        "currency": catalog.currency, "development_only": catalog.development_only,
        "stripe_test_only": catalog.stripe_test_only,
        "commercial_terms_version": catalog.commercial_terms_version,
        "quote_schema_version": 2, "per_service_tax": catalog.schema_version == 2,
        "tax_breakdown": [dict(entry_id=line["entry_id"], mode=line["tax_mode"], rate_bps=line["tax_rate_bps"], net_minor=line["net_minor"], tax_minor=line["tax_minor"], total_minor=line["total_minor"]) for line in lines],
        "configuration": catalog.model_dump(), "quantity": quantity, "lines": lines,
        "discount": rule.model_dump() if rule else None, "discount_scope": catalog.discount_scope,
        "volume_bracket": bracket.model_dump() if bracket else None,
        "tax_mode": catalog.tax_mode, "tax_rate_bps": catalog.tax_rate_bps,
        "tax_description": catalog.tax_description.model_dump(),
        **{key: sum(line[key] for line in lines) for key in ("base_minor", "speed_minor", "upgrades_minor", "subtotal_minor", "discount_minor", "net_minor", "tax_minor", "total_minor")},
    }
