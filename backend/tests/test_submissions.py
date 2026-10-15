import secrets
from datetime import timedelta
from uuid import uuid4
import pytest
from app.auth import digest, csrf_value, now
from app.customer_models import Customer, CustomerSession

BASE = '/api/submissions'
CARD = dict(game='pokemon', card_name='Pikachu', expansion='Base', card_number='58/102', language='FR', quantity=2, notes='Collector')

@pytest.fixture
def submissions_api(api):
    client, db, settings = api
    def login():
        customer = Customer(email=f'{uuid4().hex}@example.com', password_hash='unused', first_name='Test', last_name='Collector', email_verified=True)
        db.add(customer)
        db.flush()
        raw = secrets.token_urlsafe(32)
        db.add(CustomerSession(customer_id=customer.id, token_hash=digest(raw), expires_at=now()+timedelta(hours=1)))
        db.commit()
        client.cookies.set('spectra_session', raw)
        client.headers.update({'Origin': settings.auth_origin, 'X-Spectra-Client':'1', 'X-CSRF-Token':csrf_value(raw)})
        return customer.id
    login()
    return client, db, login

def draft(client):
    response = client.post(BASE, json={})
    assert response.status_code == 201
    item = response.json()
    assert item['reference'].startswith('SP-') and item['status'] == 'draft'
    assert item['version'] == 1 and item['confirmed_at'] is None
    assert response.headers['cache-control'] == 'no-store'
    return item

def add(client, item, **overrides):
    response = client.post(f"{BASE}/{item['id']}/entries", json={**CARD, 'version':item['version'], **overrides})
    assert response.status_code == 201, response.text
    return response.json()

def test_complete_workflow_and_retry(submissions_api):
    client, db, _ = submissions_api
    item = draft(client)
    url = f"{BASE}/{item['id']}"
    assert client.post(url+'/confirm', json={'version':1}).status_code == 422
    item = add(client, item)
    item = add(client, item, game='one-piece', card_name='Luffy', quantity=1)
    assert item['card_count'] == 3 and len(item['entries']) == 2
    response = client.patch(url, json={'version':item['version'], 'notes':'Keep together'})
    assert response.status_code == 200
    item = response.json()
    entry = item['entries'][0]
    response = client.put(url+'/entries/'+entry['id'], json={**CARD,'version':item['version'],'quantity':3})
    assert response.status_code == 200
    item = response.json()
    response = client.request('DELETE',url+'/entries/'+item['entries'][1]['id'],json={'version':item['version']})
    assert response.status_code == 200
    item = response.json()
    db.expire_all()
    assert client.get(url).json() == item
    assert client.get(BASE).json() == [item]
    response = client.post(url+'/confirm', json={'version':item['version']})
    assert response.status_code == 200
    confirmed = response.json()
    assert confirmed['status'] == 'submitted' and confirmed['confirmed_at']
    assert client.post(url+'/confirm', json={'version':1}).json() == confirmed
    assert client.patch(url,json={'version':confirmed['version'],'notes':'changed'}).status_code == 409
    assert client.post(url+'/entries',json={**CARD,'version':confirmed['version']}).status_code == 409
    assert client.put(url+'/entries/'+entry['id'],json={**CARD,'version':confirmed['version']}).status_code == 409
    assert client.request('DELETE',url+'/entries/'+entry['id'],json={'version':confirmed['version']}).status_code == 409

def test_stale_version_and_entry_scope(submissions_api):
    client, _, _ = submissions_api
    first = draft(client)
    second = add(client, draft(client))
    url = f"{BASE}/{first['id']}"
    entry = second['entries'][0]['id']
    assert client.put(url+'/entries/'+entry,json={**CARD,'version':1}).status_code == 404
    assert client.request('DELETE',url+'/entries/'+entry,json={'version':1}).status_code == 404
    changed = add(client,first)
    for path,method,payload in [(url,'PATCH',{'version':1,'notes':'stale'}),(url+'/confirm','POST',{'version':1}),(url+'/entries','POST',{**CARD,'version':1})]:
        assert client.request(method,path,json=payload).status_code == 409
    assert client.get(url).json() == changed

def test_ownership_and_unauthenticated(submissions_api):
    client, _, login = submissions_api
    item = add(client,draft(client))
    url = f"{BASE}/{item['id']}"
    entry = item['entries'][0]['id']
    login()
    operations = [('GET',url,None),('PATCH',url,{'version':2,'notes':'x'}),('POST',url+'/entries',{**CARD,'version':2}),('PUT',url+'/entries/'+entry,{**CARD,'version':2}),('DELETE',url+'/entries/'+entry,{'version':2}),('POST',url+'/confirm',{'version':2})]
    assert client.get(BASE).json() == []
    for method,path,payload in operations:
        assert client.request(method,path,json=payload).status_code == 404
    client.cookies.clear()
    for method,path,payload in operations + [('POST',BASE,{}),('GET',BASE,None)]:
        assert client.request(method,path,json=payload).status_code == 401

@pytest.mark.parametrize('override',[{'game':'unknown'},{'card_name':' '},{'expansion':'x'*201},{'card_number':'x'*65},{'language':''},{'quantity':0},{'quantity':101},{'quantity':True},{'quantity':1.5},{'notes':'x'*2001},{'card_name':'x\nname'},{'customer_id':str(uuid4())},{'status':'submitted'},{'price':0}])
def test_invalid_entries(submissions_api,override):
    client, _, _ = submissions_api
    item = draft(client)
    url = f"{BASE}/{item['id']}"
    assert client.post(url+'/entries',json={**CARD,'version':1,**override}).status_code == 422
    assert client.get(url).json()['entries'] == []

def test_csrf_and_forged_details(submissions_api):
    client, _, _ = submissions_api
    item = draft(client)
    url = f"{BASE}/{item['id']}"
    for headers in [{'Origin':'https://evil.example'},{'X-CSRF-Token':''},{'X-Spectra-Client':''}]:
        assert client.post(BASE,json={},headers=headers).status_code == 403
    assert client.post(BASE,json={'customer_id':str(uuid4())}).status_code == 422
    assert client.patch(url,json={'version':1,'status':'submitted'}).status_code == 422
    assert client.get(BASE+'?limit=101').status_code == 422
    assert client.get(BASE+'?offset=-1').status_code == 422

@pytest.mark.parametrize('game',['pokemon','one-piece','dragon-ball','naruto'])
def test_supported_games(submissions_api,game):
    client, _, _ = submissions_api
    item = add(client,draft(client),game=game)
    assert item['entries'][0]['game'] == game

def test_entry_limit(submissions_api):
    from uuid import UUID
    from app.submission_models import SubmissionEntry
    client, db, _ = submissions_api
    item = draft(client)
    db.add_all([SubmissionEntry(submission_id=UUID(item['id']),**CARD) for _ in range(100)])
    db.commit()
    assert client.post(f"{BASE}/{item['id']}/entries",json={**CARD,'version':1}).status_code == 422
    assert len(client.get(f"{BASE}/{item['id']}").json()['entries']) == 100
