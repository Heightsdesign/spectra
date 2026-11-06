import base64
import hashlib
import io
from uuid import UUID
from unittest.mock import patch
import pytest
from PIL import Image
from sqlalchemy import select
from app.submission_models import SubmissionPhoto
from app.submission_models import Submission
from app.auth import csrf_value
from app.intake_models import StaffMembership
from test_submissions import submissions_api, draft, add, BASE, CARD


def image_data(color='red', format='PNG'):
    output = io.BytesIO()
    Image.new('RGB', (16, 16), color).save(output, format=format)
    return output.getvalue()


def entry(item):
    return item['entries'][0]


def url(item, eid=None):
    return f"{BASE}/{item['id']}/entries/{eid or entry(item)['id']}/photos"


def upload(client, item, side='front', copy=1, data=None, **overrides):
    return client.post(url(item), json={'version':item['version'], 'copy_number':copy, 'side':side,
        'filename':'customer.png', 'data':base64.b64encode(data if data is not None else image_data()).decode(), **overrides})


def test_manual_minimal_fields_and_multiple_entries(submissions_api):
    client, _, _ = submissions_api
    item = draft(client)
    response = client.post(f"{BASE}/{item['id']}/entries", json={'version':1, 'game':'pokemon', 'card_name':'Customer text', 'language':'FR', 'quantity':3})
    assert response.status_code == 201
    item = response.json()
    assert entry(item)['expansion'] == entry(item)['card_number'] == ''
    assert entry(item)['catalog_card_id'] is None and entry(item)['pre_shipment_photos'] == []
    item = add(client, item, game='one-piece', expansion='', card_number='', quantity=2)
    assert item['card_count'] == 5
    confirmed = client.post(f"{BASE}/{item['id']}/confirm", json={'version':item['version']}).json()
    assert confirmed['status'] == 'submitted' and len(confirmed['entries']) == 2


def test_front_back_replacement_removal_copy_identity_and_confirmation(submissions_api):
    client, db, _ = submissions_api
    item = add(client, draft(client), quantity=2)
    pricing_before = db.get(Submission, UUID(item['id'])).pricing_revision
    item = upload(client, item).json()
    front = entry(item)['pre_shipment_photos'][0]
    first_id = front['id']
    assert front['provenance'] == 'customer_pre_shipment' and front['identity_verified'] is False
    assert front['sha256'] == hashlib.sha256(image_data()).hexdigest() and front['uploaded_at']
    assert 'storage_key' not in front
    item = upload(client, item, side='back').json()
    item = upload(client, item, copy=2, data=image_data('blue')).json()
    assert {(p['copy_number'],p['side']) for p in entry(item)['pre_shipment_photos']} == {(1,'front'),(1,'back'),(2,'front')}
    item = upload(client, item, data=image_data('green')).json()
    photos = entry(item)['pre_shipment_photos']
    current = next(p for p in photos if p['copy_number']==1 and p['side']=='front')
    assert current['id'] != first_id and db.get(SubmissionPhoto, UUID(first_id)).removed_at
    assert client.get(url(item)+'/'+first_id).status_code == 404
    response = client.get(url(item)+'/'+current['id'])
    assert response.content == image_data('green') and response.headers['content-type']=='image/png'
    assert response.headers['cache-control'] == 'private, no-store'
    back = next(p for p in photos if p['side']=='back')
    item = client.request('DELETE',url(item)+'/'+back['id'],json={'version':item['version']}).json()
    assert len(entry(item)['pre_shipment_photos']) == 2
    assert client.get(url(item)+'/'+back['id']).status_code == 404
    assert db.get(Submission, UUID(item['id'])).pricing_revision == pricing_before
    confirmed = client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    assert upload(client, confirmed).status_code == 409
    assert client.request('DELETE',url(confirmed)+'/'+current['id'],json={'version':confirmed['version']}).status_code == 409
    assert client.get(f"{BASE}/{item['id']}").json() == confirmed
    assert client.post(f"{BASE}/{item['id']}/confirm",json={'version':1}).json() == confirmed
    assert client.get(url(item)+'/'+current['id']).content == image_data('green')


def test_ownership_staff_and_cross_entry_access(submissions_api):
    client, db, login = submissions_api
    item = upload(client, add(client, draft(client))).json()
    photo = entry(item)['pre_shipment_photos'][0]
    private = url(item)+'/'+photo['id']
    other = add(client, draft(client))
    assert client.get(url(other)+'/'+photo['id']).status_code == 404
    confirmed = client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).json()
    staff_url=f"/internal/intake/submissions/{item['id']}/pre-shipment-photos/{photo['id']}"
    assert client.get(staff_url).status_code == 403
    staff_id = login()
    assert client.get(private).status_code == 404
    assert upload(client, confirmed).status_code == 404
    assert client.request('DELETE',private,json={'version':confirmed['version']}).status_code == 404
    db.add(StaffMembership(customer_id=staff_id, role='operator'))
    db.commit()
    assert client.get(staff_url).content == image_data()
    detail = client.get(f"/internal/intake/submissions/{item['id']}").json()
    assert detail['entries'][0]['pre_shipment_photos'] == entry(confirmed)['pre_shipment_photos']
    assert detail['cards'] == [] and detail['status'] == 'awaiting_receipt'
    assert client.get(f"/internal/intake/submissions/{other['id']}/pre-shipment-photos/{photo['id']}").status_code == 404
    client.cookies.clear()
    assert client.get(private).status_code == client.get(staff_url).status_code == 401


