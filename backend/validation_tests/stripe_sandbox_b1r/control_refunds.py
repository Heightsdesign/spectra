"""Two explicitly authorized TEST refunds only; no payment/expiry/dispute writes."""
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
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid5, NAMESPACE_URL

import control as C
import control_phase2 as P
import control_b2 as B
from sqlalchemy import select, text, event, func
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_engine
from app.customer_models import CustomerSession
from app.auth import now, digest
from app.commercial_models import ShipmentDeclaration, CommercialEvent
from app.stripe_models import StripeAttempt, StripeEvidence
from app.stripe_checkout import StripeGateway, signature_event
from fastapi import HTTPException
from fastapi.responses import JSONResponse

PREP=C.ROOT/'validation_artifacts/stripe_sandbox_b2/preparation'
OUT=C.ROOT/'validation_artifacts/stripe_sandbox_b2/refunds'
OUT.mkdir(parents=True,exist_ok=True)
C.OUT=P.OUT=B.OUT=OUT
save,read=C.save,C.read
AMOUNTS={'B-REFUND-PARTIAL':500,'B-REFUND-FULL':2500}
targets=json.loads((PREP/'refund-targets.json').read_text(encoding='utf-8'))
TARGET_HASH=hashlib.sha256((PREP/'refund-targets.json').read_bytes()).hexdigest()
envelope_lock=threading.RLock()

def normalized(value):return json.loads(json.dumps(value,default=str))

def guard_manifest():
    assert hashlib.sha256((PREP/'refund-targets.json').read_bytes()).hexdigest()==read('manifest.json')['preparation_manifest_sha256'],'STOP manifest changed'
    assert set(targets)==set(AMOUNTS)
    for field in ['charge_id','payment_intent_id','submission_id','quote_id','session_id']:
        assert len({v[field] for v in targets.values()})==2,'STOP targets not distinct'
    for name,t in targets.items():
        assert t['name']==name and t['account_id']==C.BASE.stripe_account_id and t['test_only'] is True and t['currency']=='eur' and t['paid_minor']==2500

def guarded(self,method,path,data=None,key=None):
    C.identity();guard_manifest()
    # Refund creation is only available in mutate(), after the complete preflight.
    assert method=='GET','STOP no gateway mutations allowed'
    allowed={'account'}|{resource+'/'+t[field] for t in targets.values() for resource,field in [('checkout/sessions','session_id'),('payment_intents','payment_intent_id'),('charges','charge_id')]}
    is_refund_list=any(path=='refunds?charge='+t['charge_id']+'&limit=100' for t in targets.values())
    is_event=bool(re.fullmatch(r'events/evt_[A-Za-z0-9]+',path))
    is_refund=bool(re.fullmatch(r'refunds/re_[A-Za-z0-9]+',path))
    assert path in allowed or is_refund_list or is_event or is_refund,'STOP out-of-scope read'
    result=C.ORIGINAL(self,method,path,data,key)
    assert result.get('livemode',False) is False
    if is_refund_list:
        assert not result.get('has_more'),'STOP refund pagination needs review'
        assert all(r['charge'] in {t['charge_id'] for t in targets.values()} for r in result['data'])
    if is_refund:assert result['charge'] in {t['charge_id'] for t in targets.values()}
    return result

StripeGateway.call=guarded

def canonical(name,unrefunded=False):
    guard_manifest();identity=C.identity();t=targets[name];g=StripeGateway(get_settings())
    s=g.get('checkout/sessions',t['session_id']);pi=g.get('payment_intents',t['payment_intent_id']);ch=g.get('charges',t['charge_id'])
    for o in [s,pi,ch]:assert o.get('livemode') is False and o['currency']=='eur','STOP live/currency mismatch'
    expected={'attempt_id':t['attempt_id'],'quote_id':t['quote_id'],'obligation_id':t['quote_id'],'submission_id':t['submission_id'],'customer_id':t['customer_id']}
    assert s['metadata']==pi['metadata']==ch['metadata']==expected,'STOP metadata mismatch'
    assert s['payment_intent']==pi['id']==ch['payment_intent']==t['payment_intent_id'] and pi['latest_charge']==ch['id']==t['charge_id']
    assert s['status']=='complete' and s['payment_status']=='paid' and pi['status']=='succeeded'
    assert s['amount_total']==pi['amount']==pi['amount_received']==ch['amount']==ch['amount_captured']==2500
    assert ch['paid'] is True and ch['captured'] is True and ch['disputed'] is False,'STOP financial mismatch/dispute'
    refunds=g.call('GET','refunds?charge='+ch['id']+'&limit=100')
    if unrefunded:assert ch['amount_refunded']==0 and not ch['refunded'] and not refunds['data'],'STOP prior refund'
    result={'identity':identity,'session':C.clean(s),'payment_intent':C.clean(pi),'charge':C.clean(ch),'refunds':C.clean(refunds['data'])}
    return result

