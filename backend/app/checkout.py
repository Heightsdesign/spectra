"""Authoritative checkout readiness. Grading totals never imply a payable total."""
from sqlalchemy import select

from app.checkout_models import CustomerAddress, ShippingConfiguration, ShippingState, SubmissionDelivery
from app.checkout_schemas import Address, ShippingCatalog
from app.pricing import calculate, current_catalog, rounded_ratio
from app.submissions import entries


def address_snapshot(address):
    if address is None:
        return None
    return {"id": str(address.id), "version": address.version,
            **{field: getattr(address, field) for field in Address.model_fields}}


def shipping_config(db):
    state = db.scalar(select(ShippingState).where(ShippingState.id == 1).with_for_update(read=True).execution_options(populate_existing=True))
    record = db.get(ShippingConfiguration, state.current_version) if state and state.current_version else None
    return (record, ShippingCatalog.model_validate(record.document)) if record else (None, ShippingCatalog())


def context(item, db):
    delivery = db.get(SubmissionDelivery, item.id, populate_existing=True)
    address = db.get(CustomerAddress, delivery.address_id, populate_existing=True) if delivery and delivery.address_id else None
    record, _ = shipping_config(db)
    return {"delivery_version": delivery.version if delivery else 0,
            "address_id": str(address.id) if address else None,
            "address_version": address.version if address else None,
            "shipping_version": str(record.version) if record else None}


def summary(item, db, settings, configured=None):
    configured = configured or current_catalog(db, settings, required=False)
    cards = entries(item, db)
    grading = calculate(configured[1], cards) if configured and cards else None
    delivery = db.get(SubmissionDelivery, item.id, populate_existing=True)
    address = db.get(CustomerAddress, delivery.address_id, populate_existing=True) if delivery and delivery.address_id else None
    record, config = shipping_config(db)
    states = []
    tax_ready = bool(configured and configured[1].tax_mode != "pending" and configured[1].tax_validation_reference)
    if not tax_ready:
        states.append("tax_configuration_pending")
    if configured and configured[1].development_only:
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
        tax = rounded_ratio(service.charge_minor, service.tax_rate_bps, 10_000 + service.tax_rate_bps) if service.tax_mode == "inclusive" else 0
        shipping.update(charge_minor=service.charge_minor, tax_minor=tax, net_minor=service.charge_minor-tax,
                        service={"id": delivery.service_id, **service.model_dump()})
    ready = not states and grading is not None
    return {"submission_reference": item.reference, "currency": "EUR", "quantity": sum(c.quantity for c in cards),
            "pricing_revision": str(configured[0].version) if configured else None,
            "grading": grading, "return_address": address_snapshot(address),
            "delivery": {"version": delivery.version if delivery else 0,
                         "address_id": str(delivery.address_id) if delivery and delivery.address_id else None,
                         "declared_value_minor": delivery.declared_value_minor if delivery else None,
                         "service_id": delivery.service_id if delivery else None,
                         "parcel": delivery.parcel if delivery else {}},
            "shipping": shipping, "shipping_configuration_version": str(record.version) if record else None,
            "available_services": [{"id": key, "name": value.name.model_dump(), "countries": value.countries} for key,value in config.services.items()
                                   if value.available and value.tracked and value.trading_cards_coverage_verified
                                   and value.coverage_reference],
            "inbound_receiving_address": config.receiving_address,
            "readiness": {"ready": ready, "states": states if states else (["ready_for_checkout"] if ready else ["submission_empty"])},
            "final_payable_minor": grading["total_minor"] + shipping["charge_minor"] if ready else None,
            "context": context(item, db)}
