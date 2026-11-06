"""Authorized B-DISPUTE only: one hosted TEST Checkout; no dispute/refund writes."""
import asyncio
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
from datetime import datetime, timezone
from uuid import UUID, uuid5, NAMESPACE_URL

import control as C
import control_phase2 as P
import control_b2 as B
from sqlalchemy import event, select, func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_engine
from app.stripe_checkout import StripeGateway, signature_event, SESSION_EVENTS, PI_EVENTS
from app.commercial_models import ShipmentDeclaration
from fastapi.responses import JSONResponse
from fastapi import HTTPException

OUT=C.ROOT/'validation_artifacts/stripe_sandbox_b_dispute'
OUT.mkdir(parents=True,exist_ok=True)
C.OUT=P.OUT=B.OUT=OUT
B.CASES=['B-DISPUTE']
save,read=C.save,C.read
NAME='B-DISPUTE'
DISPUTE_EVENTS={'charge.dispute.'+s for s in ['created','updated','closed','funds_withdrawn','funds_reinstated']}
EVENTS=((SESSION_EVENTS|PI_EVENTS)-{'checkout.session.expired','payment_intent.canceled'})|DISPUTE_EVENTS
lock=threading.RLock()

def normalized(v):return json.loads(json.dumps(v,default=str))
def case():return read('manifest.json')['cases'][NAME]
def stamp():return datetime.now(timezone.utc).isoformat()

def guarded(self,method,path,data=None,key=None):
    C.identity()
    if method=='POST':
        assert path=='checkout/sessions','STOP forbidden Stripe mutation'
        result=C.guarded(self,method,path,data,key)
        assert result['metadata']['submission_id']==case()['submission_id']
        P.audit('stripe-operations.jsonl',{'method':method,'path':path,'session_id':result['id'],'key':key})
        return result
    assert method=='GET','STOP forbidden Stripe mutation'
    # Canonical links are checked on every result, including webhook resolution.
    assert re.fullmatch(r'(account|checkout/sessions/cs_test_[A-Za-z0-9]+|payment_intents/pi_[A-Za-z0-9]+|charges/ch_[A-Za-z0-9]+|events/evt_[A-Za-z0-9]+|disputes/[A-Za-z0-9_]+|(?:refunds|disputes)\?charge=ch_[A-Za-z0-9]+&limit=100|events\?type=payment_intent\.succeeded&limit=100(?:&starting_after=evt_[A-Za-z0-9]+)?)',path),'STOP out-of-scope read'
    result=C.ORIGINAL(self,method,path,data,key)
    assert result.get('livemode',False) is False,'STOP LIVE object'
    if result.get('object') in {'checkout.session','payment_intent','charge'}:
        assert result['metadata']['submission_id']==case()['submission_id'],'STOP foreign object'
        assert result['metadata']['quote_id']==case()['quote_id']
        assert result['currency']=='eur'
    if result.get('object')=='dispute':
        ch=self.get('charges',result['charge'])
        assert result['livemode'] is False and result['amount']==2500 and result['currency']=='eur'
        assert result.get('payment_intent') in (None,ch['payment_intent'])
    if path.startswith(('refunds?','disputes?')):
        charge=path.split('charge=')[1].split('&')[0]
        self.get('charges',charge)
        assert not result['has_more'] and all(x['charge']==charge and x.get('livemode',False) is False for x in result['data'])
    return result

StripeGateway.call=guarded

def prepare():
    (OUT/'.gitignore').write_text('private-*\nbrowser-command.json\n',encoding='utf-8')
    B.prepare()  # Existing application routes, one new customer/order/accepted quote.
    m=read('manifest.json');m.update(phase='B-DISPUTE',max_successful_payments=1,automatic_dispute_authorized=True,card_last4='3810',refunds_authorized=False)
    save('manifest.json',m)
    c=case();assert c['submission_id'] not in {'c54cbac8-5098-423c-946f-02d7ec8d3915','d4dd84bf-5112-4301-a66c-cb51e2fdc4fd'}

