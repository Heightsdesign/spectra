"""Production Next + FastAPI HTTP intake smoke test in a disposable test schema.

Run after building frontend with its default backend URL (127.0.0.1:8000).
The guarded _test database is never shared with concurrently running test suites.
"""
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta
from contextlib import ExitStack, nullcontext
from uuid import uuid4

frontend = Path(__file__).resolve().parents[1]
backend = frontend.parent / 'backend'
sys.path.insert(0, str(backend))
import httpx
import uvicorn
from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from app.auth import digest, now
from app.config import Settings, get_settings
from app.database import get_session
from app.main import app
from app.customer_models import Customer, CustomerSession
from app.submission_models import Submission, SubmissionEntry
from app.intake_models import StaffMembership


def main():
    raw = os.environ.get('TEST_DATABASE_URL') or dotenv_values(backend / '.env').get('TEST_DATABASE_URL')
    if not raw:
        raise RuntimeError('TEST_DATABASE_URL is required')
    url = make_url(raw)
    if url.drivername != 'postgresql+psycopg' or not url.database.endswith('_test') or url.database == make_url(get_settings().database_url).database:
        raise RuntimeError('Separate PostgreSQL _test database required')
    for port in (8000,13000):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',port))
    root_engine = create_engine(url)
    schema = 'w51_http_' + uuid4().hex
    with root_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = url.update_query_dict({'options':f'-csearch_path={schema}'})
    engine = create_engine(isolated)
    previous = os.environ.get('DATABASE_URL')
    process = server = thread = None
    temporary = ExitStack()
    try:
        os.environ['DATABASE_URL'] = isolated.render_as_string(hide_password=False)
        get_settings.cache_clear()
        command.upgrade(Config(str(backend / 'alembic.ini')), 'head')
        origin = 'http://127.0.0.1:13000'
        with nullcontext(temporary.enter_context(tempfile.TemporaryDirectory(prefix='test_tmp_intake_http_',dir=frontend))) as folder:
            settings = Settings(database_url=isolated.render_as_string(hide_password=False),auth_origin=origin,auth_mail_dir=Path(folder)/'mail')
            tokens=[]
            with Session(engine) as db:
                for staff in (True,False):
                    actor=Customer(email=uuid4().hex+'@example.invalid',password_hash='unused',first_name='Test',last_name='HTTP',email_verified=True)
                    db.add(actor)
                    db.flush()
                    if staff:
                        db.add(StaffMembership(customer_id=actor.id,role='admin'))
                        staff_id=actor.id
                    raw_session=secrets.token_urlsafe(32)
                    db.add(CustomerSession(customer_id=actor.id,token_hash=digest(raw_session),expires_at=now()+timedelta(hours=1)))
                    tokens.append(raw_session)
                item=Submission(customer_id=actor.id,reference='SP-'+uuid4().hex.upper(),status='submitted',confirmed_at=now())
                db.add(item)
                db.flush()
                sid=str(item.id)
                entry=SubmissionEntry(submission_id=item.id,game='pokemon',card_name='HTTP fixture',expansion='Synthetic',card_number='1',language='FR',quantity=1)
                db.add(entry)
                db.flush()
                eid=str(entry.id)
                db.commit()
            def sessions():
                with Session(engine) as db:
                    yield db
            app.dependency_overrides[get_session]=sessions
            app.dependency_overrides[get_settings]=lambda:settings
            server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8000,access_log=False,log_level='warning'))
            thread=threading.Thread(target=server.run,daemon=True)
            thread.start()
            with (Path(folder)/'next.log').open('w') as log:
                process=subprocess.Popen(['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','13000'],cwd=frontend,env={**os.environ,'SPECTRA_BACKEND_URL':'http://127.0.0.1:8000'},stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                with httpx.Client(base_url=origin,timeout=15,follow_redirects=False) as client:
                    for _ in range(100):
                        try:
                            if server.started and client.get('/login').status_code==200:
                                break
                        except httpx.TransportError:
                            pass
                        if process.poll() is not None:
                            raise RuntimeError('Next server did not start')
                        time.sleep(.1)
                    else:
                        raise RuntimeError('Servers did not become ready')
                    assert client.get('/admin').headers['location']=='/login'
                    assert client.get('/internal/intake/submissions').status_code==401
                    client.cookies.set('spectra_session',tokens[1])
                    assert client.get('/admin').headers['location']=='/account'
                    assert client.get('/internal/intake/submissions').status_code==403
                    client.cookies.set('spectra_session',tokens[0])
                    page=client.get('/admin')
                    assert page.status_code==200 and 'Réception physique' in page.text
                    with Session(engine) as db:
                        db.get(Customer,staff_id).preferred_language='EN'
                        db.commit()
                    assert 'Physical intake' in client.get('/admin').text
                    csrf=client.get('/api/auth/csrf').json()['csrf_token']
                    client.headers.update({'Origin':origin,'X-Spectra-Client':'1','X-CSRF-Token':csrf})
                    path='/internal/intake/submissions/'+sid
                    assert client.post(path+'/parcels',json={'request_key':str(uuid4())},headers={'X-CSRF-Token':''}).status_code==403
                    payload={'request_key':str(uuid4()),'notes':'HTTP received parcel'}
                    parcel=client.post(path+'/parcels',json=payload)
                    assert parcel.status_code==201
                    assert client.post(path+'/parcels',json=payload).json()==parcel.json()
                    for action in ['override','begin']:
                        assert client.post(path+'/transition',json={'action':action,'reason':'Synthetic HTTP test authorization'}).status_code==200
                    payload={'request_key':str(uuid4()),'parcel_id':parcel.json()['id']}
                    card=client.post(path+'/cards',json=payload)
                    assert card.status_code==201
                    assert client.post(path+'/cards',json=payload).json()==card.json()
                    assert client.post(path+'/cards/'+card.json()['id']+'/match',json={'entry_id':eid,'reason':'Verified synthetic identity'}).status_code==200
                    result=client.post(path+'/transition',json={'action':'complete','reason':'HTTP reconciliation reviewed'})
                    assert result.status_code==200 and result.json()['status']=='reconciled'
                    assert result.json()['received_quantity']==1
                    assert result.headers['cache-control']=='no-store'
                    assert any(e['action']=='physical_card_created' for e in result.json()['events'])
            print('Intake production HTTP integration: 1 passed (staff SSR FR/EN, customer rejection, proxy CSRF, parcel/card retries, matching, reconciliation, audit).')
    finally:
        if process:
            process.terminate()
            process.wait(timeout=10)
        if server:
            server.should_exit=True
        if thread:
            thread.join(timeout=10)
        temporary.close()
        app.dependency_overrides.clear()
        if previous is None:
            os.environ.pop('DATABASE_URL',None)
        else:
            os.environ['DATABASE_URL']=previous
        get_settings.cache_clear()
        engine.dispose()
        # Only this generated disposable schema in the guarded _test database is removed.
        with root_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root_engine.dispose()


if __name__=='__main__':
    main()
