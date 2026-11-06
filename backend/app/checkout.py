"""Authoritative checkout readiness. Grading totals never imply a payable total."""
from sqlalchemy import select
from fastapi import HTTPException
from pydantic import ValidationError

from app.checkout_models import CustomerAddress, ShippingConfiguration, ShippingState, SubmissionDelivery
from app.checkout_schemas import Address, ShippingCatalog
from app.pricing import calculate, current_catalog, rounded_ratio
from app.submissions import entries


def address_snapshot(address):
    if address is None:
        return None
    return {"id": str(address.id), "version": address.version,
            **{field: getattr(address, field) for field in Address.model_fields}}


def shipping_config(db, settings=None):
    state = db.scalar(select(ShippingState).where(ShippingState.id == 1).with_for_update(read=True).execution_options(populate_existing=True))
    record = db.get(ShippingConfiguration, state.current_version) if state and state.current_version else None
    try:
        config = ShippingCatalog.model_validate(record.document) if record else ShippingCatalog()
        from app.fictitious_checkout import require_scope
        require_scope(config.model_dump(), settings)
        return record, config
    except ValidationError:
        raise HTTPException(503, "shipping_configuration_invalid") from None


def context(item, db, settings=None):
    from app.logistics import uses_logistics, logistics_context
    if uses_logistics(item, db, settings):
        return logistics_context(item, db)
    delivery = db.get(SubmissionDelivery, item.id, populate_existing=True)
    address = db.get(CustomerAddress, delivery.address_id, populate_existing=True) if delivery and delivery.address_id else None
    record, _ = shipping_config(db, settings)
    return {"delivery_version": delivery.version if delivery else 0,
            "address_id": str(address.id) if address else None,
            "address_version": address.version if address else None,
            "shipping_version": str(record.version) if record else None}


def summary(item, db, settings, configured=None):
    configured = configured or current_catalog(db, settings, required=False)
    cards = entries(item, db)
    pricing_problem = None
    try:
        grading = calculate(configured[1], cards) if configured and cards else None
    except HTTPException as exc:
        if exc.status_code != 422:
            raise
        grading = None
        pricing_problem = 'service_selection_required'

    from app.logistics import uses_logistics
    if uses_logistics(item, db, settings):
        from app.logistics import checkout_summary
        return checkout_summary(item, db, settings, grading, configured, pricing_problem)

    delivery = db.get(SubmissionDelivery, item.id, populate_existing=True)
    address = db.get(CustomerAddress, delivery.address_id, populate_existing=True) if delivery and delivery.address_id else None
    record, config = shipping_config(db, settings)
    states = [pricing_problem] if pricing_problem else []
    tax_ready = bool(grading and all(line["tax_mode"] != "pending" and line["tax_validation_reference"] for line in grading["lines"]))
    if not configured or not configured[1].commercial_terms_version:
        states.append("commercial_terms_pending")
    if not tax_ready:
        states.append("tax_configuration_pending")
    if configured and configured[1].development_only and not configured[1].stripe_test_only:
        states.append("development_rates")
    if not address:
        states.append("missing_return_address")
    elif address.country not in config.supported_destinations:
        states.append("unsupported_shipping_destination")
    service = config.services.get(delivery.service_id) if delivery and delivery.service_id else None
    eligible = bool(address and service and service.available and address.country in service.countries and service.tracked
                    and service.trading_cards_coverage_verified and service.coverage_reference)
    if eligible:
        if delivery.declared_value_minor is None or delivery.declared_value_minor > service.coverage_minor:
            states.append("declared_value_required_or_uncovered")
            eligible = False
        quantity = sum(c.quantity for c in cards)
        if quantity < service.min_cards or (service.max_cards is not None and quantity > service.max_cards):
            states.append("shipping_card_count_unsupported")
            eligible = False
        if service.phone_required and not address.phone:
            states.append("delivery_phone_required")
            eligible = False
        for field in ("weight_g", "length_mm", "width_mm", "height_mm"):
            maximum = getattr(service, f"max_{field}")
            if maximum is not None and (not delivery.parcel.get(field) or delivery.parcel[field] > maximum):
                if "parcel_requirements_pending" not in states:
                    states.append("parcel_requirements_pending")
                eligible = False
    if not eligible:
        states.append("shipping_price_pending")
    shipping = {"status": "configured" if eligible else "pending", "charge_minor": None,
                "service": None, "tax_minor": None, "net_minor": None}
    if eligible:
        shipping.update(shipping_amounts(service.charge_minor, service.tax_mode, service.tax_rate_bps),
                        tax_mode=service.tax_mode, tax_rate_bps=service.tax_rate_bps,
                        service={"id": delivery.service_id, **service.model_dump()})
    ready = not states and grading is not None
    total = grading["total_minor"] + shipping["charge_minor"] if ready else None
    tax_total = grading["tax_minor"] + shipping["tax_minor"] if ready else None
    return {"stripe_test_only": bool(config.stripe_test_only or (configured and configured[1].stripe_test_only)),
            "commercial_terms_version": configured[1].commercial_terms_version if configured else None,
            "payment": {"status": "unavailable", "charging_enabled": False},
            "dispatch_policy": {"calendar_days_after_verified_payment": 30, "timezone": "UTC", "automatic_forfeiture": False},
            "tax_total_minor": tax_total,
            "net_total_minor": total - tax_total if ready else None,
            "adjustments_minor": 0,
            "line_items": ([{"kind": "grading", **line} for line in grading["lines"]] if grading else []) + [{"kind": "return_shipping", **shipping}],
            "submission_reference": item.reference, "currency": "EUR", "quantity": sum(c.quantity for c in cards),
            "pricing_revision": str(configured[0].version) if configured else None,
            "grading": grading, "return_address": address_snapshot(address),
            "delivery": {"version": delivery.version if delivery else 0,
                         "address_id": str(delivery.address_id) if delivery and delivery.address_id else None,
                         "declared_value_minor": delivery.declared_value_minor if delivery else None,
                         "service_id": delivery.service_id if delivery else None,
                         "parcel": delivery.parcel if delivery else {}},
            "shipping_pricing_inputs": {"destination_country": address.country if address else None,
                "zone": service.zone if service else None, "card_count": sum(c.quantity for c in cards),
                "declared_value_minor": delivery.declared_value_minor if delivery else None,
                "parcel": delivery.parcel if delivery else {}},
            "shipping": shipping, "shipping_configuration_version": str(record.version) if record else None,
            "available_services": [{"id": key, "name": value.name.model_dump(), "countries": value.countries} for key,value in config.services.items()
                                   if value.available and value.tracked and value.trading_cards_coverage_verified
                                   and value.coverage_reference],
            "inbound_receiving_address": config.receiving_address,
            "readiness": {"ready": ready, "states": states if states else (["ready_for_checkout"] if ready else ["submission_empty"])},
            "final_payable_minor": total,
            "context": context(item, db, settings)}


def shipping_amounts(amount, mode, rate):
    if mode == "inclusive":
        tax = rounded_ratio(amount, rate, 10000 + rate)
        net, total = amount - tax, amount
    else:
        tax = rounded_ratio(amount, rate) if mode == "exclusive" else 0
        net, total = amount, amount + tax
    return dict(charge_minor=total, net_minor=net, tax_minor=tax, configured_price_minor=amount)
