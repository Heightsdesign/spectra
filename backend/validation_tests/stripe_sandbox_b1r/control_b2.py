"""B2 preparation only: two TEST payments; refunds/disputes/expiry forbidden."""
import json
import hashlib
import os
import re
import secrets
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path
from collections import Counter
from uuid import UUID

import control as C
import control_phase2 as P
from sqlalchemy import select, text, event
from sqlalchemy.orm import Session
from app.config import get_settings
from app.database import get_engine
from app.customer_models import Customer, CustomerSession
from app.auth import now, digest
from app.stripe_checkout import StripeGateway, signature_event, SESSION_EVENTS, PI_EVENTS
from fastapi import HTTPException
from fastapi.responses import JSONResponse

OUT=C.ROOT/'validation_artifacts/stripe_sandbox_b2/preparation'
OUT.mkdir(parents=True,exist_ok=True)
C.OUT=P.OUT=OUT
save,read=C.save,C.read
CASES=['B-REFUND-PARTIAL','B-REFUND-FULL']

def guarded(self,method,path,data=None,key=None):
    # Reuse the one-Session-per-manifest-order guard; every other POST is denied.
    try:
        if method=='GET' and re.fullmatch(r'events\?type=payment_intent\.succeeded&limit=100(?:&starting_after=evt_[A-Za-z0-9]+)?',path):
            C.identity()
            result=C.ORIGINAL(self,method,path,data,key)
            assert all(e.get('livemode') is False and e.get('account') in (None,C.BASE.stripe_account_id) for e in result.get('data',[]))
            return result
        result=C.guarded(self,method,path,data,key)
        if method=='POST':P.audit('stripe-operations.jsonl',{'method':method,'path':path,'session_id':result['id']})
        return result
    except Exception:
        P.audit('stripe-operation-failures.jsonl',{'method':method,'path':path})
        raise

StripeGateway.call=guarded

def existing_rows():
    with get_engine().connect() as conn:
        conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        tables=conn.execute(text("select tablename from pg_tables where schemaname='public' order by tablename")).scalars().all()
        result={}
        for table in tables:
            quoted=conn.dialect.identifier_preparer.quote(table)
            rows=conn.execute(text(f'SELECT to_jsonb(t)::text FROM public.{quoted} t')).scalars().all()
            result[table]=dict(Counter(hashlib.sha256(row.encode()).hexdigest() for row in rows))
        schema={
            'constraints':[tuple(r) for r in conn.execute(text("select conrelid::regclass::text,conname,pg_get_constraintdef(oid) from pg_constraint where connamespace='public'::regnamespace order by 1,2"))],
            'indexes':[tuple(r) for r in conn.execute(text("select tablename,indexname,indexdef from pg_indexes where schemaname='public' order by 1,2"))],
            'triggers':[tuple(r) for r in conn.execute(text("select tgrelid::regclass::text,tgname,pg_get_triggerdef(oid) from pg_trigger where not tgisinternal and tgrelid in (select oid from pg_class where relnamespace='public'::regnamespace) order by 1,2"))]}
        return {'rows':result,'schema_definitions_sha256':hashlib.sha256(json.dumps(schema,default=str).encode()).hexdigest()}

