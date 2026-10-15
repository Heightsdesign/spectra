"""Synthetic services and tax assertions ONLY for isolated tests, never operator defaults."""
from app.shipping_catalog import publish

ADDRESS = dict(recipient="Test Collector", line1="1 Test Street", city="Test City", postal_code="75001", country="FR", phone="+33123456789")


def shipping_document(**changes):
    return {"currency": "EUR", "supported_destinations": ["FR"], "services": {"test-return": {
        "name": {"FR": "Retour TEST", "EN": "TEST return"}, "available": True, "countries": ["FR"],
        "charge_minor": 1234, "tracked": True, "trading_cards_coverage_verified": True,
        "coverage_reference": "SYNTHETIC TEST EVIDENCE", "coverage_minor": 100000,
        "coverage": {"FR": "Couverture TEST uniquement", "EN": "TEST coverage only"},
        "exclusions": {"FR": "Exclusions TEST uniquement", "EN": "TEST exclusions only"},
        "phone_required": True, "tax_mode": "exempt", "tax_rate_bps": 0,
        "tax_validation_reference": "SYNTHETIC TEST TAX"}}, **changes}


def configure_shipping(db):
    record = publish(db, shipping_document())
    db.commit()
    return record.version


def prepare_delivery(client, item):
    address = client.post("/api/addresses", json=ADDRESS)
    assert address.status_code == 201, address.text
    result = client.put(f"/api/submissions/{item['id']}/delivery", json={"version": 0, "address_id": address.json()["id"],
        "declared_value_minor": 10000, "service_id": "test-return"})
    assert result.status_code == 200, result.text
    assert result.json()["readiness"]["ready"], result.text
    return address.json()
