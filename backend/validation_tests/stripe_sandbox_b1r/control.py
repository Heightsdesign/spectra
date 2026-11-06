"""User-authorized B1-R only. No migrations, no cancellation/refund/expiry calls.

Process-local QA transport restrictions; application source and policies unchanged.
Secrets are read from local configuration and never printed.
"""
import hashlib
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import threading
import time
from datetime import timedelta, datetime, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'validation_artifacts/stripe_sandbox_b1r/phase1'
OUT.mkdir(parents=True, exist_ok=True)
from dotenv import dotenv_values
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.config import Settings, get_settings

BASE = Settings()
VALUES = dotenv_values(ROOT / '.env')
TARGET = VALUES['TEST_DATABASE_URL']
url = make_url(TARGET)
assert url.database == 'spectra_test' and url.host in {'localhost', '127.0.0.1'}
assert BASE.stripe_mode == 'test' and BASE.stripe_secret_key.startswith('sk_test_')
assert BASE.stripe_account_id == 'acct_1UXDxRFq5FKSG47y' and BASE.auth_environment == 'development'
os.environ.update(DATABASE_URL=TARGET, AUTH_ORIGIN='http://127.0.0.1:13010',
                  AUTH_ENVIRONMENT='development', STRIPE_MODE='test', STRIPE_ENABLED='true',
                  STRIPE_FICTITIOUS_ENABLED='true', AUTH_MAIL_DIR=str(OUT / 'private-mail'))
get_settings.cache_clear()
from app.main import app
from app.database import get_engine
from app.stripe_checkout import StripeGateway
from app.commercial_models import VerifiedPayment, DispatchExpectation
from app.stripe_models import StripeAttempt
from app.pricing_models import PricingState, PricingCatalog
from app.checkout_models import ShippingState, ShippingConfiguration
from app.customer_models import Customer, CustomerSession
from app.auth import digest, csrf_value, now
from fastapi import HTTPException
from fastapi.testclient import TestClient
logging.getLogger('httpx').setLevel(logging.WARNING)

def save(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))

def clean(value):
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k not in {'client_secret', 'url', 'receipt_url', 'hosted_invoice_url'}}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value

