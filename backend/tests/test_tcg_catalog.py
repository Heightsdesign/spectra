from unittest.mock import patch
import pytest
from sqlalchemy import select
from app.tcg_import import import_set, fetch_set
from app.tcg_models import Expansion, CatalogCard
from test_submissions import submissions_api, draft, add, BASE


def seed(db, language='fr', identifier='test-set', name='Extension'):
    import_set(db, language, {'id':identifier, 'name':name, 'releaseDate':'2020-01-01',
                            'cards':[{'id':identifier+'-a', 'name':'Alpha', 'localId':'TG01'},
                                     {'id':identifier+'-b', 'name':'Beta', 'localId':'002/100'}]})
    db.commit()
    return db.scalar(select(Expansion).where(Expansion.external_id == identifier, Expansion.language == language))


def test_search_scope_pagination_localization(submissions_api):
    client, db, _ = submissions_api
    first=seed(db)
    second=seed(db, identifier='other')
    seed(db, language='en', name='English set')
    assert len(client.get('/api/catalog/games').json()) == 4
    assert client.get('/api/catalog/expansions?game=one-piece').json() == []
    assert len(client.get('/api/catalog/expansions?game=pokemon&language=en').json()) == 1
    assert len(client.get('/api/catalog/expansions?game=pokemon&q=test-set').json()) == 1
    url=f'/api/catalog/cards?expansion_id={first.id}'
    rows=client.get(url).json()
    assert [r['name'] for r in rows] == ['Alpha', 'Beta']
    assert client.get(url+'&q=TG01').json() == rows[:1]
    assert client.get(url+'&offset=1&limit=1').json() == rows[1:]
    assert client.get(url+'&q=%25').json() == []
    assert all(r['expansion_id'] != str(second.id) for r in rows)
    assert client.get('/api/catalog/cards/'+rows[0]['id']).json() == rows[0]
    assert client.get(url+'&limit=101').status_code == 422
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_snapshots_restore_multiple_legacy_and_update(submissions_api):
    client, db, _ = submissions_api
    expansion=seed(db)
    card=db.scalar(select(CatalogCard).where(CatalogCard.expansion_id==expansion.id).order_by(CatalogCard.name))
    item=add(client,draft(client),catalog_card_id=str(card.id),card_name=card.name,
             expansion=expansion.name,card_number=card.collector_number,language='fr')
    item=add(client,item)  # legacy/manual alongside catalog selection
    url=f"{BASE}/{item['id']}"
    assert client.get(url).json()==item
    confirmed=client.post(url+'/confirm',json={'version':item['version']}).json()
    seed(db,name='Updated name')
    assert client.get(url).json()==confirmed
    assert {e['catalog_card_id'] for e in confirmed['entries']} == {str(card.id), None}


def test_mismatch_and_manual_detach(submissions_api):
    client, db, _ = submissions_api
    expansion=seed(db)
    card=db.scalar(select(CatalogCard).where(CatalogCard.expansion_id==expansion.id))
    item=draft(client)
    assert client.post(f"{BASE}/{item['id']}/entries",json={'version':1,'game':'pokemon','card_name':'Wrong',
        'expansion':expansion.name,'card_number':card.collector_number,'language':'fr','catalog_card_id':str(card.id)}).status_code==422
    item=add(client,item,catalog_card_id=str(card.id),card_name=card.name,expansion=expansion.name,card_number=card.collector_number,language='fr')
    entry=item['entries'][0]
    payload={k:v for k,v in entry.items() if k not in {'id', 'pre_shipment_photos'}}
    payload.update(version=item['version'],catalog_card_id=None,card_name='Manual')
    assert client.put(f"{BASE}/{item['id']}/entries/{entry['id']}",json=payload).json()['entries'][0]['catalog_card_id'] is None


def test_provider_downtime_keeps_local_data(submissions_api):
    client, db, _ = submissions_api
    seed(db)
    with patch('app.tcg_import.urlopen',side_effect=TimeoutError):
        with pytest.raises(TimeoutError):
            fetch_set('fr','test-set')
        assert len(client.get('/api/catalog/expansions?game=pokemon').json()) == 1


def test_game_wide_printings_and_optional_expansion(submissions_api):
    client, db, _ = submissions_api
    first = seed(db, identifier='first', name='First printing')
    second = seed(db, identifier='second', name='Second printing')
    seed(db, language='en', name='English printing')
    other = seed(db, identifier='other-game')
    other.game = 'one-piece'
    db.commit()
    url = '/api/catalog/cards?game=pokemon&language=fr&q=Alpha'
    rows = client.get(url).json()
    assert len(rows) == 2 and len({r['id'] for r in rows}) == 2
    assert {r['expansion_name'] for r in rows} == {'First printing', 'Second printing'}
    assert all(r['game'] == 'pokemon' and r['language'] == 'fr' for r in rows)
    assert all(r['expansion_code'] in {'first', 'second'} for r in rows)
    assert client.get(url+f'&expansion_id={first.id}').json() == [r for r in rows if r['expansion_id'] == str(first.id)]
    assert client.get(url+f'&expansion_id={other.id}').json() == []
    assert client.get(url+'&limit=1&offset=1').json() == rows[1:]
    assert client.get('/api/catalog/cards?game=pokemon&language=en&q=Alpha').json()[0]['expansion_name'] == 'English printing'
    assert client.get(f'/api/catalog/cards?expansion_id={second.id}').status_code == 200  # V1 request
    assert client.get('/api/catalog/cards').status_code == 422
    assert client.get('/api/catalog/cards?game=pokemon').status_code == 422
    assert client.get(url+'&offset=-1').status_code == 422


def test_empty_expansion_query_and_complete_pagination(submissions_api):
    client, db, _ = submissions_api
    for i in range(23):
        seed(db, identifier=f'code-{i:02}', name=f'Localized expansion {i:02}')
    url = '/api/catalog/expansions?game=pokemon&language=fr&q=&limit=20'
    first = client.get(url).json()
    second = client.get(url+'&offset=20').json()
    assert len(first) == 20 and len(second) == 3
    assert len({r['id'] for r in first+second}) == 23
    assert [r['name'] for r in first+second] == sorted(r['name'] for r in first+second)
    assert client.get('/api/catalog/expansions?game=pokemon&q=code-22').json() == second[-1:]
    assert client.get('/api/catalog/expansions?game=pokemon&q=Localized%20expansion%2022').json() == second[-1:]
    cards_url = '/api/catalog/cards?game=pokemon&language=fr&limit=20'
    all_cards = sum((client.get(cards_url+f'&offset={offset}').json() for offset in (0,20,40)), [])
    assert len(all_cards) == len({r['id'] for r in all_cards}) == 46
