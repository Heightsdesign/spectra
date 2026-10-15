"""Independent connections and actors prove submission locking, not just session locking."""
import secrets
import os
import subprocess
import sys
from pathlib import Path
from datetime import timedelta
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app.auth import digest, csrf_value, now
from app.config import Settings, get_settings
from app.database import get_session
from app.main import app
from app.customer_models import Customer, CustomerSession
from app.submission_models import Submission, SubmissionEntry
from app.intake_models import StaffMembership, PhysicalCard, Parcel, IntakeAudit
from app.staff_bootstrap import bootstrap
from test_pricing_concurrency import race


@pytest.fixture
def isolated_intake_engine(test_engine, monkeypatch):
    schema = 'w51_test_' + uuid4().hex
    with test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    url = test_engine.url.update_query_dict({'options':f'-csearch_path={schema}'})
    engine = create_engine(url)
    try:
        with monkeypatch.context() as env:
            env.setenv('DATABASE_URL',url.render_as_string(hide_password=False))
            get_settings.cache_clear()
            command.upgrade(Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini')), 'head')
        get_settings.cache_clear()
        yield engine
    finally:
        engine.dispose()
        get_settings.cache_clear()
        # This uniquely generated schema belongs only to this test in the guarded _test DB.
        with test_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def customer(db):
    row = Customer(email=uuid4().hex+'@example.invalid',password_hash='unused',first_name='Fixture',last_name='Staff',email_verified=True)
    db.add(row)
    db.flush()
    return row


def test_concurrent_parcels_cards_and_quantity(isolated_intake_engine, tmp_path):
    engine = isolated_intake_engine
    settings = Settings(auth_mail_dir=tmp_path/'mail')
    tokens = []
    with Session(engine) as db:
        for _ in range(2):
            actor = customer(db)
            db.add(StaffMembership(customer_id=actor.id,role='admin'))
            raw = secrets.token_urlsafe(32)
            db.add(CustomerSession(customer_id=actor.id,token_hash=digest(raw),expires_at=now()+timedelta(hours=1)))
            tokens.append(raw)
        item = Submission(customer_id=actor.id,reference='SP-'+uuid4().hex.upper(),status='submitted',confirmed_at=now())
        db.add(item)
        db.flush()
        sid = str(item.id)
        entry = SubmissionEntry(submission_id=item.id,game='pokemon',card_name='Fixture',expansion='Test',card_number='1',language='FR',quantity=1)
        db.add(entry)
        db.flush()
        eid = str(entry.id)
        db.commit()
    def sessions():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_settings] = lambda: settings
    clients = [TestClient(app),TestClient(app)]
    try:
        for client,raw in zip(clients,tokens):
            client.cookies.set('spectra_session',raw)
            client.headers.update({'Origin':settings.auth_origin,'X-Spectra-Client':'1','X-CSRF-Token':csrf_value(raw)})
        path = '/internal/intake/submissions/'+sid
        payload = {'request_key':str(uuid4()),'notes':'same received parcel'}
        responses = race(*[lambda c=c:c.post(path+'/parcels',json=payload) for c in clients])
        assert [r.status_code for r in responses]==[201,201]
        assert responses[0].json()==responses[1].json()
        pid = responses[0].json()['id']
        # Two genuinely separate parcels remain separate under concurrent requests.
        responses = race(*[lambda c=c:c.post(path+'/parcels',json={'request_key':str(uuid4())}) for c in clients])
        assert all(r.status_code==201 for r in responses)
        assert responses[0].json()['id']!=responses[1].json()['id']
        for action in ['override','begin']:
            assert clients[0].post(path+'/transition',json={'action':action,'reason':'Concurrency fixture'}).status_code==200
        payload = {'request_key':str(uuid4()),'parcel_id':pid}
        responses = race(*[lambda c=c:c.post(path+'/cards',json=payload) for c in clients])
        assert all(r.status_code==201 for r in responses)
        assert responses[0].json()==responses[1].json()
        first = responses[0].json()['id']
        second = clients[0].post(path+'/cards',json={**payload,'request_key':str(uuid4())}).json()['id']
        responses = race(*[lambda c=c,cid=cid:c.post(path+'/cards/'+cid+'/match',json={'entry_id':eid,'reason':'Match unique declared slot'}) for c,cid in zip(clients,[first,second])])
        assert sorted(r.status_code for r in responses)==[200,409]
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Parcel))==3
            assert db.scalar(select(func.count()).select_from(PhysicalCard))==2
            assert db.scalar(select(func.count()).select_from(IntakeAudit).where(IntakeAudit.action=='physical_card_created'))==2
    finally:
        for client in clients:
            client.close()
        app.dependency_overrides.clear()