def history(state):
    return normalized({k:state[k] for k in ['payment','deadlines','payment_audits','snapshot_sha256']})

def observe(label):
    result=P.observe(NAME,label);g=StripeGateway(get_settings());disputes=[]
    assert len(result['database']['attempts'])<=1
    for o in result['objects']:
        s,pi,ch=o['session'],o['payment_intent'],o['charge']
        a=result['database']['attempts'][0]
        expected={'submission_id':case()['submission_id'],'quote_id':case()['quote_id'],'obligation_id':case()['quote_id'],'customer_id':case()['customer_id'],'attempt_id':a['id']}
        assert s['metadata']==expected and s['mode']=='payment' and s['amount_total']==2500
        if pi:
            assert pi['metadata']==expected and s['payment_intent']==pi['id'] and pi['amount']==2500
        if ch:
            assert ch['metadata']==expected and ch['payment_intent']==pi['id'] and ch['amount']==2500
            refunds=g.call('GET','refunds?charge='+ch['id']+'&limit=100')
            assert not refunds['data'] and ch['amount_refunded']==0,'STOP unexpected refund'
            listed=g.call('GET','disputes?charge='+ch['id']+'&limit=100')
            disputes=[g.get('disputes',d['id']) for d in listed['data']]
            assert len(disputes)<=1,'STOP multiple disputes'
            for d in disputes:
                assert d['reason']=='fraudulent' and d['status']=='needs_response','STOP unexpected dispute'
                assert ch['disputed'] is True and ch['paid'] and ch['captured']
                assert s['status']=='complete' and s['payment_status']=='paid' and pi['status']=='succeeded'
                assert pi['amount_received']==ch['amount_captured']==2500
                assert d['evidence_details']['submission_count']==0 and not d['evidence_details']['has_evidence']
    result['disputes']=C.clean(disputes)
    state=result['database'];n=int(bool(state['payment']))
    assert len(state['deadlines'])==state['payment_audits']==n,'STOP inconsistent payment/deadline'
    if n:
        assert state['payment']['amount_minor']==2500
        assert state['deadlines'][0]['dispatch_deadline']-state['deadlines'][0]['verified_payment_at']==P.timedelta(days=30)
        if (OUT/'confirmed-history.json').exists():assert history(state)==read('confirmed-history.json'),'STOP historical financial change'
        else:save('confirmed-history.json',history(state))
    if (OUT/'restricted-history.json').exists():assert history(state)==read('restricted-history.json'),'STOP credit/history changed after restriction'
    if result['commercial']['payment_status']=='restricted':
        assert not result['commercial']['charging_enabled'] and 'dispute_review' in result['commercial']['financial_restrictions']
        if not (OUT/'restricted-history.json').exists():save('restricted-history.json',history(state))
    save(NAME+'-'+label+'.json',result)
    summary=P.summarize(result);summary.update(disputes=[{k:d.get(k) for k in ['id','charge','payment_intent','amount','currency','status','reason','created']} for d in disputes],at=result['at'])
    return summary

