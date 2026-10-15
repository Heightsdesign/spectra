import copy
import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.checkout_models import ShippingConfiguration
from app.pricing import calculate
from app.pricing_catalog import publish
from app.auth import now
from app.pricing_models import QuoteAcceptance, SubmissionQuote
from app.submission_models import Submission
from datetime import timedelta
from app.pricing_schemas import Catalog
from app.shipping_catalog import publish as publish_shipping
from checkout_fixtures import ADDRESS, configure_shipping, prepare_delivery, shipping_document
from test_pricing import card, document, pricing_api, quote  # noqa: F401
from test_submissions import BASE, add, draft, submissions_api  # noqa: F401


def official(**changes):
    data = json.loads((Path(__file__).parents[1] / "pricing/spectra-v1.json").read_text(encoding="utf-8"))
    return {**data, **changes}


@pytest.mark.parametrize("quantity,unit", [(1,1990),(4,1990),(5,1790),(9,1790),(10,1690),(11,1690),(20,1690)])
def test_official_boundaries(quantity, unit):
    result = calculate(Catalog.model_validate(official()), [card(quantity)])
    assert result["total_minor"] == quantity * unit
    assert result["discount_minor"] == quantity * (1990-unit)
    assert result["volume_bracket"]["unit_price_minor"] == unit
    assert result["discount"] is None


def test_aggregated_mixed_configurations_and_front_label():
    result = calculate(Catalog.model_validate(official()), [card(2,"express",["detailed"]),card(3,"priority")])
    assert result["quantity"] == 5
    assert result["total_minor"] == 5*1790 + 2*990 + 3*1990 + 2*390
    assert result["discount_minor"] == 1000
    assert result["lines"][0]["upgrades"][0]["label_presentation"] == dict(position="front",show_overall_grade=True,subgrades=["centering","corners","edges","surface"])


@pytest.mark.parametrize("changes", [dict(discounts=[dict(id="double",min_quantity=1,rate_bps=100)]),dict(tax_mode="exclusive",tax_rate_bps=2000)])
def test_prevent_double_discount_or_inflated_gross_prices(changes):
    with pytest.raises(ValidationError):
        Catalog.model_validate(official(**changes))


def test_tax_gate_and_inclusive_rounding(pricing_api):
    _,db,_,settings,_ = pricing_api
    with pytest.raises(ValueError, match="Tax treatment"):
        publish(db, official(), settings)
    with pytest.raises(ValueError, match="Tax treatment"):
        publish(db, official(tax_mode="exempt"), settings)
    config = Catalog.model_validate(official(tax_mode="inclusive",tax_rate_bps=2000,tax_validation_reference="TEST ONLY"))
    result = calculate(config,[card(5)])
    assert (result["total_minor"],result["tax_minor"],result["net_minor"]) == (8950,1492,7458)
    record = publish(db, config.model_dump(), settings)
    assert record.document["tax_validation_reference"] == "TEST ONLY"


def test_address_crud_versions_isolation_and_validation(pricing_api):
    client,_,login,_,_ = pricing_api
    address = client.post("/api/addresses",json=ADDRESS).json()
    assert client.get("/api/addresses").json() == [address]
    updated = client.put('/api/addresses/'+address['id'],json={**ADDRESS,"version":1,"city":"Changed"})
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert client.put('/api/addresses/'+address['id'],json={**ADDRESS,"version":1}).status_code == 409
    assert client.post("/api/addresses",json={**ADDRESS,"country":"ZZ"}).status_code == 422
    assert client.post("/api/addresses",json={**ADDRESS,"customer_id":address['id']}).status_code == 422
    login()
    assert client.get("/api/addresses").json() == []
    assert client.put('/api/addresses/'+address['id'],json={**ADDRESS,"version":2}).status_code == 404
    assert client.request('DELETE','/api/addresses/'+address['id'],json={"version":2}).status_code == 404
    own = client.post("/api/addresses",json={**ADDRESS,"country":"JP","postal_code":""}).json()
    assert client.request('DELETE','/api/addresses/'+own['id'],json={"version":1}).status_code == 200


