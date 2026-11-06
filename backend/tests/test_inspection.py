from uuid import uuid4
import pytest
from sqlalchemy import select
from app.main import app
from app.inspection_commercial import commercial_provider, CommercialEvidence
from app.inspection_models import Inspection
from test_submissions import submissions_api
from test_intake import intake_api, parcel, begin, card, action, url


def accepted_quote(db, submission_id):
    """Persist immutable synthetic commerce records only in the isolated test DB."""
    from datetime import timedelta
    from app.auth import now
    from app.pricing_models import PricingCatalog, SubmissionQuote, QuoteAcceptance
    catalog = PricingCatalog(document={'test_only': True})
    db.add(catalog)
    db.flush()
    quote = SubmissionQuote(submission_id=submission_id, pricing_revision=1,
                            catalog_version=catalog.version,
                            snapshot={'test_only': True, 'total_minor': 2000, 'currency': 'EUR'},
                            created_at=now(), expires_at=now() + timedelta(days=1))
    db.add(quote)
    db.flush()
    db.add(QuoteAcceptance(submission_id=submission_id, quote_id=quote.id))
    db.flush()
    return quote.id

def test_inspection_workflow(intake_api):
    client,db,_,item,_=intake_api
    p,_=parcel(client,item); begin(client,item)
    cards=[card(client,item,p['id'])[0] for _ in range(2)]
    for c in cards:
        assert client.post(url(item)+'/cards/'+c['id']+'/match',json={'entry_id':item['entries'][0]['id'],'reason':'Verified'}).status_code==200
    ref=cards[0]['reference']; path='/internal/inspection/'+ref+'/command'
    lookup=lambda: client.get('/internal/inspection/lookup',params={'reference':'SP:PC:1:'+ref+'\r\n'})
    assert 'intake_not_reconciled' in {r['code'] for r in lookup().json()['eligibility']['start']['reasons']}
    assert action(client,item,'complete').status_code==200
    result=lookup(); assert result.status_code==200
    assert result.headers['cache-control']=='private, no-store'
    assert 'payment_unverified' in {r['code'] for r in result.json()['eligibility']['start']['reasons']}
    payload={'action':'start','version':0,'request_key':str(uuid4()),'reason':'Confirmed physical handover'}
    assert client.post(path,json=payload).status_code==409
    assert db.scalar(select(Inspection)) is None
    app.dependency_overrides[commercial_provider]=lambda: lambda db,acceptance: CommercialEvidence(True,True)
    assert client.post(path,json=payload).status_code==409
    from uuid import UUID
    accepted_quote(db, UUID(item['id']))
    response=client.post(path,json=payload); assert response.status_code==200,response.text
    assert client.post(path,json=payload).status_code==200
    assert client.post(path,json={**payload,'request_key':str(uuid4())}).status_code==409
    for op,version in [('pause',1),('resume',2)]:
        response=client.post(path,json={**payload,'request_key':str(uuid4()),'action':op,'version':version})
        assert response.status_code==200,response.text
    assert len(response.json()['custody'])==3
    assert [e['new_state'] for e in response.json()['custody']]==['in_progress','paused','in_progress']
    assert all(e['physical_card_reference']==ref for e in response.json()['custody'])
    assert action(client,item,'hold').status_code==409

def test_inspection_auth(api):
    client,_,_=api
    assert client.get('/internal/inspection/lookup',params={'reference':'PC-'+'A'*32}).status_code==401

