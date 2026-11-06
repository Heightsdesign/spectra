"""Independent PostgreSQL transactions, simulated provider, existing batch A guards."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, func
from sqlalchemy.orm import Session

from app.main import app
from app.stripe_models import StripeAttempt
from app.commercial_models import ShipmentDeclaration
from conftest import login
from test_batch_a import send, immutable_result


@pytest.mark.parametrize('first', ['webhook', 'declaration'])
def test_restriction_shipment_serialization(concurrent_scenario, first):
    s = concurrent_scenario
    with TestClient(app) as client:
        login(client, s.settings, s)
        assert client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 200
        with Session(s.engine) as db:
            attempt = db.scalar(select(StripeAttempt).where(StripeAttempt.quote_id == s.qid))
            session_id = attempt.session_id
        paid, _ = s.provider.settle(session_id)
        assert send(client, s.settings, paid).status_code == 200
    with Session(s.engine) as db:
        baseline = immutable_result(db, s.qid)
    session = s.provider.objects[('checkout/sessions', session_id)]
    pi = s.provider.objects[('payment_intents', session['payment_intent'])]
    restriction = {'id': 'evt_CORRECTION_' + uuid4().hex, 'livemode': False, 'type': 'refund.failed',
                   'data': {'object': {'id': 're_CORRECTION', 'charge': pi['latest_charge'], 'amount': 500, 'status': 'failed'}}}
    held, release, second_started = Event(), Event(), Event()

    payload = {'request_key': str(uuid4()), 'tracking': 'SYNTHETIC-CONCURRENCY'}

    def run(role):
        with TestClient(app) as client:
            login(client, s.settings, s)
            if role == 'webhook':
                return send(client, s.settings, restriction).status_code
            return client.post(f'/api/submissions/{s.sid}/shipment-declarations', json=payload).status_code

    # Pause the first request after it acquires the shared submission lock.
    def mark_connection(conn, cursor, statement, parameters, execution_context, executemany):
        if 'FOR UPDATE' in statement.upper() and 'FROM customer_submissions' in statement and not held.is_set():
            held.set()
            assert release.wait(10)

    def second_lock_attempt(conn, cursor, statement, parameters, execution_context, executemany):
        if held.is_set() and 'FOR UPDATE' in statement.upper() and 'FROM customer_submissions' in statement:
            second_started.set()

    event.listen(s.engine, 'after_cursor_execute', mark_connection)
    event.listen(s.engine, 'before_cursor_execute', second_lock_attempt)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(run, first)
            assert held.wait(10)
            two = pool.submit(run, 'declaration' if first == 'webhook' else 'webhook')
            assert second_started.wait(10)
            assert not two.done()
            release.set()
            codes = {first: one.result(timeout=15), ('declaration' if first == 'webhook' else 'webhook'): two.result(timeout=15)}
        assert codes['webhook'] == 200
        assert codes['declaration'] == (409 if first == 'webhook' else 201)
        with TestClient(app) as client:
            login(client, s.settings, s)
            path = f'/api/submissions/{s.sid}/shipment-declarations'
            assert client.post(path, json={'request_key': str(uuid4())}).status_code == 409
            if first == 'declaration':
                assert client.post(path, json=payload).status_code == 201
        with Session(s.engine) as db:
            assert immutable_result(db, s.qid) == baseline
            assert db.scalar(select(func.count()).select_from(ShipmentDeclaration).where(ShipmentDeclaration.submission_id == s.sid)) == (0 if first == 'webhook' else 1)
    finally:
        release.set()
        event.remove(s.engine, 'after_cursor_execute', mark_connection)
        event.remove(s.engine, 'before_cursor_execute', second_lock_attempt)
