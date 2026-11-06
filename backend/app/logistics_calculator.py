"""Pure Colissimo calculation; no transport, payment or label side effects."""
from datetime import datetime

from app.logistics_schemas import (
    ColissimoCatalog, LogisticsSelection, PREPARATORY_RETURN_MINIMUM_MINOR,
)


def catalog_issues(catalog: ColissimoCatalog):
    issues = []
    for key in ('period', 'contract_reference', 'documents', 'validation_reference',
                'future_cost_commitment_reference', 'return_minimum_validation_reference',
                'selby_address', 'zones', 'products'):
        if not getattr(catalog, key):
            issues.append('catalog_' + key + '_required')
    if catalog.return_minimum_minor is None or catalog.return_minimum_minor < PREPARATORY_RETURN_MINIMUM_MINOR:
        issues.append('contractual_return_minimum_required')
    if {p.direction for p in catalog.products.values()} != {'inbound', 'return'}:
        issues.append('both_transport_directions_required')
    for zone in catalog.zones.values():
        if not zone.validation_reference:
            issues.append('zone_validation_required')
    charges = []
    for product in catalog.products.values():
        if not all((product.carrier_product_code, product.eligible_categories,
                    product.eligibility_reference, product.weight_rule_reference,
                    product.dimension_reference, product.max_length_mm,
                    product.max_width_mm, product.max_height_mm, product.bands)):
            issues.append('product_contract_incomplete')
        if product.uninsured_allowed and not product.uninsured_reference:
            issues.append('uninsured_permission_required')
        if product.direction == 'return' and not any(catalog.coverages[k].level == 'minimum' for k in product.coverage_ids):
            issues.append('return_minimum_option_required')
        for band in product.bands:
            if not band.source_reference:
                issues.append('weight_band_source_required')
            charges.extend([band.transport, *band.supplements.values()])
    for coverage in catalog.coverages.values():
        if coverage.total_limit_minor is None or not all((coverage.eligible_categories,
                                                         coverage.eligibility_reference,
                                                         coverage.conditions_reference)):
            issues.append('coverage_contract_incomplete')
        if coverage.level == 'extra' and not coverage.incremental_premium_reference:
            issues.append('incremental_premium_validation_required')
        if not coverage.included_in_transport:
            if coverage.premium is None:
                issues.append('coverage_premium_required')
            else:
                charges.append(coverage.premium)
    for charge in charges:
        if charge.amount_minor is None:
            issues.append('logistics_price_missing')
        if charge.tax is None:
            issues.append('logistics_tax_unvalidated')
        if not charge.source_reference or not charge.cost_basis_reference:
            issues.append('logistics_cost_basis_unvalidated')
    return sorted(set(issues))