def immutable(name):
    state=P.local_counts(targets[name])
    with Session(get_engine()) as db:
        a=db.get(StripeAttempt,UUID(targets[name]['attempt_id']))
        values={c.name:getattr(a,c.name) for c in StripeAttempt.__table__.columns if c.name!='status'}
    return normalized({'payment':state['payment'],'deadlines':state['deadlines'],'snapshot_sha256':state['snapshot_sha256'],'payment_audits':state['payment_audits'],'attempt_static_sha256':hashlib.sha256(json.dumps(values,sort_keys=True,default=str).encode()).hexdigest()})

def assert_history(name):
    expected=read('before.json')['historical'][name]
    assert immutable(name)==expected,'STOP historical financial data changed'
    state=P.local_counts(targets[name]);assert len(state['attempts'])==1 and state['payment']['amount_minor']==2500 and len(state['deadlines'])==1
    return state

def prepare():
    assert not (OUT/'manifest.json').exists(),'STOP existing execution; never repeat preparation'
    identity=C.identity()
    manifest={'phase':'B2-authorized-refunds','preparation_manifest_sha256':TARGET_HASH,'identity':identity,'cases':targets,'authorized_amounts_minor':AMOUNTS,'currency':'eur','no_additional_payments':True}
    save('manifest.json',manifest);guard_manifest()
    before={'development':C.fingerprint(C.VALUES['DATABASE_URL']),'test':C.fingerprint(C.TARGET),'sources':P.sources(),'rows':B.existing_rows(),'historical':{},'mutable_attempt_row_hashes':[]}
    for name,t in targets.items():
        objects=canonical(name,unrefunded=True);save(name+'-preflight.json',objects)
        before['historical'][name]=immutable(name)
        original=json.loads((PREP/(name+'-final.json')).read_text(encoding='utf-8'))
        assert before['historical'][name]['payment']==original['database']['payment']
        assert before['historical'][name]['deadlines']==original['database']['deadlines']
        assert before['historical'][name]['snapshot_sha256']==t['snapshot_sha256']
        with get_engine().connect() as conn:
            row=conn.execute(text('select to_jsonb(t)::text from stripe_attempts t where id=:id'),{'id':UUID(t['attempt_id'])}).scalar_one()
            before['mutable_attempt_row_hashes'].append(hashlib.sha256(row.encode()).hexdigest())
    assert before['development']['_revision']==before['test']['_revision']==['0015']
    save('before.json',before)
    (OUT/'private-next-env-before.txt').write_bytes((C.ROOT.parent/'frontend/next-env.d.ts').read_bytes())
    access=json.loads((PREP/'private-access.json').read_text(encoding='utf-8'))
    with Session(get_engine()) as db:
        for name,t in targets.items():
            token=secrets.token_urlsafe(32);db.add(CustomerSession(customer_id=UUID(t['customer_id']),token_hash=digest(token),expires_at=now()+timedelta(hours=4)));access[name]['token']=token
        db.commit()
    save('private-access.json',access)
    print(json.dumps({'preflight_passed':True,'identity':identity,'targets_distinct':True,'prior_refunds':0,'prior_disputes':0,'authorized_amounts_minor':AMOUNTS}))

