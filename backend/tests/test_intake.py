"""Staff boundaries, real PostgreSQL custody and audit guarantees."""
from uuid import UUID, uuid4
import json
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from app.intake_models import StaffMembership, PhysicalCard, IntakeAudit
from app.customer_models import Customer, CustomerSession
from app.staff_bootstrap import bootstrap
from test_submissions import submissions_api, draft, add, BASE


@pytest.fixture
def intake_api(submissions_api, request):
    client, db, login = submissions_api
    item = add(client, draft(client), quantity=getattr(request, 'param', 2))
    item = client.post(f"{BASE}/{item['id']}/confirm", json={'version':item['version']}).json()
    # Select the account belonging to this submission, never an unrelated fixture.
    from app.submission_models import Submission
    actor = db.get(Customer, db.get(Submission, UUID(item['id'])).customer_id)
    db.add(StaffMembership(customer_id=actor.id, role='admin'))
    db.commit()
    return client, db, login, item, actor


def url(item):
    return '/internal/intake/submissions/' + item['id']


def parcel(client, item, **extra):
    payload = {'request_key':str(uuid4()), 'notes':'Box intact', **extra}
    response = client.post(url(item)+'/parcels', json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


def action(client, item, value):
    return client.post(url(item)+'/transition', json={'action':value,'reason':'Explicit test operational decision'})


def begin(client, item):
    assert action(client,item,'override').status_code == 200
    assert action(client,item,'begin').status_code == 200


def card(client, item, pid):
    payload = {'request_key':str(uuid4()),'parcel_id':pid,'notes':'Identity pending'}
    response = client.post(url(item)+'/cards',json=payload)
    assert response.status_code == 201, response.text
    return response.json(), payload


def issue(client, item, **values):
    before = {d['id'] for d in client.get(url(item)).json()['discrepancies']}
    response = client.post(url(item)+'/discrepancies', json={'notes':'Observed discrepancy',**values})
    assert response.status_code == 201, response.text
    return next(d for d in response.json()['discrepancies'] if d['id'] not in before)


def close(client, item, issue, status='acknowledged'):
    return client.post(url(item)+'/discrepancies/'+issue['id']+'/resolve', json={'status':status,'reason':'Reviewed and accepted physical discrepancy'})


@pytest.mark.parametrize('intake_api', [2,5], indirect=True)
def test_complete_quantity_and_multiple_parcels(intake_api):
    client, db, _, item, _ = intake_api
    original = client.get(BASE+'/'+item['id']).json()
    p1,_ = parcel(client,item)
    p2,_ = parcel(client,item)
    assert p1['id'] != p2['id']
    assert action(client,item,'begin').json()['detail'] == 'operational_override_required'
    begin(client,item)
    c1,_ = card(client,item,p1['id'])
    c2,_ = card(client,item,p2['id'])
    inventory = [c1,c2]
    for index in range(item['card_count']-2):
        inventory.append(card(client,item,[p1,p2][index % 2]['id'])[0])
    assert c1['reference'].startswith('PC-') and c1['id'] != c2['id']
    eid = item['entries'][0]['id']
    assert len({c['id'] for c in inventory}) == len(inventory)
    assert len({c['reference'] for c in inventory}) == len(inventory)
    for c in inventory:
        assert c['id'] != eid
        assert client.post(url(item)+'/cards/'+c['id']+'/match',json={'entry_id':eid,'reason':'Verified declaration'}).status_code == 200
    assert action(client,item,'complete').status_code == 200
    result = client.get(url(item)).json()
    assert result['status'] == 'reconciled' and result['received_quantity'] == item['card_count']
    assert all(p['status']=='reconciled' for p in result['parcels'])
    assert client.get(BASE+'/'+item['id']).json() == original
    assert result['payment_status'] == 'not_implemented' and not result['commercially_accepted']
    assert {'parcel_registered','physical_card_created','card_matched','intake_transition','operational_override'} <= {e['action'] for e in result['events']}
    assert action(client,item,'hold').status_code == 409
    assert client.post(url(item)+'/parcels',json={'request_key':str(uuid4())}).status_code == 409
    assert db.scalar(select(PhysicalCard)).grading_card_id is None


def test_missing_unexpected_and_questionable(intake_api):
    client, _, _, item, _ = intake_api
    p,_ = parcel(client,item)
    begin(client,item)
    c,_ = card(client,item,p['id'])
    assert action(client,item,'complete').json()['detail'] == 'quantity_unreconciled'
    missing = issue(client,item,kind='missing',entry_id=item['entries'][0]['id'],quantity=2)
    unexpected = issue(client,item,kind='unexpected',card_id=c['id'])
    damaged = issue(client,item,kind='damaged',card_id=c['id'])
    assert action(client,item,'complete').json()['detail'] == 'open_discrepancies'
    assert close(client,item,missing).status_code == 200
    assert close(client,item,unexpected,'resolved').status_code == 200
    assert close(client,item,damaged).status_code == 200
    assert action(client,item,'complete').json()['detail'] == 'unidentified_card'
    unresolved = issue(client,item,kind='unresolved',card_id=c['id'])
    assert close(client,item,unresolved).status_code == 200
    assert action(client,item,'complete').status_code == 200
    assert close(client,item,unresolved).status_code == 409


def test_resolved_missing_requires_actual_card(intake_api):
    client, _, _, item, _ = intake_api
    p,_ = parcel(client,item)
    begin(client,item)
    d = issue(client,item,kind='missing',entry_id=item['entries'][0]['id'],quantity=2)
    assert close(client,item,d,'resolved').status_code == 200
    assert action(client,item,'complete').status_code == 409
    for _ in range(2):
        c,_ = card(client,item,p['id'])
        assert client.post(url(item)+'/cards/'+c['id']+'/match',json={'entry_id':item['entries'][0]['id'],'reason':'Located card'}).status_code == 200
    extra,_ = card(client,item,p['id'])
    assert client.post(url(item)+'/cards/'+extra['id']+'/match',json={'entry_id':item['entries'][0]['id'],'reason':'Incorrect extra'}).status_code == 409
    mismatch = issue(client,item,kind='mismatch',card_id=extra['id'])
    assert close(client,item,mismatch).status_code == 200
    assert action(client,item,'complete').status_code == 200


def test_idempotency_and_hold(intake_api):
    client, _, _, item, _ = intake_api
    p,payload = parcel(client,item)
    assert client.post(url(item)+'/parcels',json=payload).json() == p
    assert client.post(url(item)+'/parcels',json={**payload,'notes':'Different'}).status_code == 409
    assert action(client,item,'hold').status_code == 200
    assert client.post(url(item)+'/parcels',json={'request_key':str(uuid4())}).status_code == 409
    assert action(client,item,'resume').status_code == 200
    begin(client,item)
    c,payload = card(client,item,p['id'])
    assert client.post(url(item)+'/cards',json=payload).json() == c
    assert client.post(url(item)+'/cards',json={**payload,'notes':'Different'}).status_code == 409
    result = client.get(url(item)).json()
    assert len(result['cards']) == len(result['parcels']) == 1
    assert sum(e['action']=='physical_card_created' for e in result['events']) == 1


def test_every_endpoint_requires_staff(intake_api):
    client, _, login, item, _ = intake_api
    assert not any(path.startswith('/internal/intake') for path in client.get('/openapi.json').json()['paths'])
    login()  # ordinary customer, different account
    key = str(uuid4())
    calls = [('GET','/internal/intake/me',None),('GET','/internal/intake/submissions',None),('GET',url(item),None),
             ('POST',url(item)+'/parcels',{'request_key':key}),('POST',url(item)+'/cards',{'request_key':key,'parcel_id':key}),
             ('POST',url(item)+'/cards/'+key+'/match',{'entry_id':None,'reason':'forged'}),
             ('POST',url(item)+'/discrepancies',{'kind':'missing','notes':'forged'}),
             ('POST',url(item)+'/discrepancies/'+key+'/resolve',{'status':'resolved','reason':'forged'}),
             ('POST',url(item)+'/transition',{'action':'override','reason':'forged'})]
    for method,path,payload in calls:
        assert client.request(method,path,json=payload).status_code == 403
    assert client.get(BASE+'/'+item['id']).status_code == 404
    client.cookies.clear()
    for method,path,payload in calls:
        assert client.request(method,path,json=payload).status_code == 401


def test_csrf_validation_scope_and_operator(intake_api):
    client, db, _, item, actor = intake_api
    for headers in [{'Origin':'https://evil.invalid'},{'X-CSRF-Token':''},{'X-Spectra-Client':''}]:
        assert client.post(url(item)+'/parcels',json={'request_key':str(uuid4())},headers=headers).status_code == 403
    for payload in [{'request_key':'bad'},{'request_key':str(uuid4()),'received_by':str(actor.id)},{'request_key':str(uuid4()),'notes':'x'*2001},{'request_key':str(uuid4()),'notes':'bad\x00text'},{'request_key':str(uuid4()),'carrier':'bad\ncarrier'},{'request_key':str(uuid4()),'notes':'bad\ud800text'}]:
        response = client.post(url(item)+'/parcels',content=json.dumps(payload),headers={'Content-Type':'application/json'})
        assert response.status_code == 422 and response.json()['detail']=='invalid_input'
    assert client.patch('/api/auth/profile',json={'first_name':'Test','last_name':'Collector','preferred_language':'EN','is_staff':True}).status_code == 422
    assert client.post('/api/auth/register',json={'email':'new@example.invalid','password':'test-long-password','first_name':'A','last_name':'B','role':'admin'}).status_code == 422
    assert client.get('/internal/intake/submissions?status=fake').status_code == 422
    assert client.get('/internal/intake/submissions?limit=101').status_code == 422
    assert client.get('/internal/intake/submissions?search='+item['reference']).json()[0]['id']==item['id']
    p,_ = parcel(client,item)
    db.get(StaffMembership,actor.id).role = 'operator'
    db.commit()
    assert action(client,item,'override').status_code == 403
    db.get(StaffMembership,actor.id).role = 'admin'
    db.commit()
    begin(client,item)
    assert client.post(url(item)+'/cards',json={'request_key':str(uuid4()),'parcel_id':str(uuid4())}).status_code == 404
    c,_ = card(client,item,p['id'])
    other = add(client,draft(client))
    assert client.post(url(item)+'/cards/'+c['id']+'/match',json={'entry_id':other['entries'][0]['id'],'reason':'Cross-submission'}).status_code == 404
    assert client.get(url(other)).status_code == 404  # draft is not receivable
    assert client.get('/internal/intake/me').headers['cache-control']=='no-store'


def test_revocation_and_disabled_staff_fail_closed(intake_api):
    client, db, _, item, actor = intake_api
    actor.status = 'disabled'
    db.commit()
    assert client.get(url(item)).status_code == 401
    actor.status = 'active'
    db.delete(db.get(StaffMembership,actor.id))
    db.commit()
    assert client.get(url(item)).status_code == 403


def test_bootstrap_and_audit_immutability(submissions_api):
    client, db, _ = submissions_api
    customer = db.scalar(select(Customer).where(Customer.first_name=='Test'))
    assert db.get(StaffMembership,customer.id) is None
    with pytest.raises(ValueError):
        bootstrap(db,'unknown@example.invalid','Initial authorization')
    customer.email_verified = False
    db.flush()
    with pytest.raises(ValueError):
        bootstrap(db,customer.email,'Initial authorization')
    customer.email_verified = True
    db.flush()
    bootstrap(db,customer.email,'Initial authorization')
    assert db.get(StaffMembership,customer.id).role=='admin'
    assert db.scalar(select(CustomerSession)).revoked_at is not None
    assert client.get('/internal/intake/me').status_code == 401
    with pytest.raises(ValueError):
        bootstrap(db,customer.email,'Repeat authorization')
    event = db.scalar(select(IntakeAudit))
    assert event.action=='administrator_bootstrapped'
    for statement in ['UPDATE intake_audit_events SET action=\'changed\'', 'DELETE FROM intake_audit_events', 'TRUNCATE intake_audit_events']:
        with pytest.raises(DBAPIError):
            with db.begin_nested():
                db.execute(text(statement))
    assert db.scalar(select(IntakeAudit)).action=='administrator_bootstrapped'


def test_invalid_transitions(intake_api):
    client, _, _, item, _ = intake_api
    for value in ['begin','complete','resume']:
        assert action(client,item,value).status_code == 409
    assert action(client,item,'hold').status_code == 200
    assert action(client,item,'hold').status_code == 409
    assert action(client,item,'resume').json()['status']=='awaiting_receipt'
    assert client.post(url(item)+'/transition',json={'action':'graded','reason':'invalid'}).status_code == 422