def prepare():
    assert not (OUT/'manifest.json').exists(),'Do not duplicate QA preparation'
    identity=C.identity();development=C.fingerprint(C.VALUES['DATABASE_URL']);test=C.fingerprint(C.TARGET)
    assert development['_revision']==test['_revision']==['0015']
    save('before.json',{'identity':identity,'development':development,'test':test,'sources':P.sources(),'existing_test_rows':existing_rows()})
    (OUT/'private-next-env-before.txt').write_bytes((C.ROOT.parent/'frontend/next-env.d.ts').read_bytes())
    manifest={'phase':'B2-preparation','refunds_authorized':False,'max_successful_payments':2,'amount_per_payment_minor':2500,'currency':'eur','identity':identity,'cases':{}}
    save('manifest.json',manifest);save('session-ledger.json',{});save('private-access.json',{})
    for name in CASES:
        with Session(get_engine()) as db:
            customer=Customer(email=f'qa-b2-{name.lower()}-{secrets.token_hex(4)}@example.invalid',password_hash='unused-local-QA-session-only',first_name='QA',last_name=name,email_verified=True)
            db.add(customer);db.flush();token=secrets.token_urlsafe(32)
            db.add(CustomerSession(customer_id=customer.id,token_hash=digest(token),expires_at=now()+timedelta(hours=4)));db.commit()
            access=read('private-access.json');access[name]={'token':token,'customer_id':str(customer.id),'email':customer.email};save('private-access.json',access)
        with C.client_for(name) as client:
            item=C.request(client,'POST','/api/submissions',{});path='/api/submissions/'+item['id']
            case={'name':name,'submission_id':item['id'],'customer_id':access[name]['customer_id']}
            manifest['cases'][name]=case;save('manifest.json',manifest)
            for card in ['QA Pikachu','QA Eevee']:
                item=C.request(client,'POST',path+'/entries',{'version':item['version'],'game':'pokemon','card_name':card,'expansion':'QA TEST','card_number':'TEST','language':'FR','quantity':1,'notes':name,'processing_tier':'standard','upgrade_ids':['classic']})
            address=C.request(client,'POST','/api/addresses',{'recipient':'QA TEST','line1':'1 rue du Test','city':'Paris','postal_code':'75001','country':'FR'})
            summary=C.request(client,'PUT',path+'/delivery',{'version':0,'address_id':address['id'],'declared_value_minor':10000,'service_id':'fictitious-test-return-fr'})
            assert summary['final_payable_minor']==2500 and summary['readiness']['ready']
            item=C.request(client,'GET',path);item=C.request(client,'POST',path+'/confirm',{'version':item['version']})
            quote=C.request(client,'POST',path+'/quotes',{'version':item['version']})
            quote=C.request(client,'POST',path+'/quotes/'+quote['id']+'/accept',{'version':item['version'],'accept_terms':True})
            assert quote['snapshot']['order_total_minor']==2500 and quote['status']=='accepted'
            case.update(quote_id=quote['id'],snapshot_sha256=hashlib.sha256(json.dumps(quote['snapshot'],sort_keys=True).encode()).hexdigest())
            save('manifest.json',manifest)
    print(json.dumps({'prepared':True,'identity':identity,'cases':manifest['cases']}))

