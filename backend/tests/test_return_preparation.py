from uuid import UUID
import pytest
from app.intake_models import StaffMembership, IntakeAudit
from app.pricing_catalog import publish
from app.shipping_catalog import publish as publish_shipping
from sqlalchemy import select
from checkout_fixtures import ADDRESS, configure_shipping, shipping_document
from test_pricing import pricing_api, document, quote  # noqa: F401
from test_submissions import BASE, add, draft, submissions_api  # noqa: F401

PARCEL={'weight_g':650,'length_mm':240,'width_mm':160,'height_mm':80}


def promote(client,db):
    identifier=UUID(client.get('/api/auth/me').json()['id'])
    db.add(StaffMembership(customer_id=identifier,role='operator'))
    db.commit()


def test_customer_save_preserves_legacy_parcel_and_omitted_service(pricing_api):
    client,db,_,_,_=pricing_api
    configure_shipping(db)
    item=add(client,draft(client))
    address=client.post('/api/addresses',json=ADDRESS).json()
    path=f"{BASE}/{item['id']}/delivery"
    old=client.put(path,json={'version':0,'address_id':address['id'],'declared_value_minor':10000,'service_id':'test-return','parcel':PARCEL}).json()
    new=client.put(path,json={'version':old['delivery']['version'],'address_id':address['id'],'declared_value_minor':25000}).json()
    assert new['delivery']['parcel']==old['delivery']['parcel']==PARCEL
    assert new['delivery']['service_id']=='test-return' and new['delivery']['declared_value_minor']==25000
    assert client.get(f"{BASE}/{item['id']}").json()==item


def test_missing_configuration_preserves_customer_details_and_blocks_acceptance(pricing_api):
    client,db,_,settings,_=pricing_api
    publish(db,document(development_only=False,approval_reference='SYNTHETIC TEST ONLY'),settings);db.commit()
    item=add(client,draft(client))
    address=client.post('/api/addresses',json=ADDRESS).json()
    order=client.put(f"{BASE}/{item['id']}/delivery",json={'version':0,'address_id':address['id'],'declared_value_minor':120050}).json()
    assert order['available_services']==[] and order['shipping']['charge_minor'] is None
    assert order['final_payable_minor'] is None and not order['readiness']['ready']
    assert order['delivery']['declared_value_minor']==120050
    item=client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    q=quote(client,item)
    assert client.post(f"{BASE}/{item['id']}/quotes/{q['id']}/accept",json={'version':item['version'],'accept_terms':True}).json()['detail']=='checkout_not_ready'


def test_staff_can_prepare_empty_record_only_for_confirmed_submission(pricing_api):
    client,db,_,_,_=pricing_api
    item=add(client,draft(client));promote(client,db)
    path=f"/internal/intake/submissions/{item['id']}/return-parcel"
    assert client.get(path).status_code==404
    item=client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    assert client.get(path).json()=={'version':0,'parcel':{},'terms_accepted':False}
    result=client.put(path,json={'version':0,'parcel':PARCEL,'reason':'SYNTHETIC preparation'}).json()
    assert result=={'version':1,'parcel':PARCEL,'terms_accepted':False}
    order=client.get(f"{BASE}/{item['id']}/order-summary").json()
    assert order['delivery']['address_id'] is None and order['delivery']['declared_value_minor'] is None
    assert order['final_payable_minor'] is None
    assert client.get(f"{BASE}/{item['id']}").json()==item


def test_staff_measurements_auth_audit_eligibility_and_accepted_lock(pricing_api):
    client,db,_,settings,_=pricing_api
    publish(db,document(development_only=False,approval_reference='SYNTHETIC TEST ONLY'),settings)
    config=shipping_document();config['services']['test-return'].update(max_weight_g=1000,max_length_mm=500,max_width_mm=500,max_height_mm=500)
    publish_shipping(db,config);db.commit()
    item=add(client,draft(client))
    address=client.post('/api/addresses',json=ADDRESS).json()
    client.put(f"{BASE}/{item['id']}/delivery",json={'version':0,'address_id':address['id'],'service_id':'test-return','declared_value_minor':10000})
    item=client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    path=f"/internal/intake/submissions/{item['id']}/return-parcel"
    assert client.get(path).status_code==403
    payload={'version':1,'parcel':PARCEL,'reason':'SYNTHETIC operator preparation'}
    assert client.put(path,json=payload).status_code==403
    q=quote(client,item)
    assert q['snapshot']['checkout']['final_payable_minor'] is None
    promote(client,db)
    response=client.put(path,json=payload)
    assert response.status_code==200,response.text
    result=response.json()
    assert result['parcel']==PARCEL and result['version']==2
    assert client.get(path).json()==result
    assert client.put(path,json=payload).status_code==409
    assert client.get(f"{BASE}/{item['id']}").json()==item
    assert client.get(f"{BASE}/{item['id']}/quotes/{q['id']}").json()['status']=='invalidated'
    event=db.scalar(select(IntakeAudit).where(IntakeAudit.submission_id==UUID(item['id']),IntakeAudit.action=='return_parcel_prepared'))
    assert event.data['after']==PARCEL and event.reason==payload['reason']
    new=quote(client,item)
    accepted=client.post(f"{BASE}/{item['id']}/quotes/{new['id']}/accept",json={'version':item['version'],'accept_terms':True})
    assert accepted.status_code==200,accepted.text
    frozen=client.get(f"{BASE}/{item['id']}/order-summary").json()
    assert client.put(path,json={**payload,'version':2,'parcel':{'weight_g':1}}).json()['detail']=='terms_already_accepted'
    assert client.get(f"{BASE}/{item['id']}/order-summary").json()==frozen
    client.cookies.clear();assert client.get(path).status_code==401


@pytest.mark.parametrize('parcel',[{'weight_g':True},{'weight_g':0},{'weight_g':100001},{'length_mm':5001},{'width_mm':-1},{'height_mm':1.5}])
def test_staff_parcel_limits_and_csrf(pricing_api,parcel):
    client,db,_,_,_=pricing_api
    item=add(client,draft(client));item=client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    promote(client,db)
    path=f"/internal/intake/submissions/{item['id']}/return-parcel"
    assert client.put(path,json={'version':0,'parcel':parcel,'reason':'Test'}).status_code==422
    client.headers['X-CSRF-Token']='bad'
    assert client.put(path,json={'version':0,'parcel':PARCEL,'reason':'Test'}).status_code==403
