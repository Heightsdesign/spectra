"""Authorized B-EXPIRE/B-DELAY only; process-local QA controls, no app edits."""
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

import control as C
from sqlalchemy import select, func, text, event
from sqlalchemy.orm import Session
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from app.config import get_settings
from app.database import get_engine
from app.stripe_checkout import StripeGateway, signature_event, SESSION_EVENTS, PI_EVENTS, RESTRICTION_EVENTS
from app.stripe_models import StripeAttempt, StripeEvidence
from app.commercial_models import VerifiedPayment, DispatchExpectation, CommercialEvent
from app.pricing_models import SubmissionQuote
from app.customer_models import Customer, CustomerSession
from app.auth import now, digest

P1 = C.OUT
OUT = C.ROOT / 'validation_artifacts/stripe_sandbox_b1r/phase2'
OUT.mkdir(parents=True, exist_ok=True)
C.OUT = OUT
save, read, clean = C.save, C.read, C.clean
OLD = 'cs_test_a1HLmQrotUiKh8VSAkSS9aFVpagjCBXH2CyjNRdimlgluvZPYeaVWSmWI8'
lock = threading.RLock()

def audit(name, data):
    with lock, (OUT / name).open('a', encoding='utf-8') as f:
        f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),**data},ensure_ascii=False,default=str)+'\n')