def check(nonce):
    import httpx
    before=observe('before-replay');assert before['SELBY']=='restricted' and len(before['disputes'])==1
    c=case();path='/api/submissions/'+c['submission_id'];state=P.local_counts(c)
    with Session(get_engine()) as db:
        declarations=db.scalar(select(func.count()).select_from(ShipmentDeclaration).where(ShipmentDeclaration.submission_id==UUID(c['submission_id'])))
    with C.client_for(NAME) as client:
        checkout=client.post(path+'/stripe-checkout',json={'quote_id':c['quote_id']})
        shipment=client.post(path+'/shipment-declarations',json={'request_key':str(uuid5(NAMESPACE_URL,'B-DISPUTE-REJECT-'+c['submission_id'])),'tracking':'QA-MUST-BE-REJECTED'})
    assert checkout.status_code==shipment.status_code==409,'STOP commercial operation accepted'
    assert checkout.json()['detail']=='payment_already_verified_or_restricted'
    expected='payment_financial_restriction' if state['payment'] else 'verified_payment_required_before_dispatch'
    assert shipment.json()['detail']==expected
    save('rejected-actions.json',{'checkout':{'http':checkout.status_code,'body':checkout.json()},'shipment':{'http':shipment.status_code,'body':shipment.json()}})
    with lock:envelopes=[json.loads(p.read_text(encoding='utf-8')) for p in OUT.glob('private-envelope-evt_*.json')]
    replayed=[];expired=[]
    for e in envelopes:
        raw=base64.b64decode(e['body_base64']);sig=e['signature'];age=time.time()-int(sig.split('t=')[1].split(',')[0])
        if age>=240:expired.append(e['event_id']);continue
        payload=signature_event(raw,sig,get_settings().stripe_webhook_secret)
        response=httpx.post('http://127.0.0.1:18010/api/stripe/webhook',content=raw,headers={'Stripe-Signature':sig,'Content-Type':'application/json','X-QA-Replay':nonce},timeout=40)
        assert response.status_code==200,'STOP replay rejected'
        replayed.append(payload['id']);P.audit('replays.jsonl',{'event_id':payload['id'],'http':response.status_code,'body_sha256':hashlib.sha256(raw).hexdigest(),'signature_age_seconds':age})
    assert replayed,'STOP no valid original signature to replay'
    after=observe('after-replay');new=P.local_counts(c)
    assert normalized(new)==normalized(state),'STOP replay changed financial/evidence state'
    with Session(get_engine()) as db:
        assert declarations==db.scalar(select(func.count()).select_from(ShipmentDeclaration).where(ShipmentDeclaration.submission_id==UUID(c['submission_id'])))==0
    result={'passed':True,'replayed':replayed,'expired_not_resigned':expired,'database_unchanged':True,'checkout_http':409,'shipment_http':409,'branch':str(after['payment_count'])+'/'+str(after['deadline_count']),'dispute':after['disputes'][0]}
    save('conformity.json',result);return result