def test_image_versions_and_integrity(intake_api):
    import io, base64, hashlib
    from PIL import Image
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from app.inspection_models import InspectionImage
    client,db,_,item,_=intake_api
    p,_=parcel(client,item); begin(client,item)
    cards=[card(client,item,p['id'])[0] for _ in range(2)]
    for c in cards: client.post(url(item)+'/cards/'+c['id']+'/match',json={'entry_id':item['entries'][0]['id'],'reason':'Verified'})
    assert action(client,item,'complete').status_code==200
    app.dependency_overrides[commercial_provider]=lambda: lambda db,acceptance: CommercialEvidence(True,True)
    from uuid import UUID
    accepted_quote(db, UUID(item['id']))
    path='/internal/inspection/'+cards[0]['reference']
    start=client.post(path+'/command',json={'action':'start','version':0,'request_key':str(uuid4()),'reason':'Physical handover'}).json()
    buf=io.BytesIO(); Image.new('RGB',(8,8)).save(buf,format='PNG'); raw=buf.getvalue()
    payload={'inspection_id':start['inspection']['id'],'version':1,'side':'front','filename':'front.png','sha256':hashlib.sha256(raw).hexdigest(),'data':base64.b64encode(raw).decode(),'reason':'Original capture'}
    assert client.post(path+'/images',json={**payload,'inspection_id':str(uuid4())}).status_code==409
    assert client.post(path+'/images',json={**payload,'sha256':'0'*64}).status_code==422
    assert client.post(path+'/images',json={**payload,'filename':'../front.png'}).status_code==422
    invalid=b'not an image'
    assert client.post(path+'/images',json={**payload,'data':base64.b64encode(invalid).decode(),'sha256':hashlib.sha256(invalid).hexdigest()}).status_code==422
    assert client.post(path+'/images',json={**payload,'data':base64.b64encode(b'x'*4097).decode()}).status_code==413
    response=client.post(path+'/images',json=payload); assert response.status_code==200,response.text
    iid=response.json()['images'][0]['id']
    assert client.get(path+'/images/'+iid).content==raw
    assert client.get('/internal/inspection/'+cards[1]['reference']+'/images/'+iid).status_code==404
    assert client.post(path+'/images',json=payload).status_code==409
    response=client.post(path+'/images',json={**payload,'version':2,'side':'back'}); assert response.status_code==200
    response=client.post(path+'/images',json={**payload,'version':3}); assert response.status_code==200
    assert len(response.json()['images'])==3
    for table in ('inspection_images','inspection_custody_events'):
        for statement in (f'DELETE FROM {table}', f'UPDATE {table} SET reason=reason', f'TRUNCATE {table}'):
            with pytest.raises(DBAPIError), db.begin_nested(): db.execute(text(statement))
    from app.config import get_settings
    settings=app.dependency_overrides[get_settings]()
    stored=db.scalar(select(InspectionImage).where(InspectionImage.side=='front'))
    original_path=settings.card_image_dir/stored.storage_key
    original_path.write_bytes(b'tampered')
    assert client.get(path+'/images/'+str(stored.id)).status_code==409

from test_intake_concurrency import isolated_intake_engine

def test_concurrent_inspection_start(isolated_intake_engine):
    from sqlalchemy.orm import Session
    from app.intake_models import Intake, Parcel, PhysicalCard
    from app.submission_models import Submission, SubmissionEntry
    from app.inspection import command, Command
    from app.pricing_models import QuoteAcceptance
    from test_intake_concurrency import customer
    from test_pricing_concurrency import race
    from fastapi import HTTPException
    from types import SimpleNamespace
    engine=isolated_intake_engine
    with Session(engine) as db:
        actor=customer(db); aid=actor.id
        sub=Submission(customer_id=aid,reference='SP-'+uuid4().hex.upper(),status='submitted'); db.add(sub); db.flush()
        entry=SubmissionEntry(submission_id=sub.id,game='pokemon',card_name='Test',expansion='Test',card_number='1',language='FR'); db.add(entry)
        parcel=Parcel(reference='PI-'+uuid4().hex.upper(),submission_id=sub.id,received_by=aid,request_key=uuid4(),request_data={}); db.add(parcel); db.flush()
        ref='PC-'+uuid4().hex.upper()
        db.add(PhysicalCard(reference=ref,submission_id=sub.id,parcel_id=parcel.id,entry_id=entry.id,received_by=aid,request_key=uuid4(),request_data={},status='matched'))
        db.add(Intake(submission_id=sub.id,status='reconciled'))
        accepted_quote(db, sub.id)
        db.commit()
    def start():
        with Session(engine) as db:
            try:
                command(ref,Command(action='start',version=0,request_key=uuid4(),reason='Confirmed handover'),db,SimpleNamespace(id=aid),lambda db,a:CommercialEvidence(True,True))
                return 200
            except HTTPException as exc: return exc.status_code
    assert sorted(race(start,start))==[200,409]