def test_no_invented_payable_and_acceptance_blocked(pricing_api):
    client,db,_,settings,_ = pricing_api
    publish(db,document(development_only=False,approval_reference="TEST ONLY"),settings);db.commit()
    item = add(client,draft(client))
    order = client.get(f"{BASE}/{item['id']}/order-summary").json()
    assert order['final_payable_minor'] is None
    assert order['shipping']['charge_minor'] is None
    assert order['inbound_receiving_address'] is None
    assert 'missing_return_address' in order['readiness']['states']
    q = quote(client,item)
    item = client.post(f"{BASE}/{item['id']}/confirm",json={"version":item['version']}).json()
    result = client.post(f"{BASE}/{item['id']}/quotes/{q['id']}/accept",json={"version":item['version'],"accept_terms":True})
    assert result.status_code == 409 and result.json()['detail'] == 'checkout_not_ready'


def test_ready_address_invalidation_historical_snapshot(pricing_api):
    client,db,_,settings,_ = pricing_api
    publish(db,official(tax_mode='exempt',tax_validation_reference='TEST ONLY'),settings);db.commit()
    configure_shipping(db)
    item = add(client,draft(client),quantity=5)
    address = prepare_delivery(client,item)
    q = quote(client,item)
    assert q['snapshot']['checkout']['final_payable_minor'] == 8950+1234
    assert client.request('DELETE','/api/addresses/'+address['id'],json={'version':1}).status_code == 409
    result = client.put('/api/addresses/'+address['id'],json={**ADDRESS,'version':1,'city':'Second city'})
    assert result.status_code == 200
    assert client.get(f"{BASE}/{item['id']}/quotes/{q['id']}").json()['status'] == 'invalidated'
    q2 = quote(client,item)
    assert q2['id'] != q['id']
    item = client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    accepted = client.post(f"{BASE}/{item['id']}/quotes/{q2['id']}/accept",json={'version':item['version'],'accept_terms':True})
    assert accepted.status_code == 200, accepted.text
    client.put('/api/addresses/'+address['id'],json={**ADDRESS,'version':2,'city':'Third city'})
    publish_shipping(db,shipping_document(services={}));db.commit()
    unchanged = client.get(f"{BASE}/{item['id']}/quotes/{q2['id']}").json()
    assert unchanged == accepted.json()
    order = client.get(f"{BASE}/{item['id']}/order-summary").json()
    assert order['return_address']['city'] == 'Second city'
    assert order['final_payable_minor'] == 10184
    assert client.put(f"{BASE}/{item['id']}/delivery",json={'version':1,'address_id':address['id']}).status_code == 409


def test_unsupported_destination_missing_rates_and_delivery_conflict(pricing_api):
    client,db,login,_,_ = pricing_api
    configure_shipping(db)
    item = add(client,draft(client))
    address = client.post('/api/addresses',json={**ADDRESS,'country':'JP'}).json()
    payload={'version':0,'address_id':address['id']}
    order=client.put(f"{BASE}/{item['id']}/delivery",json=payload).json()
    assert 'unsupported_shipping_destination' in order['readiness']['states']
    assert order['final_payable_minor'] is None
    assert client.put(f"{BASE}/{item['id']}/delivery",json=payload).status_code == 409
    login()
    other=add(client,draft(client))
    assert client.put(f"{BASE}/{other['id']}/delivery",json=payload).status_code == 404
    assert client.get(f"{BASE}/{item['id']}/order-summary").status_code == 404


@pytest.mark.parametrize('change,state',[(dict(trading_cards_coverage_verified=False),'shipping_price_pending'),(dict(coverage_minor=1),'declared_value_required_or_uncovered'),(dict(max_weight_g=200),'parcel_requirements_pending'),(dict(available=False),'shipping_price_pending')])
def test_unverified_or_inapplicable_coverage_never_payable(pricing_api,change,state):
    client,db,_,settings,_=pricing_api
    publish(db,document(development_only=False,approval_reference='TEST ONLY'),settings);db.commit()
    config=shipping_document();config['services']['test-return'].update(change)
    publish_shipping(db,config);db.commit()
    item=add(client,draft(client));address=client.post('/api/addresses',json=ADDRESS).json()
    response=client.put(f"{BASE}/{item['id']}/delivery",json={'version':0,'address_id':address['id'],'service_id':'test-return','declared_value_minor':10000})
    if change.get('available') is False:
        assert response.status_code == 422 and response.json()['detail'] == 'shipping_service_unavailable'
        return
    order=response.json()
    assert state in order['readiness']['states']
    assert order['shipping']['charge_minor'] is None and order['final_payable_minor'] is None