@pytest.mark.parametrize('data', [b'', b'<svg xmlns="http://www.w3.org/2000/svg"/>', b'not an image', image_data(format='TIFF'), image_data(format='GIF'), image_data()[:40]])
def test_invalid_images(submissions_api, data):
    client, _, _ = submissions_api
    item = add(client,draft(client))
    assert upload(client,item,data=data).status_code == 422
    assert entry(client.get(f"{BASE}/{item['id']}").json())['pre_shipment_photos'] == []


def test_limits_csrf_stale_versions_and_quantity(submissions_api):
    client, _, _ = submissions_api
    item = add(client,draft(client),quantity=2)
    assert upload(client,item,data=b'x'*4097).status_code == 413  # fixture image limit
    assert upload(client,item,filename='../unsafe.png').status_code == 422
    assert upload(client,item,data=None,side='other').status_code == 422
    assert upload(client,item,copy=3).status_code == 422
    assert upload(client,item,copy=True).status_code == 422
    assert upload(client,item,version=1).status_code == 409
    assert upload(client,item,data=None,data_not_allowed='x').status_code == 422
    client.headers['X-CSRF-Token']='bad'
    assert upload(client,item).status_code == 403
    client.headers['X-CSRF-Token']=csrf_value(client.cookies.get('spectra_session'))
    item = upload(client,item,copy=2).json()
    payload={**CARD,'quantity':1,'version':item['version']}
    assert client.put(f"{BASE}/{item['id']}/entries/{entry(item)['id']}",json=payload).json()['detail']=='photo_quantity_conflict'
    photo=entry(item)['pre_shipment_photos'][0]
    item=client.request('DELETE',url(item)+'/'+photo['id'],json={'version':item['version']}).json()
    assert client.put(f"{BASE}/{item['id']}/entries/{entry(item)['id']}",json={**payload,'version':item['version']}).status_code == 200


def test_storage_failure_preserves_original_and_allows_confirmation(submissions_api):
    client, db, _ = submissions_api
    item = upload(client,add(client,draft(client))).json()
    original = entry(item)['pre_shipment_photos'][0]
    with patch('app.submission_photos.write_original',side_effect=OSError):
        assert upload(client,item,data=image_data('blue')).status_code == 503
    db.expire_all()
    assert client.get(f"{BASE}/{item['id']}").json() == item
    assert client.get(url(item)+'/'+original['id']).content == image_data()
    assert client.post(f"{BASE}/{item['id']}/confirm",json={'version':item['version']}).status_code == 200


def test_private_read_integrity(submissions_api, api):
    client, db, _ = submissions_api
    item = upload(client,add(client,draft(client))).json()
    photo=entry(item)['pre_shipment_photos'][0]
    record=db.get(SubmissionPhoto,UUID(photo['id']))
    settings=api[2]
    path=settings.card_image_dir/record.storage_key
    path.write_bytes(b'tampered')
    assert client.get(url(item)+'/'+photo['id']).status_code == 409
    path.unlink()
    assert client.get(url(item)+'/'+photo['id']).status_code == 503


def test_malformed_base64_animation_and_pixel_limit(submissions_api, api):
    client, _, _ = submissions_api
    item=add(client,draft(client))
    payload={'version':item['version'],'copy_number':1,'side':'front','filename':'card.png','data':'not-base64!'}
    assert client.post(url(item),json=payload).status_code == 422
    frames=io.BytesIO()
    Image.new('RGB',(4,4),'red').save(frames,format='PNG',save_all=True,append_images=[Image.new('RGB',(4,4),'blue')])
    assert upload(client,item,data=frames.getvalue()).status_code == 422
    api[2].max_image_size_bytes=8*1024*1024
    large=io.BytesIO()
    Image.new('RGB',(5000,4001),'white').save(large,format='PNG')
    assert upload(client,item,data=large.getvalue()).status_code == 422
    assert client.get(f"{BASE}/{item['id']}").json() == item


def test_database_failure_cleans_only_new_file(submissions_api, api):
    from sqlalchemy.exc import SQLAlchemyError
    client, db, _ = submissions_api
    item=upload(client,add(client,draft(client))).json()
    before=set(api[2].card_image_dir.iterdir())
    with patch.object(db,'commit',side_effect=SQLAlchemyError):
        assert upload(client,item,data=image_data('blue')).status_code == 503
    assert set(api[2].card_image_dir.iterdir()) == before
    db.expire_all()
    assert client.get(f"{BASE}/{item['id']}").json() == item
