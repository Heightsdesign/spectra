"""Actual Uvicorn process + PostgreSQL + HTTP, isolated from the operational DB."""
import os
import secrets
import socket
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import csrf_value, digest, now
from app.customer_models import CustomerSession
from app.intake_models import Intake, Parcel, PhysicalCard, StaffMembership
from app.submission_models import Submission, SubmissionEntry
from test_customer_operations import BASE, account, private
from test_intake_concurrency import isolated_intake_engine  # noqa: F401
from test_physical_labels import check_pdf, decode_page
from app.physical_identity import qr_payload


def test_real_http_directory_trace_and_staff_boundary(isolated_intake_engine):
    engine = isolated_intake_engine
    staff_token, customer_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with Session(engine) as db:
        actor = account(db, 'staff-http@example.invalid', first='Operator')
        customer = account(db, 'customer-http@example.invalid')
        customer_id = customer.id
        db.add(StaffMembership(customer_id=actor.id, role='admin'))
        for row, token in [(actor, staff_token), (customer, customer_token)]:
            db.add(CustomerSession(customer_id=row.id, token_hash=digest(token), expires_at=now()+timedelta(hours=1)))
        submission = Submission(customer_id=customer.id, reference='SP-'+uuid4().hex.upper(), status='submitted', confirmed_at=now())
        db.add(submission); db.flush()
        entry = SubmissionEntry(submission_id=submission.id, game='pokemon', card_name='HTTP test card',
                                expansion='Test', card_number='1', language='FR', quantity=1)
        parcel = Parcel(submission_id=submission.id, reference='PI-'+uuid4().hex.upper(), received_by=actor.id,
                        request_key=uuid4(), request_data={}, status='reconciled')
        db.add_all([entry, parcel]); db.flush()
        card = PhysicalCard(submission_id=submission.id, reference='PC-'+uuid4().hex.upper(), received_by=actor.id,
                            parcel_id=parcel.id, entry_id=entry.id, request_key=uuid4(), request_data={}, status='matched')
        reference = card.reference
        db.add_all([card, Intake(submission_id=submission.id, status='reconciled')]); db.commit()
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1',
                                '--port', str(port), '--no-access-log', '--log-level', 'warning'],
                               cwd=Path(__file__).resolve().parents[1],
                               env={**os.environ, 'DATABASE_URL': engine.url.render_as_string(hide_password=False),
                                    'AUTH_ORIGIN': 'http://127.0.0.1:3000'},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{port}', timeout=5) as client:
            ready = False
            for _ in range(100):
                try:
                    ready = client.get('/api/health').status_code == 200
                    if ready:
                        break
                except httpx.TransportError:
                    pass
                if process.poll() is not None:
                    break
                time.sleep(.1)
            assert ready, 'Isolated HTTP test server failed to start'
            private(client.get(BASE+'/customers'), 401)
            assert client.get('/internal/labels/cards/'+reference+'/pdf').status_code == 401
            client.cookies.set('spectra_session', customer_token)
            private(client.get(BASE+'/customers/not-a-uuid'), 403)
            assert client.get('/internal/labels/cards/'+reference+'/pdf').status_code == 403
            client.cookies.set('spectra_session', staff_token)
            directory = private(client.get(BASE+'/customers', params={'search':'customer-http'}))
            assert [row['id'] for row in directory['items']] == [str(customer_id)]
            detail = private(client.get(BASE+'/customers/'+str(customer_id)))
            assert detail['email'] == 'customer-http@example.invalid'
            history = private(client.get(BASE+'/customers/'+str(customer_id)+'/submissions'))
            assert history['items'][0]['declared_quantity'] == 1
            assert history['items'][0]['intake_status'] == 'reconciled'
            trace = private(client.get(BASE+'/cards/'+reference))
            assert trace['customer']['id'] == str(customer_id)
            assert trace['declared_entry']['card_name'] == 'HTTP test card'
            private(client.get(BASE+'/cards/PC-invalid'), 422)
            label=check_pdf(client.get('/internal/labels/cards/'+reference+'/pdf'))
            assert decode_page(label)==qr_payload(reference)
            assert check_pdf(client.get('/internal/labels/cards/'+reference+'/pdf'))==label
            print_headers={'Origin':'http://127.0.0.1:3000','X-Spectra-Client':'1','X-CSRF-Token':csrf_value(staff_token)}
            batch_path='/internal/labels/submissions/'+trace['submission']['id']+'/pdf'
            assert client.post(batch_path,json={'references':[reference]}).status_code==403
            assert check_pdf(client.post(batch_path,json={'references':[reference,reference]},headers=print_headers))==label
            assert client.get(BASE+'/cards/'+qr_payload(reference)+'%0D%0A').json()['card']['reference']==reference
            with engine.connect() as connection:
                assert connection.execute(text('SELECT status FROM submission_intakes')).scalar() == 'reconciled'
                assert connection.execute(text('SELECT count(*) FROM intake_audit_events')).scalar() == 0
    finally:
        process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=10)