def test_eligibility_independent_blocks(intake_api):
    from app.inspection import eligibility
    from app.intake_models import PhysicalCard, Discrepancy, Intake
    from app.submission_models import SubmissionEntry
    from app.pricing_models import QuoteAcceptance
    client,db,_,item,actor=intake_api
    p,_=parcel(client,item); begin(client,item); c,_=card(client,item,p['id'])
    physical=db.scalar(select(PhysicalCard).where(PhysicalCard.reference==c['reference']))
    provider=lambda db,a:CommercialEvidence(True,True)
    codes=lambda: {r['code'] for r in eligibility(db,physical,provider)['reasons']}
    assert {'association_invalid','intake_not_reconciled','quote_not_accepted'} <= codes()
    physical.entry_id=__import__('uuid').UUID(item['entries'][0]['id']); physical.status='matched'; db.flush()
    assert 'association_invalid' not in codes()
    issue=Discrepancy(submission_id=physical.submission_id,card_id=physical.id,kind='damaged',notes='Condition concern',created_by=actor.id,status='acknowledged')
    db.add(issue);db.flush();assert 'discrepancy_block' in codes()
    issue.status='resolved';db.flush();assert 'discrepancy_block' not in codes()
    state=db.get(Intake,physical.submission_id);state.status='on_hold';db.flush();assert 'intake_not_reconciled' in codes()
    accepted_quote(db, physical.submission_id)
    reasons=eligibility(db,physical,lambda db,a:CommercialEvidence())['reasons']
    assert 'quote_not_accepted' not in {r['code'] for r in reasons}
    assert 'payment_unverified' in {r['code'] for r in reasons}
    from app.intake_models import StaffMembership
    db.delete(db.get(StaffMembership,actor.id));db.commit()
    assert client.get('/internal/inspection/lookup',params={'reference':c['reference']}).status_code==403

@pytest.mark.parametrize('role', ['admin','operator'])
def test_authorization_csrf_and_commercial_boundaries(intake_api, role):
    from app.intake_models import StaffMembership
    client,db,_,item,actor=intake_api
    db.get(StaffMembership,actor.id).role=role;db.commit()
    p,_=parcel(client,item)
    # A scan is a read even without an intake override and before reconciliation.
    from app.intake_models import PhysicalCard
    from uuid import UUID
    physical=PhysicalCard(reference='PC-'+uuid4().hex.upper(),submission_id=UUID(item['id']),parcel_id=UUID(p['id']),received_by=actor.id,request_key=uuid4(),request_data={})
    db.add(physical);db.commit()
    path='/internal/inspection/'+physical.reference+'/command'
    payload={'action':'start','version':0,'request_key':str(uuid4()),'reason':'Explicit action'}
    assert client.post(path,json=payload,headers={'X-CSRF-Token':''}).status_code==403
    assert client.post(path,json=payload,headers={'Origin':'https://untrusted.invalid'}).status_code==403
    assert client.post(path,json={**payload,'payment_confirmed':True}).status_code==422
    assert client.post(path,json=payload,headers={'X-Payment-Confirmed':'true'}).status_code==409
    actor.email_verified=False;db.commit()
    assert client.get('/internal/inspection/lookup',params={'reference':physical.reference}).status_code==401

@pytest.mark.parametrize('wrong_link', ['entry','parcel','status'])
def test_foreign_card_associations_block_inspection(intake_api, wrong_link):
    from uuid import UUID
    from app.inspection_eligibility import eligibility
    from app.intake_models import PhysicalCard, Parcel
    from app.submission_models import Submission, SubmissionEntry
    client,db,_,item,actor=intake_api
    p,_=parcel(client,item);begin(client,item);c,_=card(client,item,p['id'])
    physical=db.scalar(select(PhysicalCard).where(PhysicalCard.reference==c['reference']))
    physical.entry_id=UUID(item['entries'][0]['id']);physical.status='matched'
    other=Submission(customer_id=actor.id,reference='SP-'+uuid4().hex.upper(),status='submitted');db.add(other);db.flush()
    if wrong_link=='entry':
        entry=SubmissionEntry(submission_id=other.id,game='pokemon',card_name='Other card',expansion='Test',card_number='2',language='FR');db.add(entry);db.flush();physical.entry_id=entry.id
    elif wrong_link=='parcel':
        foreign=Parcel(reference='PI-'+uuid4().hex.upper(),submission_id=other.id,received_by=actor.id,request_key=uuid4(),request_data={});db.add(foreign);db.flush();physical.parcel_id=foreign.id
    else: physical.status='questionable'
    db.flush()
    result=eligibility(db,physical,lambda db,a:CommercialEvidence(True,True))
    assert 'association_invalid' in {r['code'] for r in result['reasons']}