def test_concurrent_first_admin_bootstrap(isolated_intake_engine):
    engine = isolated_intake_engine
    with Session(engine) as db:
        emails = [customer(db).email for _ in range(2)]
        db.commit()
    def authorize(email):
        with Session(engine) as db:
            try:
                bootstrap(db,email,'Concurrent trusted host bootstrap')
                return 'authorized'
            except ValueError:
                return 'closed'
    assert sorted(race(*[lambda email=email:authorize(email) for email in emails]))==['authorized','closed']
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(StaffMembership))==1
        assert db.scalar(select(func.count()).select_from(IntakeAudit))==1


def run_bootstrap_cli(engine, email, reason='Initial administrator authorization approved by company operator'):
    # Execute the real entry point without inheriting pytest's preloaded ORM registry.
    environment = {**os.environ, 'DATABASE_URL': engine.url.render_as_string(hide_password=False)}
    return subprocess.run(
        [sys.executable, '-m', 'app.staff_bootstrap', '--email', email, '--reason', reason],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, timeout=30,
    )


def test_bootstrap_cli_fresh_process(isolated_intake_engine):
    engine = isolated_intake_engine
    with Session(engine) as db:
        actor = customer(db)
        actor_id, email = actor.id, actor.email
        other = customer(db)
        other_id = other.id
        for row in (actor, other):
            db.add(CustomerSession(customer_id=row.id, token_hash=digest(uuid4().hex),
                                   expires_at=now()+timedelta(hours=1)))
        db.commit()
    result = run_bootstrap_cli(engine, ' ' + email.upper() + ' ')
    assert result.returncode == 0, result.stderr
    assert 'Administrator authorized' in result.stdout
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(StaffMembership)) == 1
        assert db.get(StaffMembership, actor_id).role == 'admin'
        event = db.scalars(select(IntakeAudit)).one()
        assert event.actor_id == event.entity_id == actor_id
        assert event.submission_id is None
        assert event.action == 'administrator_bootstrapped'
        assert event.data == {'before': None, 'after': 'admin', 'source': 'trusted_host_cli'}
        assert event.reason == 'Initial administrator authorization approved by company operator'
        assert db.scalar(select(CustomerSession).where(CustomerSession.customer_id == actor_id)).revoked_at
        assert db.scalar(select(CustomerSession).where(CustomerSession.customer_id == other_id)).revoked_at is None
    result = run_bootstrap_cli(engine, email)
    assert result.returncode == 1
    assert 'a staff membership already exists' in result.stderr
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(IntakeAudit)) == 1


@pytest.mark.parametrize('case', ['missing', 'unverified', 'disabled', 'operator', 'blank_reason', 'long_reason'])
def test_bootstrap_cli_rejects_unauthorized(isolated_intake_engine, case):
    engine = isolated_intake_engine
    with Session(engine) as db:
        actor = customer(db)
        email = actor.email
        if case == 'unverified':
            actor.email_verified = False
        if case == 'disabled':
            actor.status = 'disabled'
        if case == 'operator':
            existing = customer(db)
            db.add(StaffMembership(customer_id=existing.id, role='operator'))
        db.add(CustomerSession(customer_id=actor.id, token_hash=digest(uuid4().hex),
                               expires_at=now()+timedelta(hours=1)))
        db.commit()
    reason = {'blank_reason': ' ', 'long_reason': 'x'*1001}.get(case, 'Initial authorization')
    result = run_bootstrap_cli(engine, 'missing@example.invalid' if case == 'missing' else email, reason)
    assert result.returncode == 1, result.stderr
    expected = ('a staff membership already exists' if case == 'operator' else
                'A bounded operational reason is required' if case.endswith('reason') else
                'An existing active verified account is required')
    assert expected in result.stderr
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(StaffMembership)) == (1 if case == 'operator' else 0)
        assert db.scalar(select(func.count()).select_from(IntakeAudit)) == 0
        assert db.scalars(select(CustomerSession)).one().revoked_at is None


def test_bootstrap_cli_audit_failure_rolls_back_grant_and_revocation(isolated_intake_engine):
    engine = isolated_intake_engine
    with Session(engine) as db:
        actor = customer(db)
        email = actor.email
        db.add(CustomerSession(customer_id=actor.id, token_hash=digest(uuid4().hex),
                               expires_at=now()+timedelta(hours=1)))
        db.commit()
    # Fail only the audit insert in this disposable schema to exercise the real transaction.
    with engine.begin() as connection:
        connection.execute(text("""CREATE FUNCTION reject_bootstrap_audit() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test audit insert failure'; END $$"""))
        connection.execute(text('CREATE TRIGGER reject_bootstrap_audit BEFORE INSERT ON intake_audit_events '
                                'FOR EACH ROW EXECUTE FUNCTION reject_bootstrap_audit()'))
    result = run_bootstrap_cli(engine, email)
    assert result.returncode != 0
    assert 'test audit insert failure' in result.stderr
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(StaffMembership)) == 0
        assert db.scalar(select(func.count()).select_from(IntakeAudit)) == 0
        assert db.scalars(select(CustomerSession)).one().revoked_at is None
