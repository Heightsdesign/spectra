from app.pricing import common_configuration
from test_pricing import pricing_api, configured, quote  # noqa: F401
from test_submissions import BASE, CARD, add, draft, submissions_api  # noqa: F401


def minimal_card(client,item,name='New card',quantity=1):
    response=client.post(f"{BASE}/{item['id']}/entries",json={
        'version':item['version'],'game':'pokemon','card_name':name,'language':'FR','quantity':quantity})
    assert response.status_code==201,response.text
    return response.json()


def test_order_configuration_and_notes_are_atomic_and_inherited(pricing_api):
    client,_,_,_,_=pricing_api
    item=add(client,draft(client),quantity=2,notes='First card only')
    item=add(client,item,quantity=3,notes='Second card only')
    old=quote(client,item)
    response=client.patch(f"{BASE}/{item['id']}/configuration",json={
        'version':item['version'],'processing_tier':'priority','upgrade_ids':['detailed'],'notes':'Whole order note'})
    assert response.status_code==200,response.text
    changed=response.json()
    assert changed['version']==item['version']+1 and changed['notes']=='Whole order note'
    assert {entry['notes'] for entry in changed['entries']}=={'First card only','Second card only'}
    assert all(entry['processing_tier']=='priority' and entry['upgrade_ids']==['detailed'] for entry in changed['entries'])
    assert client.get(f"{BASE}/{item['id']}/quotes/{old['id']}").json()['status']=='invalidated'
    current=quote(client,changed)
    assert current['snapshot']['total_minor']==5*2300
    assert current['snapshot']['submission_notes']=='Whole order note'
    assert all(line['unit_minor']==2300 and line['processing_tier']=='priority' for line in current['snapshot']['lines'])
    changed=minimal_card(client,changed,quantity=4)
    newest=next(entry for entry in changed['entries'] if entry['card_name']=='New card')
    assert newest['processing_tier']=='priority' and newest['upgrade_ids']==['detailed']
    assert client.get(f"{BASE}/{item['id']}").json()==changed
    assert quote(client,changed)['snapshot']['total_minor']==9*2300


def test_identification_edits_keep_historical_exceptions_and_explicit_apis(pricing_api):
    client,_,_,_,_=pricing_api
    item=add(client,draft(client),quantity=1)
    item=add(client,item,quantity=1)
    exceptional=item['entries'][0]['id']
    item=configured(client,item,'express',['detailed'],entry_id=exceptional)
    before={entry['id']:(entry['processing_tier'],entry['upgrade_ids']) for entry in item['entries']}
    item=client.patch(f"{BASE}/{item['id']}",json={'version':item['version'],'notes':'Order note without conversion'}).json()
    response=client.put(f"{BASE}/{item['id']}/entries/{exceptional}",json={**CARD,'version':item['version'],'card_name':'Identification corrected'})
    assert response.status_code==200,response.text
    item=response.json()
    assert {entry['id']:(entry['processing_tier'],entry['upgrade_ids']) for entry in item['entries']}==before
    assert quote(client,item)['snapshot']['total_minor']==2*1800+1000  # edited legacy quantity from CARD is 2
    assert client.get(f"{BASE}/{item['id']}").json()==item
    # Existing explicit per-card and mixed-quote API capability is retained.
    item=client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    frozen=client.get(f"{BASE}/{item['id']}").json()
    assert client.patch(f"{BASE}/{item['id']}/configuration",json={
        'version':item['version'],'processing_tier':'standard','upgrade_ids':['classic'],'notes':'overwrite'}).status_code==409
    assert client.get(f"{BASE}/{item['id']}").json()==frozen


def test_explicit_legacy_writes_override_inheritance_and_old_global_payload_preserves_notes(pricing_api):
    client,_,_,_,_=pricing_api
    item=configured(client,add(client,draft(client)),'express',['detailed'])
    item=client.patch(f"{BASE}/{item['id']}",json={'version':item['version'],'notes':'Keep me'}).json()
    item=add(client,item,processing_tier='standard',upgrade_ids=['classic'])
    assert {entry['processing_tier'] for entry in item['entries']}=={'standard','express'}
    # Old caller explicitly chooses order-wide replacement; no notes field means preserve it.
    item=configured(client,item,'priority',['classic'])
    assert item['notes']=='Keep me'
    assert all(entry['processing_tier']=='priority' and entry['upgrade_ids']==['classic'] for entry in item['entries'])


def test_invalid_atomic_request_preserves_notes_configuration_and_revision(pricing_api):
    client,_,_,_,_=pricing_api
    item=add(client,draft(client))
    for invalid in [dict(notes='x'*2001),dict(processing_tier='not-a-tier'),dict(upgrade_ids=['classic','detailed']),dict(version=item['version']-1)]:
        response=client.patch(f"{BASE}/{item['id']}/configuration",json={
            'version':item['version'],'processing_tier':'express','upgrade_ids':['detailed'],'notes':'Do not partially save',**invalid})
        assert response.status_code in {409,422}
        assert client.get(f"{BASE}/{item['id']}").json()==item


def test_common_configuration_ignores_upgrade_order_without_mutating_records():
    from types import SimpleNamespace
    first=SimpleNamespace(processing_tier='express',upgrade_ids=['extra','classic'])
    second=SimpleNamespace(processing_tier='express',upgrade_ids=['classic','extra'])
    assert common_configuration([first,second])=={'processing_tier':'express','upgrade_ids':['extra','classic']}
    assert second.upgrade_ids==['classic','extra']
    assert common_configuration([]) is None
    second.processing_tier='priority'
    assert common_configuration([first,second]) is None


def test_notes_without_pricing_and_identification_remain_independent(submissions_api):
    client,_,_=submissions_api
    item=draft(client)
    item=client.patch(f"{BASE}/{item['id']}",json={'version':item['version'],'notes':'Whole order before services'}).json()
    item=minimal_card(client,item)
    assert item['notes']=='Whole order before services'
    assert item['entries'][0]['notes']==''
    assert item['entries'][0]['processing_tier']=='standard' and item['entries'][0]['upgrade_ids']==['classic']


def test_explicit_partial_legacy_create_and_mixed_draft_omission_keep_old_defaults(pricing_api):
    client,_,_,_,_=pricing_api
    item=configured(client,add(client,draft(client)),'express',['detailed'])
    item=add(client,item,processing_tier='priority',card_name='Partial legacy call')
    partial=next(entry for entry in item['entries'] if entry['card_name']=='Partial legacy call')
    assert partial['processing_tier']=='priority' and partial['upgrade_ids']==['classic']
    before={entry['id']:(entry['processing_tier'],entry['upgrade_ids']) for entry in item['entries']}
    item=minimal_card(client,item,name='Mixed legacy addition')
    newest=next(entry for entry in item['entries'] if entry['card_name']=='Mixed legacy addition')
    assert newest['processing_tier']=='standard' and newest['upgrade_ids']==['classic']
    assert {entry['id']:(entry['processing_tier'],entry['upgrade_ids']) for entry in item['entries'] if entry['id'] in before}==before