def serve():
    C.identity();nonce=secrets.token_urlsafe(32);env=os.environ.copy();env['STRIPE_API_KEY']=C.BASE.stripe_secret_key
    cli=subprocess.Popen(['C:/Users/plher/Documents/stripe_cli/stripe.exe','listen','--skip-update','--events',','.join(sorted(EVENTS)),'--forward-to','http://127.0.0.1:18010/api/stripe/webhook'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    ready=threading.Event()
    def logs():
        for line in cli.stdout:
            secret=re.search(r'whsec_[A-Za-z0-9]+',line)
            if secret:os.environ['STRIPE_WEBHOOK_SECRET']=secret.group(0);get_settings.cache_clear();ready.set()
            with (OUT/'listener.log').open('a',encoding='utf-8') as f:f.write(re.sub(r'whsec_[A-Za-z0-9]+','[REDACTED]',line))
    threading.Thread(target=logs,daemon=True).start()
    try:
        assert ready.wait(25),'STOP no listener; no payment'
        @C.app.middleware('http')
        async def scope(request,call_next):
            path=request.url.path
            if path.startswith('/qa/'):
                if request.client.host!='127.0.0.1':return JSONResponse({},status_code=403)
                if path.startswith('/qa/observe/'):
                    result=await asyncio.to_thread(observe,path.split('/')[-1]);return JSONResponse(result)
                if path=='/qa/check':return JSONResponse(await asyncio.to_thread(check,nonce))
                return JSONResponse({},status_code=404)
            if path=='/api/stripe/webhook':
                raw=await request.body();sig=request.headers.get('stripe-signature','')
                try:payload=signature_event(raw,sig,get_settings().stripe_webhook_secret)
                except HTTPException:return JSONResponse({'detail':'invalid_stripe_signature'},status_code=400)
                obj=payload.get('data',{}).get('object',{});kind=payload.get('type')
                sid=obj.get('metadata',{}).get('submission_id')
                if kind in DISPUTE_EVENTS:
                    # Dispute metadata is usually empty: resolve its canonical Charge.
                    ch=C.ORIGINAL(StripeGateway(get_settings()),'GET','charges/'+obj['charge'])
                    assert ch.get('livemode') is False
                    sid=ch.get('metadata',{}).get('submission_id')
                    if sid==case()['submission_id']:
                        pi=StripeGateway(get_settings()).get('payment_intents',ch['payment_intent'])
                        assert pi['metadata']['submission_id']==sid and obj.get('payment_intent') in (None,pi['id'])
                if payload.get('livemode') is not False or sid!=case()['submission_id']:return JSONResponse({'ignored':'outside_QA_manifest'},status_code=200)
                assert kind in EVENTS,'STOP unexpected event'
                with lock:
                    if not (OUT/('private-envelope-'+payload['id']+'.json')).exists():save('private-envelope-'+payload['id']+'.json',{'event_id':payload['id'],'body_base64':base64.b64encode(raw).decode(),'signature':sig,'received_at':stamp()})
                    save('event-'+payload['id']+'.json',C.clean(payload))
                response=await call_next(request)
                P.audit('webhooks.jsonl',{'event_id':payload['id'],'type':kind,'http':response.status_code,'replay':request.headers.get('X-QA-Replay')==nonce,'body_sha256':hashlib.sha256(raw).hexdigest(),'signature_sha256':hashlib.sha256(sig.encode()).hexdigest(),'provider_created':payload['created'],'api_version':payload.get('api_version')})
                assert response.status_code==200,'STOP webhook rejected'
                return response
            if path.startswith('/api/submissions/') and path.split('/')[3]!=case()['submission_id']:return JSONResponse({'outside_QA':True},status_code=403)
            response=await call_next(request)
            if path.endswith('/stripe-checkout'):
                raw=b''.join([b async for b in response.body_iterator]);data=json.loads(raw)
                P.audit('checkout-api.jsonl',{'path':path,'http':response.status_code,'body':C.clean(data),'url_present':bool(data.get('url'))})
                return JSONResponse(data,status_code=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'})
            return response
        def sql_guard(conn,cursor,statement,parameters,context,executemany):
            assert statement.lstrip().split()[0].upper() in {'SELECT','INSERT','UPDATE','SET','SHOW','ROLLBACK','SAVEPOINT','RELEASE'},'DDL/purge forbidden'
        event.listen(get_engine(),'before_cursor_execute',sql_guard)
        import uvicorn
        print('QA_B_DISPUTE_READY TEST spectra_test port=18010',flush=True)
        uvicorn.run(C.app,host='127.0.0.1',port=18010,log_level='warning')
    finally:cli.terminate();cli.wait(timeout=10)

def finalize():
    observe('final');before=read('before.json');rows=B.existing_rows();dev=C.fingerprint(C.VALUES['DATABASE_URL']);test=C.fingerprint(C.TARGET)
    checks={'development_unchanged':dev==before['development'],'all_preexisting_test_rows_unchanged':all(all(rows['rows'].get(t,{}).get(h,0)>=n for h,n in v.items()) for t,v in before['existing_test_rows']['rows'].items()),'test_columns_unchanged':test['_schema']==before['test']['_schema'],'constraints_indexes_triggers_unchanged':rows['schema_definitions_sha256']==before['existing_test_rows']['schema_definitions_sha256'],'application_frontend_env_unchanged':P.sources()==before['sources'],'revision':test['_revision'],'identity':C.identity()}
    save('integrity-final.json',checks);assert all(v is True for k,v in checks.items() if k.endswith('unchanged'))
    print(json.dumps(checks))

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='observe':print(json.dumps(observe(sys.argv[2])))
    elif sys.argv[1]=='finalize':finalize()