def mutate(name):
    assert name in AMOUNTS
    if name=='B-REFUND-FULL':assert read('B-REFUND-PARTIAL-conformity.json')['passed'] is True,'STOP partial not fully validated'
    assert not (OUT/(name+'-mutation-reserved.json')).exists(),'STOP already submitted/ambiguous; read-only reconciliation required'
    before=canonical(name,unrefunded=True);assert_history(name)
    save(name+'-immediate-before-mutation.json',before)
    key='selby-b2-'+name.lower()+'-'+str(AMOUNTS[name])+'-'+targets[name]['charge_id']
    data={'charge':targets[name]['charge_id'],'amount':str(AMOUNTS[name]),'metadata[qa_case]':name,'metadata[submission_id]':targets[name]['submission_id'],'metadata[quote_id]':targets[name]['quote_id']}
    reservation={'case':name,'charge_id':targets[name]['charge_id'],'payment_intent_id':targets[name]['payment_intent_id'],'amount_minor':AMOUNTS[name],'idempotency_key':key,'request':data,'identity':C.identity()}
    # Persist before network; never automatically retry an ambiguous refund.
    save(name+'-mutation-reserved.json',reservation)
    result=C.ORIGINAL(StripeGateway(get_settings()),'POST','refunds',data,key)
    save(name+'-refund-response.json',C.clean(result))
    assert result['charge']==targets[name]['charge_id'] and result['payment_intent']==targets[name]['payment_intent_id'] and result['amount']==AMOUNTS[name] and result['currency']=='eur','STOP refund identity mismatch'
    assert result.get('livemode',False) is False and result['status']=='succeeded','STOP refund not succeeded; no further mutation'
    P.audit('mutations.jsonl',{'case':name,'refund_id':result['id'],'charge_id':result['charge'],'amount':result['amount'],'status':result['status'],'idempotency_key':key})
    print(json.dumps({'case':name,'refund_id':result['id'],'amount_minor':result['amount'],'currency':result['currency'],'status':result['status'],'idempotency_key':key}))

def verify(name,label):
    objects=canonical(name);refunds=objects['refunds'];expected=AMOUNTS[name]
    assert len(refunds)==1 and refunds[0]['amount']==expected and refunds[0]['status']=='succeeded','STOP refund count/amount/status'
    assert refunds[0]['charge']==targets[name]['charge_id'] and refunds[0]['payment_intent']==targets[name]['payment_intent_id']
    refund=StripeGateway(get_settings()).get('refunds',refunds[0]['id'])
    assert refund['amount']==expected and refund['currency']=='eur' and refund['status']=='succeeded'
    assert objects['charge']['amount_refunded']==expected and objects['charge']['refunded']==(expected==2500),'STOP canonical cumulative amount'
    with C.client_for(name) as client:commercial=C.request(client,'GET','/api/submissions/'+targets[name]['submission_id']+'/commercial-state')
    state=assert_history(name)
    result={'case':name,'label':label,'objects':objects,'refund':C.clean(refund),'commercial':commercial,'database':state,'historical_unchanged':True}
    save(name+'-'+label+'.json',result)
    return result

def reject_new_actions(name):
    t=targets[name];path='/api/submissions/'+t['submission_id']
    before=P.local_counts(t)
    with Session(get_engine()) as db:declarations_before=db.scalar(select(func.count()).select_from(ShipmentDeclaration).where(ShipmentDeclaration.submission_id==UUID(t['submission_id'])))
    with C.client_for(name) as client:
        checkout=client.post(path+'/stripe-checkout',json={'quote_id':t['quote_id']})
        shipment=client.post(path+'/shipment-declarations',json={'request_key':str(uuid5(NAMESPACE_URL,'SELBY-B2-REFUND-REJECT-'+t['submission_id'])),'tracking':'QA-MUST-BE-REJECTED'})
    assert checkout.status_code==409 and checkout.json()['detail']=='payment_already_verified_or_restricted','STOP checkout protection'
    assert shipment.status_code==409 and shipment.json()['detail']=='payment_financial_restriction','STOP shipment protection'
    after=P.local_counts(t)
    with Session(get_engine()) as db:declarations_after=db.scalar(select(func.count()).select_from(ShipmentDeclaration).where(ShipmentDeclaration.submission_id==UUID(t['submission_id'])))
    assert len(before['attempts'])==len(after['attempts'])==1 and declarations_before==declarations_after==0
    result={'checkout':{'http':checkout.status_code,'body':checkout.json()},'shipment':{'http':shipment.status_code,'body':shipment.json()},'declarations_before':declarations_before,'declarations_after':declarations_after,'attempts':1}
    save(name+'-rejected-actions.json',result);return result