def test_shipping_publication_invalidates_quotes_and_is_immutable(pricing_api):
    client,db,_,_,_=pricing_api
    item=add(client,draft(client));q=quote(client,item)
    version=configure_shipping(db)
    assert client.get(f"{BASE}/{item['id']}/quotes/{q['id']}").json()['status']=='invalidated'
    with pytest.raises(DBAPIError), db.begin_nested():
        db.execute(text('UPDATE shipping_configurations SET document=document WHERE version=:v'),{'v':version})


def test_address_auth_csrf_and_sensitive_validation(pricing_api):
    client,_,_,_,_=pricing_api
    token=client.headers.pop('X-CSRF-Token')
    assert client.post('/api/addresses',json=ADDRESS).status_code==403
    client.headers['X-CSRF-Token']=token
    response=client.post('/api/addresses',json={**ADDRESS,'recipient':'PRIVATE\x00ADDRESS'})
    assert response.status_code==422 and 'PRIVATE' not in response.text
    assert response.headers['cache-control']=='no-store'
    client.cookies.clear()
    assert client.get('/api/addresses').status_code==401


def test_legacy_accepted_quote_is_grandfathered_without_invented_checkout(pricing_api):
    client,db,_,_,catalog_version=pricing_api
    item=add(client,draft(client))
    item=client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    timestamp=now()
    legacy_snapshot={'development_only':False,'currency':'EUR','total_minor':2000,'historical':'W3.2 grading-only agreement'}
    legacy=SubmissionQuote(submission_id=UUID(item['id']),pricing_revision=db.get(Submission,UUID(item['id'])).pricing_revision,
        catalog_version=catalog_version,snapshot=legacy_snapshot,created_at=timestamp,expires_at=timestamp+timedelta(hours=1))
    db.add(legacy);db.flush()
    db.add(QuoteAcceptance(submission_id=UUID(item['id']),quote_id=legacy.id,accepted_at=timestamp));db.commit()
    result=client.post(f"{BASE}/{item['id']}/quotes/{legacy.id}/accept",json={'version':1,'accept_terms':True})
    assert result.status_code==200 and result.json()['snapshot']==legacy_snapshot
    order=client.get(f"{BASE}/{item['id']}/order-summary").json()
    assert order['final_payable_minor'] is None and order['readiness']['states']==['legacy_grading_terms']
    assert order['terms_accepted'] is True


def test_tax_pending_with_legacy_catalog_phone_and_unknown_shipping(pricing_api):
    from app.pricing_models import PricingCatalog, PricingState
    client,db,_,_,_=pricing_api
    legacy=PricingCatalog(document=document(tax_validation_reference=None,development_only=False,approval_reference='LEGACY TEST'))
    db.add(legacy);db.flush();db.get(PricingState,1).current_version=legacy.version;db.commit()
    configure_shipping(db)
    item=add(client,draft(client));address=client.post('/api/addresses',json={**ADDRESS,'phone':''}).json()
    payload={'version':0,'address_id':address['id'],'service_id':'test-return','declared_value_minor':10000}
    order=client.put(f"{BASE}/{item['id']}/delivery",json=payload).json()
    assert 'tax_configuration_pending' in order['readiness']['states']
    assert 'delivery_phone_required' in order['readiness']['states']
    assert order['final_payable_minor'] is None
    assert client.put(f"{BASE}/{item['id']}/delivery",json={**payload,'version':1,'service_id':'invented'}).status_code==422
    assert client.put(f"{BASE}/{item['id']}/delivery",json={**payload,'version':1,'charge_minor':1}).status_code==422
    assert client.post('/api/addresses',json={**ADDRESS,'phone':'+'}).status_code==422