def calculate_logistics(catalog: ColissimoCatalog, selection: LogisticsSelection,
                        *, at: datetime, expected_card_keys: list[str]):
    """Integer grams inclusive bands; unsupported contracts fail closed.

    Caller supplies the calculation instant and actual submission inventory.
    The preparatory EUR 150 floor never supplies missing contract evidence.
    """
    if at.tzinfo is None:
        raise ValueError('Calculation instant must be timezone-aware')
    issues = catalog_issues(catalog)
    lines, included, trace = [], [], []
    if catalog.period is None or not catalog.period.start <= at < catalog.period.end:
        issues.append('logistics_catalog_outside_validity')
    if not expected_card_keys or set(expected_card_keys) != {i.card_key for i in selection.items}:
        issues.append('logistics_inventory_incomplete')
    if selection.selby_destination != catalog.selby_address or catalog.selby_address is None:
        issues.append('selby_address_mismatch')

    def zone_for(address):
        if address is None or address.country != 'FR':
            return None
        matches = [k for k, z in catalog.zones.items() if address.postal_code in z.postal_codes]
        return matches[0] if len(matches) == 1 else None

    def add_charge(kind, key, charge, direction):
        if charge is None or charge.amount_minor is None or charge.tax is None or not charge.source_reference or not charge.cost_basis_reference:
            issues.append('logistics_charge_unvalidated')
            return
        # Same function as legacy shipping, same HALF_UP integer conventions.
        from app.checkout import shipping_amounts
        amounts = shipping_amounts(charge.amount_minor, charge.tax.mode, charge.tax.rate_bps)
        lines.append({'kind': kind, 'id': f'{direction}:{key}', 'direction': direction,
                      'name': charge.name.model_dump(), **amounts,
                      'total_minor': amounts['charge_minor'], 'tax_mode': charge.tax.mode,
                      'tax_rate_bps': charge.tax.rate_bps,
                      'tax_validation_reference': charge.tax.validation_reference,
                      'source_reference': charge.source_reference,
                      'cost_basis_reference': charge.cost_basis_reference})

    for direction, leg, origin, destination in [
        ('inbound', selection.inbound, selection.customer_origin, selection.selby_destination),
        ('return', selection.return_leg, selection.selby_destination, selection.customer_return),
    ]:
        origin_zone, destination_zone = zone_for(origin), zone_for(destination)
        if origin_zone is None or destination_zone is None:
            issues.append(direction + '_metropolitan_address_required')
        product = catalog.products.get(leg.product_id)
        if product is None or product.direction != direction:
            issues.append(direction + '_product_required')
            continue
        if any(item.category not in product.eligible_categories for item in selection.items):
            issues.append(direction + '_goods_ineligible')
        parcel = leg.parcel.model_dump()
        if any(value is None for value in parcel.values()):
            issues.append(direction + '_parcel_incomplete')
        if direction == 'return' and not leg.packing_profile_id:
            issues.append('return_packing_profile_required')
        if leg.packing_profile_id:
            profile = catalog.packing_profiles.get(leg.packing_profile_id)
            if (profile is None or profile.direction != direction or not profile.validation_reference
                    or profile.parcel != leg.parcel or profile.card_count != len(expected_card_keys)
                    or any(i.category not in profile.eligible_categories for i in selection.items)):
                issues.append(direction + '_packing_profile_mismatch')
        for dimension in ('length_mm', 'width_mm', 'height_mm'):
            limit = getattr(product, 'max_' + dimension)
            if limit is None or parcel[dimension] is None or parcel[dimension] > limit:
                issues.append(direction + '_dimensions_unsupported')
        weight = parcel['weight_g']
        bands = [b for b in product.bands if b.origin_zone == origin_zone
                 and b.destination_zone == destination_zone and weight is not None
                 and b.min_weight_g <= weight <= b.max_weight_g]
        if len(bands) != 1:
            issues.append(direction + '_weight_rate_missing')
        else:
            band = bands[0]
            add_charge(direction + '_transport', 'transport', band.transport, direction)
            for key, charge in sorted(band.supplements.items()):
                add_charge(direction + '_contract_supplement', 'supplement:' + key, charge, direction)
            trace.append({'direction': direction, 'product_id': leg.product_id,
                          'origin_zone': origin_zone, 'destination_zone': destination_zone,
                          'band_id': band.id, 'min_weight_g_inclusive': band.min_weight_g,
                          'max_weight_g_inclusive': band.max_weight_g, 'parcel': parcel,
                          'packing_profile_id': leg.packing_profile_id,
                          'source_reference': band.source_reference})

        minimum = catalog.coverages.get(leg.minimum_coverage_id)
        extra = catalog.coverages.get(leg.extra_coverage_id)
        if direction == 'return' and minimum is None:
            issues.append('return_minimum_coverage_required')
        if minimum is None and extra is None and direction == 'inbound' and not (product.uninsured_allowed and product.uninsured_reference):
            issues.append('inbound_coverage_choice_required')
        for key, coverage, level in [(leg.minimum_coverage_id, minimum, 'minimum'), (leg.extra_coverage_id, extra, 'extra')]:
            if key is None:
                continue
            if coverage is None or key not in product.coverage_ids or coverage.direction != direction or coverage.level != level:
                issues.append(direction + '_coverage_option_invalid')
                continue
            if any(i.category not in coverage.eligible_categories for i in selection.items):
                issues.append(direction + '_coverage_goods_ineligible')
            if level == 'minimum' and direction == 'return' and (coverage.total_limit_minor is None
                    or catalog.return_minimum_minor is None or coverage.total_limit_minor < catalog.return_minimum_minor):
                issues.append('return_minimum_coverage_insufficient')
            if coverage.included_in_transport:
                included.append({'direction': direction, 'coverage_id': key, 'level': level,
                                 'included_in_transport': True,
                                 'conditions_reference': coverage.conditions_reference})
            else:
                kind = 'return_required_coverage' if direction == 'return' and level == 'minimum' else direction + '_extra_coverage'
                add_charge(kind, 'coverage:' + key, coverage.premium, direction)
        effective = extra or minimum
        if effective:
            values = [getattr(i, direction + '_value_minor') for i in selection.items]
            if effective.total_limit_minor is None or sum(values) > effective.total_limit_minor or (effective.per_item_limit_minor is not None and any(v > effective.per_item_limit_minor for v in values)):
                issues.append(direction + '_declared_value_uncovered')
            if extra and minimum and (extra.total_limit_minor is None or minimum.total_limit_minor is None or extra.total_limit_minor < minimum.total_limit_minor):
                issues.append(direction + '_extra_coverage_below_minimum')

    issues = sorted(set(issues))
    return {'schema_version': 1, 'calculator_version': 'colissimo-c1-v1',
            'currency': 'EUR', 'calculated_at': at.isoformat(),
            'preparatory_return_minimum_minor': PREPARATORY_RETURN_MINIMUM_MINOR,
            'contractual_return_minimum_minor': catalog.return_minimum_minor,
            'ready': not issues, 'issues': issues, 'line_items': lines,
            'included_services': included, 'trace': trace,
            'net_total_minor': sum(x['net_minor'] for x in lines) if not issues else None,
            'tax_total_minor': sum(x['tax_minor'] for x in lines) if not issues else None,
            'total_minor': sum(x['charge_minor'] for x in lines) if not issues else None}


def commercial_preview(grading, logistics):
    """One aggregation boundary; no obligation or payable state is created here."""
    if not grading or not logistics['ready'] or any(
        line['tax_mode'] == 'pending' or not line['tax_validation_reference']
        for line in grading['lines']
    ):
        return None
    return {key: grading[source] + logistics[key] for key, source in [
        ('total_minor', 'total_minor'), ('net_total_minor', 'net_minor'),
        ('tax_total_minor', 'tax_minor')]}