def check_and_replay(name,nonce):
    import httpx
    result=verify(name,'before-replay')
    assert result['commercial']['payment_status']=='restricted' and not result['commercial']['charging_enabled'],'STOP no financial restriction'
    label='partially_refunded' if AMOUNTS[name]==500 else 'refunded'
    assert label in result['commercial']['financial_restrictions'],'STOP wrong restriction label'
    actions=reject_new_actions(name)
    with envelope_lock:
        envelopes=[json.loads(p.read_text(encoding='utf-8')) for p in OUT.glob('private-envelope-evt_*.json')]
    envelopes=[e for e in envelopes if e['case']==name]
    assert envelopes,'STOP no real webhook captured'
    for envelope in envelopes:
        raw=base64.b64decode(envelope['body_base64']);signature=envelope['signature']
        payload=signature_event(raw,signature,get_settings().stripe_webhook_secret)
        age=time.time()-int(signature.split('t=')[1].split(',')[0]);assert age<240,'STOP replay signature too old; no re-signing'
        response=httpx.post('http://127.0.0.1:18010/api/stripe/webhook',content=raw,headers={'Stripe-Signature':signature,'Content-Type':'application/json','X-QA-Replay':nonce},timeout=35)
        P.audit('replays.jsonl',{'case':name,'event_id':payload['id'],'http':response.status_code,'body_sha256':hashlib.sha256(raw).hexdigest(),'signature_sha256':hashlib.sha256(signature.encode()).hexdigest(),'signature_age_seconds':age})
        assert response.status_code==200,'STOP signed replay rejected'
    after=verify(name,'after-replay')
    # Replays preserve both evidence rows and financial history, not just HTTP status.
    assert after['database']['evidence_count']==result['database']['evidence_count'],'STOP replay evidence duplicated/unsettled concurrent events'
    assert after['database']['payment_audits']==1 and len(after['database']['deadlines'])==1
    assert after['objects']['charge']['amount_refunded']==AMOUNTS[name] and len(after['objects']['refunds'])==1
    amounts=[e['data'].get('amount_refunded_minor',0) or 0 for e in after['database']['evidence'] if e['restricted']]
    assert max(amounts,default=0)==AMOUNTS[name] and all(a<=AMOUNTS[name] for a in amounts)
    summary={'case':name,'passed':True,'refund_id':after['refund']['id'],'refunded_minor':AMOUNTS[name],'SELBY':'restricted','restrictions':after['commercial']['financial_restrictions'],'historical_unchanged':True,'checkout_http':actions['checkout']['http'],'shipment_http':actions['shipment']['http'],'replayed_events':len(envelopes),'evidence_count_stable':True,'unique_refunds':1,'payment_count':1,'deadline_count':1,'max_cumulative_refund_evidence_minor':max(amounts)}
    save(name+'-conformity.json',summary);return summary

