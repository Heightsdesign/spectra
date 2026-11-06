"""Existing login + native client roundtrip over HTTP relay to real PostgreSQL APIs."""
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import logging
import threading
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from app.auth import now
from app.customer_models import Customer, CustomerSession
from app.intake_models import StaffMembership, PhysicalCard, Parcel, IntakeAudit
from app.submission_models import Submission, SubmissionEntry
from app.passwords import hash_password
from app.access_privacy import IntakeAccessPrivacy

PASSWORD='Synthetic-desktop-password!'


@pytest.fixture
def native_backend(api,monkeypatch):
    client,db,settings=api
    settings.auth_rate_limit=100
    operator=Customer(email='desktop-operator@example.invalid',password_hash=hash_password(PASSWORD),
        first_name='Synthetic',last_name='Operator',email_verified=True)
    customer=Customer(email='customer@example.invalid',password_hash='unused',first_name='Camille',last_name='Martin',email_verified=True)
    db.add_all([operator,customer]);db.flush();db.add(StaffMembership(customer_id=operator.id,role='operator'))
    items=[]
    for index in range(3):
        identifier=uuid4()
        item=Submission(id=identifier,reference='SP-'+identifier.hex.upper(),customer_id=customer.id,status='submitted',confirmed_at=now()+timedelta(seconds=index))
        db.add(item);db.flush()
        db.add(SubmissionEntry(submission_id=item.id,game='pokemon',card_name='Synthetic card',expansion='',card_number='',language='FR',quantity=2))
        items.append(item)
    db.commit()
    class Relay(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def forward(self):
            body=self.rfile.read(int(self.headers.get('Content-Length',0))) if self.command=='POST' else None
            headers={key:value for key,value in self.headers.items() if key.lower() in {'cookie','origin','x-spectra-client','x-csrf-token','content-type'}}
            client.cookies.clear()  # The relay must not add its own implicit cookie between native requests.
            response=client.request(self.command,self.path,headers=headers,content=body)
            client.cookies.clear()
            self.send_response(response.status_code)
            self.send_header('Content-Type',response.headers.get('content-type','application/json'))
            for cookie in response.headers.get_list('set-cookie'):
                self.send_header('Set-Cookie',cookie)
            self.send_header('Content-Length',str(len(response.content)));self.end_headers()
            self.wfile.write(response.content)
        do_GET=forward
        do_POST=forward
    server=ThreadingHTTPServer(('127.0.0.1',0),Relay)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]/'scanner_agent'))
    try:
        yield f'http://127.0.0.1:{server.server_port}',client,db,settings,operator,customer,items
    finally:
        server.shutdown();server.server_close();thread.join()


class MemoryVaultFixture:
    def __init__(self):self.value=None
    def save(self,value):self.value=value
    def load(self):return self.value
    def delete(self):self.value=None


def auth_service(fixture,vault=None):
    from selby_workstation.connection import DesktopConnection
    from selby_workstation.desktop_auth import DesktopAuthService
    origin,_,_,settings,_,_,_=fixture
    return DesktopAuthService(DesktopConnection('development',origin,settings.auth_origin),vault or MemoryVaultFixture())


def counts(db):
    return {model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in (Submission,SubmissionEntry,PhysicalCard,Parcel,IntakeAudit)}


def test_real_native_login_search_details_restore_logout_and_no_business_writes(native_backend):
    origin,_,db,_,_,customer,items=native_backend
    before=counts(db);snapshots={item.id:(item.reference,item.status,item.confirmed_at) for item in items}
    auth=auth_service(native_backend)
    client,actor=auth.sign_in('desktop-operator@example.invalid',PASSWORD)
    assert actor['role']=='operator' and actor['display_name']=='Synthetic Operator'
    results=client.submissions('camille martin')
    assert len(results)==3 and all(row['customer_name']=='Camille Martin' for row in results)
    assert results[0]['id']==str(items[-1].id)
    assert results[0]['declared_quantity']==2 and results[0]['received_quantity']==0
    assert client.submission(results[0]['id'])['entries'][0]['card_name']=='Synthetic card'
    restored,_=auth_service(native_backend,auth.store).restore()
    assert restored.submissions('SP-')==client.submissions('SP-')
    assert counts(db)==before
    assert {item.id:(item.reference,item.status,item.confirmed_at) for item in items}==snapshots
    assert PASSWORD not in auth.store.value
    assert auth.sign_out() and auth.store.value is None
    assert db.scalars(select(CustomerSession)).one().revoked_at is not None
    from selby_workstation.incoming import PreviewError
    with pytest.raises(PreviewError):client.submissions()
    assert counts(db)==before


def test_real_bad_credentials_role_change_and_expiration(native_backend):
    from selby_workstation.incoming import PreviewError
    _,_,db,_,operator,_,_=native_backend
    auth=auth_service(native_backend)
    with pytest.raises(PreviewError,match='Invalid email or password'):
        auth.sign_in('desktop-operator@example.invalid','incorrect')
    assert db.scalar(select(func.count()).select_from(CustomerSession))==0
    auth.sign_in('desktop-operator@example.invalid',PASSWORD)
    record=db.scalars(select(CustomerSession)).one();record.expires_at=now()-timedelta(seconds=1);db.commit()
    with pytest.raises(PreviewError):auth_service(native_backend,auth.store).restore()
    assert auth.store.value is None
    db.delete(db.get(StaffMembership,operator.id));db.commit()
    with pytest.raises(PreviewError,match='Operator or administrator'):
        auth.sign_in('desktop-operator@example.invalid',PASSWORD)
    latest=db.scalars(select(CustomerSession).where(CustomerSession.expires_at>now())).one()
    assert latest.revoked_at is not None and auth.store.value is None


def test_bounded_search_and_staff_isolation(native_backend):
    _,client,db,_,_,customer,_=native_backend
    auth=auth_service(native_backend);auth.sign_in('desktop-operator@example.invalid',PASSWORD)
    from selby_workstation.desktop_auth import SessionCredential
    record=SessionCredential.decode(auth.store.value,auth.connection)
    headers={'Cookie':f'{record.cookie_name}={record.token}'}
    first=client.get('/internal/intake/submissions?search=Martin&limit=2',headers=headers).json()
    second=client.get('/internal/intake/submissions?search=Martin&offset=2&limit=2',headers=headers).json()
    assert len(first)==2 and len(second)==1 and len({row['id'] for row in first+second})==3
    assert client.get('/internal/intake/submissions?limit=101',headers=headers).status_code==422
    assert client.get('/internal/intake/submissions?offset=-1',headers=headers).status_code==422
    assert client.get('/internal/intake/submissions?search=%25',headers=headers).json()==[]
    assert client.get('/internal/intake/submissions?search='+'x'*201,headers=headers).status_code==422
    customer.first_name='Cam%ille';db.commit()
    assert len(client.get('/internal/intake/submissions?search=%25',headers=headers).json())==3
    client.cookies.clear()
    assert client.get('/internal/intake/submissions').status_code==401


def test_search_access_logging_redacts_query():
    record=logging.LogRecord('uvicorn.access',logging.INFO,'test',1,'%s - "%s %s HTTP/%s" %d',
        ('127.0.0.1','GET','/internal/intake/submissions?search=PRIVATE-NAME','1.1',200),None)
    assert IntakeAccessPrivacy().filter(record)
    assert 'PRIVATE-NAME' not in record.getMessage() and '200' in record.getMessage()