def fingerprint(target):
    engine = create_engine(target)
    with engine.connect() as conn:
        conn.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        tables = conn.execute(text("select tablename from pg_tables where schemaname='public' order by tablename")).scalars().all()
        data = {}
        for table in tables:
            quoted = conn.dialect.identifier_preparer.quote(table)
            rows = conn.execute(text(f'SELECT to_jsonb(t)::text FROM public.{quoted} t ORDER BY to_jsonb(t)::text')).scalars().all()
            data[table] = {'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
        schema = conn.execute(text("select table_name,column_name,data_type,is_nullable,column_default from information_schema.columns where table_schema='public' order by table_name,ordinal_position")).all()
        data['_schema'] = hashlib.sha256(str(schema).encode()).hexdigest()
        data['_revision'] = conn.execute(text('select version_num from alembic_version')).scalars().all()
    engine.dispose()
    return data

def identity():
    settings = get_settings()
    assert settings.stripe_mode == 'test' and settings.stripe_secret_key.startswith('sk_test_')
    account = ORIGINAL(StripeGateway(settings), 'GET', 'account')
    assert account['id'] == BASE.stripe_account_id
    return {'account_id':account['id'], 'business_name':account.get('business_profile',{}).get('name'),
            'test_key':True, 'database':'spectra_test', 'api_version':settings.stripe_api_version}

ORIGINAL = StripeGateway.call
write_lock = threading.Lock()

def guarded(self, method, path, data=None, key=None):
    check = identity()
    manifest = read('manifest.json')
    cases = manifest['cases']
    if method == 'POST':
        if path != 'checkout/sessions':
            raise HTTPException(409, 'qa_forbidden_stripe_mutation')
        sid = data.get('metadata[submission_id]')
        case = next((v for v in cases.values() if v['submission_id'] == sid), None)
        if not case or data.get('metadata[quote_id]') != case['quote_id'] or data.get('line_items[0][price_data][unit_amount]') != '2500':
            raise HTTPException(409, 'qa_manifest_mismatch')
        with write_lock:
            ledger = read('session-ledger.json')
            if sid in ledger:
                raise HTTPException(409, 'qa_additional_session_forbidden')
            # Reserve before network: an ambiguous call is never retried automatically.
            ledger[sid] = {'key':key,'status':'reserved'}
            save('session-ledger.json', ledger)
        result = ORIGINAL(self, method, path, data, key)
        assert result['id'].startswith('cs_test_') and result['livemode'] is False
        assert result['amount_total'] == 2500 and result['currency'] == 'eur'
        ledger[sid].update(status='created', session_id=result['id'])
        save('session-ledger.json', ledger)
        save('session-created-' + case['name'] + '.json', clean(result))
    else:
        if method != 'GET' or not re.fullmatch(r'(account|checkout/sessions/cs_test_[A-Za-z0-9]+|payment_intents/pi_[A-Za-z0-9]+|charges/ch_[A-Za-z0-9]+|events/evt_[A-Za-z0-9]+)',path):
            raise HTTPException(409, 'qa_forbidden_stripe_read')
        result = ORIGINAL(self, method, path, data, key)
        if 'livemode' in result and result['livemode'] is not False:
            raise HTTPException(409, 'qa_live_object_forbidden')
    return result

StripeGateway.call = guarded

def client_for(case):
    client = TestClient(app)
    token = read('private-access.json')[case]['token']
    client.cookies.set('spectra_session', token)
    client.headers.update({'Origin':get_settings().auth_origin,'X-Spectra-Client':'1','X-CSRF-Token':csrf_value(token)})
    return client

def request(client, method, path, body=None):
    response = client.request(method, path, json=body)
    with (OUT / 'api.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'method':method,'path':path,'status':response.status_code,'body':clean(response.json())}, default=str, ensure_ascii=False)+'\n')
    assert response.status_code < 400, (response.status_code, response.text)
    return response.json()

def prepare():
    assert not (OUT / 'manifest.json').exists(), 'Do not recreate dedicated fixtures'
    account = identity()
    dev = fingerprint(VALUES['DATABASE_URL'])
    test = fingerprint(TARGET)
    assert dev['_revision'] == test['_revision'] == ['0015']
    save('before.json', {'identity':account,'development':dev,'test':test})
    from app.pricing_catalog import publish
    from app.shipping_catalog import publish as shipping_publish
    with Session(get_engine()) as db:
        pricing = db.get(PricingState, 1)
        shipping = db.get(ShippingState, 1)
        # Publish the authorized fictitious configuration only if absent.
        if not pricing.current_version:
            publish(db,json.loads((ROOT/'pricing/fictitious-stripe-test-pricing.json').read_text(encoding='utf-8')),get_settings())
        if not shipping.current_version:
            shipping_publish(db,json.loads((ROOT/'pricing/fictitious-stripe-test-shipping.json').read_text(encoding='utf-8')),get_settings())
        db.commit()
        p = db.get(PricingCatalog, pricing.current_version)
        sh = db.get(ShippingConfiguration, shipping.current_version)
        assert p.document.get('stripe_test_only') and sh.document.get('stripe_test_only'), 'Existing catalogs need review; do not replace'
    manifest = {'run':'B1-R-phase1-20261106', 'identity':account, 'max_successes':2,'amount_minor':2500,'currency':'eur','cases':{}}
    access = {}
    save('manifest.json',manifest)
    save('session-ledger.json',{})
    for name in ['B-DECLINE','B-3DS','B-ABANDON']:
        with Session(get_engine()) as db:
            customer=Customer(email=f'qa-b1r-{name.lower()}-{secrets.token_hex(4)}@example.invalid',password_hash='unused-local-QA-session-only',first_name='QA',last_name=name,email_verified=True)
            db.add(customer);db.flush()
            token=secrets.token_urlsafe(32)
            db.add(CustomerSession(customer_id=customer.id,token_hash=digest(token),expires_at=now()+timedelta(hours=4)))
            db.commit()
            access[name]={'token':token,'customer_id':str(customer.id),'email':customer.email}
        save('private-access.json',access)
        with client_for(name) as client:
            item=request(client,'POST','/api/submissions',{})
            path='/api/submissions/'+item['id']
            # Record each fixture immediately so preparation can be audited after interruption.
            manifest['cases'][name]={'name':name,'customer_id':access[name]['customer_id'],'submission_id':item['id']}
            save('manifest.json',manifest)
            for card in ['QA Pikachu','QA Eevee']:
                item=request(client,'POST',path+'/entries',{'version':item['version'],'game':'pokemon','card_name':card,'expansion':'QA TEST','card_number':'TEST','language':'FR','quantity':1,'notes':name,'processing_tier':'standard','upgrade_ids':['classic']})
            address=request(client,'POST','/api/addresses',{'recipient':'QA TEST','line1':'1 rue du Test','city':'Paris','postal_code':'75001','country':'FR'})
            summary=request(client,'PUT',path+'/delivery',{'version':0,'address_id':address['id'],'declared_value_minor':10000,'service_id':'fictitious-test-return-fr'})
            assert summary['final_payable_minor']==2500 and summary['readiness']['ready']
            item=request(client,'GET',path)
            item=request(client,'POST',path+'/confirm',{'version':item['version']})
            quote=request(client,'POST',path+'/quotes',{'version':item['version']})
            quote=request(client,'POST',path+'/quotes/'+quote['id']+'/accept',{'version':item['version'],'accept_terms':True})
            assert quote['snapshot']['order_total_minor']==2500 and quote['status']=='accepted'
            manifest['cases'][name].update(quote_id=quote['id'],snapshot_sha256=hashlib.sha256(json.dumps(quote['snapshot'],sort_keys=True).encode()).hexdigest())
            save('manifest.json',manifest)
    print(json.dumps({'prepared':True,'identity':account,'cases':manifest['cases']}))

def observe(name, label):
    check=identity();case=read('manifest.json')['cases'][name]
    with client_for(name) as client:
        commercial=request(client,'GET','/api/submissions/'+case['submission_id']+'/commercial-state')
    with Session(get_engine()) as db:
        attempts=db.scalars(select(StripeAttempt).where(StripeAttempt.quote_id==UUID(case['quote_id']))).all()
        assert len(attempts)<=1, 'STOP multiple attempts'
        result={'at':datetime.now(timezone.utc).isoformat(),'identity':check,'case':name,'label':label,'commercial':commercial,'objects':[]}
        for attempt in attempts:
            if not attempt.session_id:continue
            session=StripeGateway(get_settings()).get('checkout/sessions',attempt.session_id)
            assert session['livemode'] is False and session['amount_total']==2500 and session['metadata']['quote_id']==case['quote_id']
            pi=StripeGateway(get_settings()).get('payment_intents',session['payment_intent']) if session.get('payment_intent') else None
            if pi:
                assert pi['livemode'] is False and pi['amount']==2500 and pi['metadata']['quote_id']==case['quote_id']
            charge=StripeGateway(get_settings()).get('charges',pi['latest_charge']) if pi and pi.get('latest_charge') else None
            if charge:
                assert charge['livemode'] is False and charge['payment_intent']==pi['id'] and charge['amount']==2500
            result['objects'].append({'attempt_id':str(attempt.id),'attempt_status':attempt.status,'session':clean(session),'payment_intent':clean(pi),'charge':clean(charge)})
            if session['status']=='complete' and session['payment_status']=='unpaid' and pi and pi['status']=='requires_action':
                result['B-P2_reproduced']=True
        result['database_payment']=clean({c.name:getattr(db.get(VerifiedPayment,UUID(case['quote_id'])),c.name) for c in VerifiedPayment.__table__.columns}) if db.get(VerifiedPayment,UUID(case['quote_id'])) else None
        result['deadlines']=[{c.name:getattr(d,c.name) for c in DispatchExpectation.__table__.columns} for d in db.scalars(select(DispatchExpectation).where(DispatchExpectation.quote_id==UUID(case['quote_id'])))]
    save(name+'-'+label+'.json',result)
    print(json.dumps({'case':name,'label':label,'payment_status':commercial['payment_status'],'objects':[{'session':o['session']['id'],'session_status':o['session']['status'],'payment_status':o['session']['payment_status'],'pi':o['payment_intent']['id'] if o['payment_intent'] else None,'pi_status':o['payment_intent']['status'] if o['payment_intent'] else None} for o in result['objects']],'B-P2_reproduced':result.get('B-P2_reproduced',False)}))

def serve():
    identity()
    env=os.environ.copy();env['STRIPE_API_KEY']=BASE.stripe_secret_key
    cli=subprocess.Popen(['C:/Users/plher/Documents/stripe_cli/stripe.exe','listen','--skip-update','--events','checkout.session.completed,payment_intent.succeeded,payment_intent.processing,payment_intent.requires_action,payment_intent.payment_failed','--forward-to','http://127.0.0.1:18010/api/stripe/webhook'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
    ready=threading.Event()
    def output():
        for line in cli.stdout:
            secret=re.search(r'whsec_[A-Za-z0-9]+',line)
            if secret:
                os.environ['STRIPE_WEBHOOK_SECRET']=secret.group(0);get_settings.cache_clear();ready.set()
            with (OUT/'listener.log').open('a',encoding='utf-8') as f:f.write(re.sub(r'whsec_[A-Za-z0-9]+','[REDACTED]',line))
    threading.Thread(target=output,daemon=True).start()
    try:
        assert ready.wait(25), 'Listener not ready; no checkout creation'
        from fastapi.responses import JSONResponse
        @app.middleware('http')
        async def qa_scope(request, call_next):
            if request.url.path=='/api/stripe/webhook':
                raw=await request.body()
                obj=json.loads(raw).get('data',{}).get('object',{})
                cases=read('manifest.json')['cases']
                if obj.get('livemode') is not False or obj.get('metadata',{}).get('submission_id') not in {v['submission_id'] for v in cases.values()}:
                    return JSONResponse({'ignored':'outside_QA_manifest'},status_code=200)
                # Preserve the real signed event body; never generate provider events.
                payload=json.loads(raw)
                save('event-'+payload['id']+'.json',clean(payload))
                response=await call_next(request)
                with (OUT/'webhooks.jsonl').open('a') as f:f.write(json.dumps({'event_id':payload['id'],'type':payload['type'],'http':response.status_code})+'\n')
                return response
            if request.url.path.startswith('/api/submissions/'):
                sid=request.url.path.split('/')[3]
                if sid not in {v['submission_id'] for v in read('manifest.json')['cases'].values()}:
                    return JSONResponse({'detail':'outside_QA_manifest'},status_code=403)
            return await call_next(request)
        def sql_guard(conn,cursor,statement,parameters,context,executemany):
            assert statement.lstrip().split()[0].upper() in {'SELECT','INSERT','UPDATE','SET','SHOW','ROLLBACK','SAVEPOINT','RELEASE'}, 'Forbidden DDL/purge'
        event.listen(get_engine(),'before_cursor_execute',sql_guard)
        import uvicorn
        print('QA_READY spectra_test TEST port=18010',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=18010,log_level='warning')
    finally:
        cli.terminate();cli.wait(timeout=10)

if __name__=='__main__':
    if sys.argv[1]=='prepare':prepare()
    elif sys.argv[1]=='serve':serve()
    elif sys.argv[1]=='observe':observe(sys.argv[2],sys.argv[3])
    elif sys.argv[1]=='finalize':
        before=read('before.json');after=fingerprint(VALUES['DATABASE_URL']);test=fingerprint(TARGET)
        from app.pricing_models import SubmissionQuote
        from app.commercial_models import CommercialEvent
        from sqlalchemy import func
        result={'development_unchanged':before['development']==after,'test_schema_unchanged':before['test']['_schema']==test['_schema'],'revision':test['_revision'],'identity':identity(),'cases':{}}
        total=0
        with Session(get_engine()) as db:
            for name,case in read('manifest.json')['cases'].items():
                qid=UUID(case['quote_id'])
                snapshot=db.get(SubmissionQuote,qid).snapshot
                attempts=db.scalars(select(StripeAttempt).where(StripeAttempt.quote_id==qid)).all()
                payments=db.scalars(select(VerifiedPayment).where(VerifiedPayment.quote_id==qid)).all()
                deadlines=db.scalars(select(DispatchExpectation).where(DispatchExpectation.quote_id==qid)).all()
                audits=db.scalar(select(func.count()).select_from(CommercialEvent).where(CommercialEvent.submission_id==UUID(case['submission_id']),CommercialEvent.kind=='provider_payment_verified'))
                snapshot_unchanged=hashlib.sha256(json.dumps(snapshot,sort_keys=True).encode()).hexdigest()==case['snapshot_sha256']
                expected=0 if name=='B-ABANDON' else 1
                assert len(attempts)==1 and len(payments)==len(deadlines)==audits==expected and snapshot_unchanged
                if expected:
                    assert payments[0].amount_minor==2500 and deadlines[0].dispatch_deadline-deadlines[0].verified_payment_at==timedelta(days=30)
                total+=sum(p.amount_minor for p in payments)
                result['cases'][name]={'attempts':len(attempts),'verified_payments':len(payments),'deadlines':len(deadlines),'payment_audits':audits,'snapshot_unchanged':snapshot_unchanged}
        assert total==5000 and len(read('session-ledger.json'))==3
        result.update(successful_test_payments=2,total_received_minor=total,checkout_sessions=3)
        save('isolation-final.json',result);print(json.dumps(result));assert result['development_unchanged'] and result['test_schema_unchanged']