def serve():
    C.identity();guard_manifest();nonce=secrets.token_urlsafe(32)
    env=os.environ.copy();env['STRIPE_API_KEY']=C.BASE.stripe_secret_key
    cli=subprocess.Popen(['C:/Users/plher/Documents/stripe_cli/stripe.exe','listen','--skip-update','--events','charge.refunded,refund.created,refund.updated,refund.failed','--forward-to','http://127.0.0.1:18010/api/stripe/webhook'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    ready=threading.Event()
    def logs():
        for line in cli.stdout:
            secret=re.search(r'whsec_[A-Za-z0-9]+',line)
            if secret:os.environ['STRIPE_WEBHOOK_SECRET']=secret.group(0);get_settings.cache_clear();ready.set()
            with (OUT/'listener.log').open('a',encoding='utf-8') as f:f.write(re.sub(r'whsec_[A-Za-z0-9]+','[REDACTED]',line))
    threading.Thread(target=logs,daemon=True).start()
    try:
        assert ready.wait(25),'STOP no listener; no refund'
        @C.app.middleware('http')
        async def scope(request,call_next):
            path=request.url.path
            if path.startswith('/qa/check/'):
                if request.client.host!='127.0.0.1':return JSONResponse({},status_code=403)
                name=path.split('/')[3];assert name in AMOUNTS
                import asyncio
                summary=await asyncio.to_thread(check_and_replay,name,nonce)
                return JSONResponse(summary)
            if path.startswith('/qa/observe/'):
                name,label=path.split('/')[3:5];assert name in AMOUNTS
                import asyncio
                result=await asyncio.to_thread(verify,name,label)
                return JSONResponse({'case':name,'status':result['commercial']['payment_status'],'restrictions':result['commercial']['financial_restrictions'],'refunded_minor':result['objects']['charge']['amount_refunded']})
            if path=='/api/stripe/webhook':
                raw=await request.body();signature=request.headers.get('stripe-signature','')
                try:payload=signature_event(raw,signature,get_settings().stripe_webhook_secret)
                except HTTPException:return JSONResponse({'detail':'invalid_stripe_signature'},status_code=400)
                obj=payload.get('data',{}).get('object',{});kind=payload.get('type')
                charge_id=obj.get('id') if kind=='charge.refunded' else obj.get('charge')
                name=next((n for n,t in targets.items() if t['charge_id']==charge_id),None)
                if not name or payload.get('livemode') is not False:return JSONResponse({'ignored':'outside_QA_manifest'},status_code=200)
                assert kind in {'charge.refunded','refund.created','refund.updated','refund.failed'},'STOP unexpected event'
                if kind!='charge.refunded':assert obj.get('payment_intent') in (None,targets[name]['payment_intent_id'])
                with envelope_lock:
                    if not (OUT/('private-envelope-'+payload['id']+'.json')).exists():
                        save('private-envelope-'+payload['id']+'.json',{'case':name,'body_base64':base64.b64encode(raw).decode(),'signature':signature})
                    save('event-'+payload['id']+'.json',C.clean(payload))
                response=await call_next(request)
                P.audit('webhooks.jsonl',{'case':name,'event_id':payload['id'],'type':kind,'http':response.status_code,'replay':request.headers.get('x-qa-replay')==nonce,'body_sha256':hashlib.sha256(raw).hexdigest(),'signature_sha256':hashlib.sha256(signature.encode()).hexdigest()})
                return response
            if path.startswith('/api/submissions/') and path.split('/')[3] not in {t['submission_id'] for t in targets.values()}:
                return JSONResponse({'outside_QA':True},status_code=403)
            return await call_next(request)
        def sql_guard(conn,cursor,statement,parameters,context,executemany):
            assert statement.lstrip().split()[0].upper() in {'SELECT','INSERT','UPDATE','SET','SHOW','ROLLBACK','SAVEPOINT','RELEASE'},'STOP DDL/purge'
        event.listen(get_engine(),'before_cursor_execute',sql_guard)
        import uvicorn
        print('QA_B2_REFUNDS_READY TEST spectra_test port=18010',flush=True)
        uvicorn.run(C.app,host='127.0.0.1',port=18010,log_level='warning')
    finally:cli.terminate();cli.wait(timeout=10)

def finalize():
    before=read('before.json');summaries={}
    for name in AMOUNTS:
        assert read(name+'-conformity.json')['passed'] is True
        result=verify(name,'final');summaries[name]=read(name+'-conformity.json')
        for evidence in result['database']['evidence']:
            if evidence['event_id'].startswith('evt_'):
                canonical_event=StripeGateway(get_settings()).get('events',evidence['event_id']);save('canonical-event-'+evidence['event_id']+'.json',C.clean(canonical_event))
    current=B.existing_rows();allowed=set(before['mutable_attempt_row_hashes'])
    unrelated=all(all(current['rows'].get(table,{}).get(h,0)>=n or (table=='stripe_attempts' and h in allowed) for h,n in rows.items()) for table,rows in before['rows']['rows'].items())
    dev=C.fingerprint(C.VALUES['DATABASE_URL']);test=C.fingerprint(C.TARGET)
    result={'identity':C.identity(),'development_unchanged':dev==before['development'],'preexisting_rows_unchanged_except_target_attempt_status':unrelated,'schema_columns_unchanged':test['_schema']==before['test']['_schema'],'constraints_indexes_triggers_unchanged':current['schema_definitions_sha256']==before['rows']['schema_definitions_sha256'],'application_frontend_env_unchanged':P.sources()==before['sources'],'revision':test['_revision'],'actual_refunded_minor':sum(s['refunded_minor'] for s in summaries.values()),'refund_operations':2,'new_payments':0,'disputes_created':0,'B-P2_open':True,'cases':summaries}
    save('isolation-final.json',result);print(json.dumps(result))
    assert all(result[k] for k in ['development_unchanged','preexisting_rows_unchanged_except_target_attempt_status','schema_columns_unchanged','constraints_indexes_triggers_unchanged','application_frontend_env_unchanged'])

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='refund':mutate(sys.argv[2])
    elif sys.argv[1]=='finalize':finalize()