def sources():
    files=list((C.ROOT/'app').glob('*.py'))+list((C.ROOT.parent/'frontend/src').rglob('*'))+[C.ROOT/'.env']
    return {str(p.relative_to(C.ROOT.parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}

def checked_session(identifier, case):
    s=StripeGateway(get_settings()).get('checkout/sessions',identifier)
    assert s['id']==identifier and s['livemode'] is False and s['currency']=='eur' and s['amount_total']==2500
    assert s['metadata']['submission_id']==case['submission_id'] and s['metadata']['quote_id']==case['quote_id']
    return s

def guarded(self, method, path, data=None, key=None):
    identity=C.identity()
    cases=read('manifest.json')['cases']
    if method=='GET':
        assert re.fullmatch(r'(account|checkout/sessions/cs_test_[A-Za-z0-9]+|payment_intents/pi_[A-Za-z0-9]+|charges/ch_[A-Za-z0-9]+|events/evt_[A-Za-z0-9]+)',path), 'Forbidden Stripe read'
        result=C.ORIGINAL(self,method,path,data,key)
        assert result.get('livemode',False) is False
        return result
    if method!='POST' or path!='checkout/sessions':
        raise HTTPException(409,'qa_forbidden_stripe_mutation')
    case=next((v for v in cases.values() if v['submission_id']==data.get('metadata[submission_id]')),None)
    assert case and data.get('metadata[quote_id]')==case['quote_id'] and data.get('line_items[0][price_data][unit_amount]')=='2500'
    assert case['name'] in {'B-EXPIRE','B-DELAY'}
    if case['name']=='B-EXPIRE':
        old=checked_session(OLD,case)
        assert old['status']=='expired' and old['payment_status']=='unpaid' and not old.get('payment_intent'), 'STOP old session still payable'
    with lock:
        ledger=read('session-ledger.json')
        assert case['name'] not in ledger, 'STOP additional or ambiguous Session creation'
        ledger[case['name']]={'key':key,'state':'reserved'}
        save('session-ledger.json',ledger)
    result=C.ORIGINAL(self,method,path,data,key)
    assert result['livemode'] is False and result['id'].startswith('cs_test_') and result['amount_total']==2500
    assert result['metadata']['quote_id']==case['quote_id']
    ledger[case['name']].update(state='created',session_id=result['id'])
    save('session-ledger.json',ledger)
    save('created-'+case['name']+'.json',clean(result))
    urls=read('private-urls.json');urls[case['name']]=result['url'];save('private-urls.json',urls)
    audit('stripe-operations.jsonl',{'identity':identity,'method':method,'path':path,'session_id':result['id'],'case':case['name']})
    return result

StripeGateway.call=guarded

def local_counts(case):
    with Session(get_engine()) as db:
        qid=UUID(case['quote_id'])
        payment=db.get(VerifiedPayment,qid)
        deadlines=db.scalars(select(DispatchExpectation).where(DispatchExpectation.quote_id==qid)).all()
        attempt_rows=db.scalars(select(StripeAttempt).where(StripeAttempt.quote_id==qid)).all()
        return {'payment':{c.name:getattr(payment,c.name) for c in VerifiedPayment.__table__.columns} if payment else None,
                'deadlines':[{c.name:getattr(d,c.name) for c in DispatchExpectation.__table__.columns} for d in deadlines],
                'payment_audits':db.scalar(select(func.count()).select_from(CommercialEvent).where(CommercialEvent.submission_id==UUID(case['submission_id']),CommercialEvent.kind=='provider_payment_verified')),
                'evidence_count':db.scalar(select(func.count()).select_from(StripeEvidence).where(StripeEvidence.quote_id==qid)),
                'evidence':[{c.name:getattr(e,c.name) for c in StripeEvidence.__table__.columns} for e in db.scalars(select(StripeEvidence).where(StripeEvidence.quote_id==qid))],
                'attempts':[{'id':str(a.id),'session_id':a.session_id,'status':a.status} for a in attempt_rows],
                'snapshot_sha256':hashlib.sha256(json.dumps(db.get(SubmissionQuote,qid).snapshot,sort_keys=True).encode()).hexdigest()}

def observe(name,label):
    identity=C.identity();case=read('manifest.json')['cases'][name]
    with C.client_for(name) as client:
        commercial=C.request(client,'GET','/api/submissions/'+case['submission_id']+'/commercial-state')
    counts=local_counts(case)
    objects=[]
    sessions={a['session_id'] for a in counts['attempts'] if a['session_id']}
    if name=='B-EXPIRE':sessions.add(OLD)
    for sid in sorted(sessions):
        s=checked_session(sid,case)
        pi=StripeGateway(get_settings()).get('payment_intents',s['payment_intent']) if s.get('payment_intent') else None
        if pi:assert pi['metadata']['quote_id']==case['quote_id'] and pi['livemode'] is False and pi['amount']==2500
        charge=StripeGateway(get_settings()).get('charges',pi['latest_charge']) if pi and pi.get('latest_charge') else None
        objects.append({'session':clean(s),'payment_intent':clean(pi),'charge':clean(charge)})
    payable=sum(o['session']['status']=='open' and o['session']['payment_status']=='unpaid' for o in objects)
    result={'at':datetime.now(timezone.utc).isoformat(),'identity':identity,'case':name,'label':label,'commercial':commercial,'database':counts,'objects':objects,'payable_sessions':payable}
    result['B-P2_reproduced']=any(o['session']['status']=='complete' and o['session']['payment_status']=='unpaid' and o['payment_intent'] and o['payment_intent']['status']=='requires_action' for o in objects)
    save(name+'-'+label+'.json',result)
    assert payable<=1 and not result['B-P2_reproduced'], 'STOP double payable or B-P2'
    assert counts['snapshot_sha256']==case['snapshot_sha256']
    return result

def summarize(result):
    return {'case':result['case'],'label':result['label'],'SELBY':result['commercial']['payment_status'],'payment_count':int(bool(result['database']['payment'])),'deadline_count':len(result['database']['deadlines']),'payable_sessions':result['payable_sessions'],'objects':[{'id':o['session']['id'],'status':o['session']['status'],'payment_status':o['session']['payment_status'],'pi_status':o['payment_intent']['status'] if o['payment_intent'] else None} for o in result['objects']],'B-P2':result['B-P2_reproduced']}

def prepare():
    assert not (OUT/'manifest.json').exists(), 'Never recreate fixtures'
    identity=C.identity()
    dev=C.fingerprint(C.VALUES['DATABASE_URL']);test=C.fingerprint(C.TARGET)
    assert dev['_revision']==test['_revision']==['0015']
    save('before.json',{'identity':identity,'development':dev,'test':test,'sources':sources()})
    (OUT/'private-next-env-before.txt').write_bytes((C.ROOT.parent/'frontend/next-env.d.ts').read_bytes())
    old=json.loads((P1/'manifest.json').read_text(encoding='utf-8'))['cases']['B-ABANDON']
    old={**old,'name':'B-EXPIRE','source':'phase1/B-ABANDON','old_session_id':OLD}
    manifest={'phase':2,'max_new_successes':1,'amount_minor':2500,'cases':{'B-EXPIRE':old},'identity':identity}
    save('manifest.json',manifest);save('session-ledger.json',{})
    access=json.loads((P1/'private-access.json').read_text(encoding='utf-8'))['B-ABANDON']
    # Create only a fresh local QA authentication session; preserve original account.
    token=secrets.token_urlsafe(32)
    with Session(get_engine()) as db:
        db.add(CustomerSession(customer_id=UUID(access['customer_id']),token_hash=digest(token),expires_at=now()+timedelta(hours=4)));db.commit()
    save('private-access.json',{'B-EXPIRE':{**access,'token':token}})
    s=checked_session(OLD,old)
    save('old-session-preflight.json',clean(s))
    assert s['payment_status']=='unpaid' and not s.get('payment_intent') and s['status'] in {'open','expired'}, 'STOP unsafe original Session'
    assert not local_counts(old)['payment'] and not local_counts(old)['deadlines']
    save('private-urls.json',{'old':s.get('url') or 'https://checkout.stripe.com/c/pay/'+OLD})
    # One new dedicated customer/order only for B-DELAY, through existing commerce routes.
    with Session(get_engine()) as db:
        customer=Customer(email='qa-b1r-delay-'+secrets.token_hex(4)+'@example.invalid',password_hash='unused-local-QA-session-only',first_name='QA',last_name='B-DELAY',email_verified=True)
        db.add(customer);db.flush();token=secrets.token_urlsafe(32)
        db.add(CustomerSession(customer_id=customer.id,token_hash=digest(token),expires_at=now()+timedelta(hours=4)));db.commit()
        access=read('private-access.json');access['B-DELAY']={'token':token,'customer_id':str(customer.id),'email':customer.email};save('private-access.json',access)
    with C.client_for('B-DELAY') as client:
        item=C.request(client,'POST','/api/submissions',{});path='/api/submissions/'+item['id']
        manifest['cases']['B-DELAY']={'name':'B-DELAY','submission_id':item['id'],'customer_id':access['B-DELAY']['customer_id']};save('manifest.json',manifest)
        for card in ['QA Pikachu','QA Eevee']:
            item=C.request(client,'POST',path+'/entries',{'version':item['version'],'game':'pokemon','card_name':card,'expansion':'QA TEST','card_number':'TEST','language':'FR','quantity':1,'notes':'B-DELAY','processing_tier':'standard','upgrade_ids':['classic']})
        address=C.request(client,'POST','/api/addresses',{'recipient':'QA TEST','line1':'1 rue du Test','city':'Paris','postal_code':'75001','country':'FR'})
        summary=C.request(client,'PUT',path+'/delivery',{'version':0,'address_id':address['id'],'declared_value_minor':10000,'service_id':'fictitious-test-return-fr'})
        assert summary['final_payable_minor']==2500 and summary['readiness']['ready']
        item=C.request(client,'GET',path);item=C.request(client,'POST',path+'/confirm',{'version':item['version']})
        quote=C.request(client,'POST',path+'/quotes',{'version':item['version']})
        quote=C.request(client,'POST',path+'/quotes/'+quote['id']+'/accept',{'version':item['version'],'accept_terms':True})
        assert quote['status']=='accepted' and quote['snapshot']['order_total_minor']==2500
        manifest['cases']['B-DELAY'].update(quote_id=quote['id'],snapshot_sha256=hashlib.sha256(json.dumps(quote['snapshot'],sort_keys=True).encode()).hexdigest());save('manifest.json',manifest)
    save('retention-state.json',{'armed':False,'released':False,'error':None})
    print(json.dumps({'prepared':True,'identity':identity,'old_session_status':s['status'],'cases':manifest['cases']}))

def expire():
    identity=C.identity();case=read('manifest.json')['cases']['B-EXPIRE']
    s=checked_session(OLD,case)
    assert s['payment_status']=='unpaid' and not s.get('payment_intent') and not local_counts(case)['payment']
    if s['status']=='expired':
        save('expiration-operation.json',{'identity':identity,'action':'already_expired_no_mutation','session':clean(s)});print('Already expired; no forced expiration');return
    assert s['status']=='open' and not (OUT/'expiration-reserved.json').exists()
    save('expiration-reserved.json',{'session_id':OLD,'identity':identity})
    result=C.ORIGINAL(StripeGateway(get_settings()),'POST','checkout/sessions/'+OLD+'/expire',{},'selby-b1r-phase2-expire-'+OLD)
    assert result['id']==OLD and result['livemode'] is False and result['status']=='expired' and not result.get('payment_intent')
    save('expiration-operation.json',{'identity':identity,'action':'explicit_expiration','session':clean(result)})
    audit('stripe-operations.jsonl',{'method':'POST','path':'checkout/sessions/'+OLD+'/expire','identity':identity})
    print(json.dumps({'expired':OLD,'payment_status':result['payment_status']}))

class Queue:
    def __init__(self):
        self.entries={};self.lock=threading.RLock();self.first=None;self.error=None;self.released=False;self.armed=False;self.token=secrets.token_urlsafe(32)

    def persist(self):
        save('retention-state.json',{'armed':self.armed,'released':self.released,'error':self.error,'first_received':self.first,'now':time.time(),'entries':[{k:v for k,v in e.items() if k not in {'raw','signature'}} for e in self.entries.values()]})

    def forward(self,raw,signature,stage):
        import httpx
        payload=signature_event(raw,signature,get_settings().stripe_webhook_secret)
        result=httpx.post('http://127.0.0.1:18010/api/stripe/webhook',content=raw,headers={'Stripe-Signature':signature,'Content-Type':'application/json','X-QA-Delivery':self.token},timeout=35)
        audit('delivery.jsonl',{'event_id':payload['id'],'type':payload['type'],'stage':stage,'http':result.status_code,'body_sha256':hashlib.sha256(raw).hexdigest(),'signature_sha256':hashlib.sha256(signature.encode()).hexdigest(),'signature_age_seconds':time.time()-int(signature.split('t=')[1].split(',')[0]),'body':clean(result.json())})
        assert result.status_code==200, 'STOP backend rejected original signed payload'

    def capture(self,raw,signature):
        payload=signature_event(raw,signature,get_settings().stripe_webhook_secret)
        assert payload['livemode'] is False
        obj=payload['data']['object'];sid=obj.get('metadata',{}).get('submission_id')
        cases=read('manifest.json')['cases']
        if sid not in {c['submission_id'] for c in cases.values()}:return {'ignored':'outside_QA_manifest'}
        if sid!=cases['B-DELAY']['submission_id']:
            self.forward(raw,signature,'immediate-expire');return {'forwarded':True}
        assert self.armed, 'STOP B-DELAY event before retention armed'
        assert payload['type'] in SESSION_EVENTS|PI_EVENTS, 'STOP unexpected financial event'
        with self.lock:
            if payload['id'] in self.entries:
                assert self.entries[payload['id']]['raw']==raw
                return {'retained_duplicate':True}
            stamp=time.time();sha=hashlib.sha256(raw).hexdigest()
            e={'id':payload['id'],'type':payload['type'],'received_at':stamp,'raw':raw,'signature':signature,'body_sha256':sha,'signature_sha256':hashlib.sha256(signature.encode()).hexdigest()}
            self.entries[payload['id']]=e
            # Exact signed material is private; public evidence holds hashes and sanitized objects.
            save('private-envelope-'+payload['id']+'.json',{'body_base64':base64.b64encode(raw).decode(),'signature':signature})
            save('event-'+payload['id']+'.json',clean(payload))
            if self.first is None:
                self.first=stamp
                timer=threading.Timer(70,self.release);timer.daemon=True;timer.start()
            self.persist()
        return {'retained':True,'backend_delivered':False}

    def release(self):
        try:
            with self.lock:
                assert not self.released and self.first and 60<=time.time()-self.first<120
                entries=list(self.entries.values())
                assert {'payment_intent.succeeded','checkout.session.completed'}<={e['type'] for e in entries}, 'Missing real success events; no release'
            before=observe('B-DELAY','pre-delivery-auto')
            assert not before['database']['payment'] and not before['database']['deadlines'] and before['database']['evidence_count']==0
            assert any(o['session']['payment_status']=='paid' and o['payment_intent']['status']=='succeeded' for o in before['objects'])
            entries.sort(key=lambda e:e['type']!='payment_intent.succeeded')
            for stage in ['initial-delivery','duplicate-delivery']:
                for e in entries:
                    assert time.time()-self.first<120, 'STOP retention delivery window exceeded'
                    self.forward(e['raw'],e['signature'],stage)
            after=observe('B-DELAY','post-delivery-auto')
            assert after['database']['payment'] and len(after['database']['deadlines'])==1 and after['database']['payment_audits']==1
            with self.lock:self.released=True;self.persist()
        except Exception as exc:
            with self.lock:self.error=str(exc);self.persist()

def serve():
    C.identity();queue=Queue()
    class Proxy(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            try:
                assert self.path=='/api/stripe/webhook'
                size=int(self.headers.get('Content-Length','0'));assert 0<size<=1024*1024
                result=queue.capture(self.rfile.read(size),self.headers.get('Stripe-Signature',''))
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(result).encode())
            except Exception as exc:
                audit('proxy-rejections.jsonl',{'error':str(exc)})
                self.send_response(400);self.end_headers();self.wfile.write(b'{"rejected":true}')
    proxy=ThreadingHTTPServer(('127.0.0.1',18011),Proxy)
    threading.Thread(target=proxy.serve_forever,daemon=True).start()
    env=os.environ.copy();env['STRIPE_API_KEY']=C.BASE.stripe_secret_key
    cli=subprocess.Popen(['C:/Users/plher/Documents/stripe_cli/stripe.exe','listen','--skip-update','--events',','.join(sorted(SESSION_EVENTS|PI_EVENTS|RESTRICTION_EVENTS)),'--forward-to','http://127.0.0.1:18011/api/stripe/webhook'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    ready=threading.Event()
    def logs():
        for line in cli.stdout:
            secret=re.search(r'whsec_[A-Za-z0-9]+',line)
            if secret:os.environ['STRIPE_WEBHOOK_SECRET']=secret.group(0);get_settings.cache_clear();ready.set()
            with (OUT/'listener.log').open('a',encoding='utf-8') as f:f.write(re.sub(r'whsec_[A-Za-z0-9]+','[REDACTED]',line))
    threading.Thread(target=logs,daemon=True).start()
    try:
        assert ready.wait(25), 'No listener, no payment'
        @C.app.middleware('http')
        async def scope(request,call_next):
            path=request.url.path
            if path.startswith('/qa/'):
                if request.client.host!='127.0.0.1':return JSONResponse({},status_code=403)
                if path=='/qa/state':
                    with queue.lock:queue.persist()
                    return JSONResponse(read('retention-state.json'))
                if path=='/qa/arm' and request.method=='POST':
                    import httpx
                    invalid=httpx.post('http://127.0.0.1:18011/api/stripe/webhook',content=b'{}',headers={'Stripe-Signature':'invalid'},timeout=5)
                    assert invalid.status_code==400
                    assert not queue.entries and not local_counts(read('manifest.json')['cases']['B-DELAY'])['payment']
                    with queue.lock:queue.armed=True;queue.persist()
                    save('retention-selftest.json',{'invalid_signature_rejected':True,'raw_body_reencoded':False,'all_event_types_held':True,'dedicated_forward_port':18011,'backend_requires_QA_delivery_nonce':True})
                    return JSONResponse({'armed':True,'release_after_seconds':70,'abort_after_seconds':120})
                if path.startswith('/qa/observe/'):
                    name,label=path.split('/')[3:5]
                    import asyncio
                    result=await asyncio.to_thread(observe,name,label)
                    return JSONResponse(summarize(result))
                return JSONResponse({},status_code=404)
            if path=='/api/stripe/webhook':
                raw=await request.body();sig=request.headers.get('stripe-signature','')
                try:payload=signature_event(raw,sig,get_settings().stripe_webhook_secret)
                except HTTPException:return JSONResponse({'detail':'invalid_stripe_signature'},status_code=400)
                sid=payload.get('data',{}).get('object',{}).get('metadata',{}).get('submission_id')
                if sid not in {c['submission_id'] for c in read('manifest.json')['cases'].values()}:return JSONResponse({'outside_QA':True},status_code=200)
                if request.headers.get('x-qa-delivery')!=queue.token:
                    audit('bypass-rejected.jsonl',{'event_id':payload['id']});return JSONResponse({'detail':'QA_proxy_required'},status_code=403)
                audit('backend-envelopes.jsonl',{'event_id':payload['id'],'body_sha256':hashlib.sha256(raw).hexdigest(),'signature_sha256':hashlib.sha256(sig.encode()).hexdigest()})
            if path.startswith('/api/submissions/') and path.split('/')[3] not in {c['submission_id'] for c in read('manifest.json')['cases'].values()}:
                return JSONResponse({'outside_QA':True},status_code=403)
            response=await call_next(request)
            if path.endswith('/stripe-checkout'):
                raw=b''.join([b async for b in response.body_iterator]);data=json.loads(raw)
                audit('checkout-api.jsonl',{'path':path,'http':response.status_code,'body':clean(data),'url_present':bool(data.get('url'))})
                return JSONResponse(data,status_code=response.status_code,headers=dict(response.headers))
            return response
        def sql_guard(conn,cursor,statement,parameters,context,executemany):
            assert statement.lstrip().split()[0].upper() in {'SELECT','INSERT','UPDATE','SET','SHOW','ROLLBACK','SAVEPOINT','RELEASE'}, 'Forbidden schema/purge'
        event.listen(get_engine(),'before_cursor_execute',sql_guard)
        import uvicorn
        print('QA_PHASE2_READY backend=18010 proxy=18011 TEST spectra_test',flush=True)
        uvicorn.run(C.app,host='127.0.0.1',port=18010,log_level='warning')
    finally:
        cli.terminate();cli.wait(timeout=10);proxy.shutdown()

def finalize():
    before=read('before.json');development=C.fingerprint(C.VALUES['DATABASE_URL']);test=C.fingerprint(C.TARGET)
    expire_case=read('manifest.json')['cases']['B-EXPIRE'];delay_case=read('manifest.json')['cases']['B-DELAY']
    ex=observe('B-EXPIRE','final');de=observe('B-DELAY','final')
    for result in [ex,de]:
        for evidence in result['database']['evidence']:
            if evidence['event_id'].startswith('evt_'):
                canonical=StripeGateway(get_settings()).get('events',evidence['event_id'])
                assert canonical['livemode'] is False
                save('canonical-event-'+evidence['event_id']+'.json',clean(canonical))
    assert not ex['database']['payment'] and not ex['database']['deadlines'] and len(ex['database']['attempts'])==2
    assert de['database']['payment'] and len(de['database']['deadlines'])==1 and de['database']['payment_audits']==1 and len(de['database']['attempts'])==1
    event_row=next(json.loads(p.read_text(encoding='utf-8')) for p in OUT.glob('event-evt_*.json') if json.loads(p.read_text(encoding='utf-8'))['type']=='payment_intent.succeeded')
    payment=de['database']['payment'];deadline=de['database']['deadlines'][0]
    verified=datetime.fromisoformat(str(payment['verified_at']));recorded=datetime.fromisoformat(str(payment['recorded_at']))
    provider=datetime.fromtimestamp(event_row['created'],timezone.utc)
    assert verified==provider and recorded-verified>=timedelta(seconds=60)
    assert datetime.fromisoformat(str(deadline['dispatch_deadline']))==provider+timedelta(days=30)
    state=read('retention-state.json');assert state['released'] and not state['error']
    delivered=[json.loads(l) for l in (OUT/'delivery.jsonl').read_text().splitlines() if 'delivery' in json.loads(l)['stage']]
    backend=[json.loads(l) for l in (OUT/'backend-envelopes.jsonl').read_text().splitlines()]
    assert all(any(b['event_id']==d['event_id'] and b['body_sha256']==d['body_sha256'] and b['signature_sha256']==d['signature_sha256'] for b in backend) for d in delivered)
    duplicates=[d for d in delivered if d['stage']=='duplicate-delivery']
    assert len(duplicates)>=2 and recorded<min(datetime.fromisoformat(d['at']) for d in duplicates)
    protected={}
    for name in ['B-DECLINE','B-3DS']:
        original=json.loads((P1/(name+'-final.json')).read_text(encoding='utf-8'))
        case=json.loads((P1/'manifest.json').read_text(encoding='utf-8'))['cases'][name]
        current=local_counts(case)
        assert json.loads(json.dumps(current['payment'],default=str))==original['database_payment']
        assert json.loads(json.dumps(current['deadlines'],default=str))==original['deadlines']
        assert current['snapshot_sha256']==case['snapshot_sha256']
        protected[name]=True
    assert payment['amount_minor']==2500 and len(read('session-ledger.json'))==2
    result={'identity':C.identity(),'development_unchanged':before['development']==development,'test_schema_unchanged':before['test']['_schema']==test['_schema'],'sources_and_env_unchanged':before['sources']==sources(),'phase1_paid_cases_unchanged':protected,'revision':test['_revision'],'new_test_payments':1,'amount_minor':payment['amount_minor'],'provider_paid_at':provider.isoformat(),'recorded_at':recorded.isoformat(),'lag_seconds':(recorded-verified).total_seconds(),'dispatch_deadline':str(deadline['dispatch_deadline']),'signature_and_raw_hashes_match':True,'retained_events':len(state['entries']),'delivery_attempts':len(delivered),'B-EXPIRE':summarize(ex),'B-DELAY':summarize(de)}
    save('isolation-final.json',result);print(json.dumps(result,default=str))
    assert result['development_unchanged'] and result['test_schema_unchanged'] and result['sources_and_env_unchanged']

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='expire':expire()
    elif sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='observe':print(json.dumps(summarize(observe(sys.argv[2],sys.argv[3]))))
    elif sys.argv[1]=='finalize':finalize()