def serve():
    C.identity();env=os.environ.copy();env['STRIPE_API_KEY']=C.BASE.stripe_secret_key
    cli=subprocess.Popen(['C:/Users/plher/Documents/stripe_cli/stripe.exe','listen','--skip-update','--events',','.join(sorted((SESSION_EVENTS|PI_EVENTS)-{'checkout.session.expired','payment_intent.canceled'})),'--forward-to','http://127.0.0.1:18010/api/stripe/webhook'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    ready=threading.Event()
    def logs():
        for line in cli.stdout:
            secret=re.search(r'whsec_[A-Za-z0-9]+',line)
            if secret:os.environ['STRIPE_WEBHOOK_SECRET']=secret.group(0);get_settings.cache_clear();ready.set()
            with (OUT/'listener.log').open('a',encoding='utf-8') as f:f.write(re.sub(r'whsec_[A-Za-z0-9]+','[REDACTED]',line))
    threading.Thread(target=logs,daemon=True).start()
    try:
        assert ready.wait(25),'No listener; no payment'
        @C.app.middleware('http')
        async def scope(request,call_next):
            path=request.url.path
            if path.startswith('/qa/observe/'):
                if request.client.host!='127.0.0.1':return JSONResponse({},status_code=403)
                name,label=path.split('/')[3:5];assert name in CASES
                import asyncio
                result=await asyncio.to_thread(P.observe,name,label)
                return JSONResponse(P.summarize(result))
            if path=='/api/stripe/webhook':
                raw=await request.body()
                try:payload=signature_event(raw,request.headers.get('stripe-signature',''),get_settings().stripe_webhook_secret)
                except HTTPException:return JSONResponse({'detail':'invalid_stripe_signature'},status_code=400)
                sid=payload.get('data',{}).get('object',{}).get('metadata',{}).get('submission_id')
                if payload.get('livemode') is not False or sid not in {v['submission_id'] for v in read('manifest.json')['cases'].values()}:
                    return JSONResponse({'ignored':'outside_QA_manifest'},status_code=200)
                assert payload['type'] in SESSION_EVENTS|PI_EVENTS
                save('event-'+payload['id']+'.json',C.clean(payload))
                response=await call_next(request)
                P.audit('webhooks.jsonl',{'event_id':payload['id'],'type':payload['type'],'http':response.status_code,'body_sha256':hashlib.sha256(raw).hexdigest()})
                return response
            if path.startswith('/api/submissions/') and path.split('/')[3] not in {v['submission_id'] for v in read('manifest.json')['cases'].values()}:
                return JSONResponse({'outside_QA':True},status_code=403)
            response=await call_next(request)
            if path.endswith('/stripe-checkout'):
                raw=b''.join([b async for b in response.body_iterator]);data=json.loads(raw)
                P.audit('checkout-api.jsonl',{'path':path,'http':response.status_code,'body':C.clean(data),'url_present':bool(data.get('url'))})
                return JSONResponse(data,status_code=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'})
            if response.status_code>=400 and path.startswith('/api/'):
                P.audit('api-errors.jsonl',{'path':path,'method':request.method,'http':response.status_code})
            return response
        def sql_guard(conn,cursor,statement,parameters,context,executemany):
            assert statement.lstrip().split()[0].upper() in {'SELECT','INSERT','UPDATE','SET','SHOW','ROLLBACK','SAVEPOINT','RELEASE'},'DDL/purge forbidden'
        event.listen(get_engine(),'before_cursor_execute',sql_guard)
        import uvicorn
        print('QA_B2_PREPARATION_READY TEST spectra_test port=18010',flush=True)
        uvicorn.run(C.app,host='127.0.0.1',port=18010,log_level='warning')
    finally:cli.terminate();cli.wait(timeout=10)

def finalize():
    before=read('before.json');manifest=read('manifest.json');targets={}
    for name in CASES:
        result=P.observe(name,'final');db=result['database'];obj=result['objects'][0]
        assert len(db['attempts'])==1 and db['payment'] and len(db['deadlines'])==db['payment_audits']==1
        assert result['commercial']['payment_status']=='verified' and not result['commercial']['financial_restrictions']
        session,pi,charge=obj['session'],obj['payment_intent'],obj['charge']
        assert session['status']=='complete' and session['payment_status']=='paid' and pi['status']=='succeeded'
        assert pi['amount_received']==charge['amount']==charge['amount_captured']==db['payment']['amount_minor']==2500
        assert charge['paid'] and charge['captured'] and not charge['refunded'] and charge['amount_refunded']==0 and not charge['disputed']
        assert charge['payment_intent']==pi['id'] and pi['latest_charge']==charge['id']
        assert charge.get('metadata')==pi['metadata']==session['metadata']
        deadline=db['deadlines'][0]
        assert deadline['dispatch_deadline']-deadline['verified_payment_at']==timedelta(days=30)
        assert db['payment']['provider_payment_id']==pi['id']
        for evidence in db['evidence']:
            if evidence['event_id'].startswith('evt_'):
                canonical=StripeGateway(get_settings()).get('events',evidence['event_id']);assert canonical['livemode'] is False
                save('canonical-event-'+evidence['event_id']+'.json',C.clean(canonical))
        targets[name]={**manifest['cases'][name],'account_id':C.BASE.stripe_account_id,'test_only':True,'currency':'eur','paid_minor':2500,'refunded_minor':0,'refund_authorized':False,'session_id':session['id'],'attempt_id':db['attempts'][0]['id'],'payment_intent_id':pi['id'],'charge_id':charge['id'],'verified_at':str(db['payment']['verified_at']),'dispatch_deadline':str(deadline['dispatch_deadline'])}
    assert len({v['payment_intent_id'] for v in targets.values()})==len({v['charge_id'] for v in targets.values()})==2
    assert len(read('session-ledger.json'))==2
    current_rows=existing_rows()
    preserved=all(all(current_rows['rows'].get(table,{}).get(h,0)>=n for h,n in rows.items()) for table,rows in before['existing_test_rows']['rows'].items())
    development=C.fingerprint(C.VALUES['DATABASE_URL']);test=C.fingerprint(C.TARGET)
    report={'identity':C.identity(),'development_unchanged':development==before['development'],'all_preexisting_test_rows_unchanged':preserved,'test_columns_unchanged':test['_schema']==before['test']['_schema'],'constraints_indexes_triggers_unchanged':current_rows['schema_definitions_sha256']==before['existing_test_rows']['schema_definitions_sha256'],'application_frontend_and_env_unchanged':P.sources()==before['sources'],'revision':test['_revision'],'new_test_payments':2,'new_received_minor':5000,'refunds_executed':0,'disputes_created':0,'B-P2_open':True,'targets':targets}
    save('refund-targets.json',targets);save('isolation-final.json',report)
    assert all(report[k] for k in ['development_unchanged','all_preexisting_test_rows_unchanged','test_columns_unchanged','constraints_indexes_triggers_unchanged','application_frontend_and_env_unchanged'])
    print(json.dumps(report))

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='observe':print(json.dumps(P.summarize(P.observe(sys.argv[2],sys.argv[3]))))
    elif sys.argv[1]=='finalize':finalize()
