"""Batch A: real PostgreSQL transactions + real HTTP/signature code + fake Stripe."""
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.commercial_models import CommercialEvent, DispatchExpectation, VerifiedPayment
from app.config import Settings
from app.main import app
from app.pricing_models import SubmissionQuote
from app.stripe_checkout import payment_state
from app.stripe_models import StripeAttempt, StripeEvidence
from conftest import canonical_hash, login, seed


def start(s):
    response = s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)})
    assert response.status_code == 200, response.json()
    attempt = s.db.scalar(select(StripeAttempt).where(StripeAttempt.quote_id == s.qid))
    return attempt


def send(client, settings, payload, signature_case=None):
    raw = json.dumps(payload, separators=(',', ':')).encode()
    stamp = str(int(time.time()) - (301 if signature_case == 'expired' else 0))
    secret = settings.stripe_webhook_secret if signature_case != 'wrong_secret' else 'whsec_OTHER_SYNTHETIC'
    signature = hmac.new(secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    header = f't={stamp},v1={signature}'
    if signature_case == 'missing':
        header = ''
    elif signature_case == 'malformed':
        header = 'bad'
    elif signature_case == 'digest':
        header = f't={stamp},v1=' + '0' * 64
    elif signature_case == 'tampered_body':
        raw += b' '
    elif signature_case == 'duplicate_timestamp':
        header += f',t={stamp}'
    return client.post('/api/stripe/webhook', content=raw, headers={'stripe-signature': header})


def counts(db, qid):
    db.expire_all()
    return tuple(db.scalar(select(func.count()).select_from(model).where(model.quote_id == qid))
                 for model in (VerifiedPayment, DispatchExpectation, StripeEvidence))


def immutable_result(db, qid):
    db.expire_all()
    payment = db.get(VerifiedPayment, qid)
    deadline = db.scalar(select(DispatchExpectation).where(DispatchExpectation.quote_id == qid))
    quote = db.get(SubmissionQuote, qid)
    return (
        payment.provider_event_id, payment.provider_payment_id, payment.verified_at, payment.recorded_at,
        deadline.verified_payment_at, deadline.dispatch_deadline, canonical_hash(quote.snapshot),
    )


@pytest.mark.parametrize('first', ['payment_intent.succeeded', 'checkout.session.completed'])
def test_replays_both_orders_preserve_single_confirmation_and_dates(scenario, first):
    s = scenario
    attempt = start(s)
    before = canonical_hash(s.db.get(SubmissionQuote, s.qid).snapshot)
    pi_event, session_event = s.provider.settle(attempt.session_id)
    sequence = [pi_event, session_event] if first == pi_event['type'] else [session_event, pi_event]
    assert send(s.client, s.settings, sequence[0]).status_code == 200
    baseline = immutable_result(s.db, s.qid)
    assert baseline[-1] == before
    assert baseline[0] == pi_event['id']
    assert baseline[5] - baseline[4] == timedelta(days=30)
    assert baseline[4] == baseline[2]
    # 13 deliveries of two distinct events, including both orders and repeated payloads.
    for payload in [sequence[1]] + sequence * 4 + list(reversed(sequence)) + [sequence[0]]:
        assert send(s.client, s.settings, payload).status_code == 200
        assert immutable_result(s.db, s.qid) == baseline
        assert counts(s.db, s.qid)[:2] == (1, 1)
    assert counts(s.db, s.qid) == (1, 1, 2)
    assert payment_state(s.db, s.qid) == 'verified'
    assert s.db.scalar(select(func.count()).select_from(CommercialEvent).where(
        CommercialEvent.submission_id == s.sid, CommercialEvent.kind == 'provider_payment_verified')) == 1


def test_new_notifications_for_same_payment_do_not_recredit_or_reset_dates(scenario):
    s = scenario
    attempt = start(s)
    first, second = s.provider.settle(attempt.session_id)
    assert send(s.client, s.settings, first).status_code == 200
    baseline = immutable_result(s.db, s.qid)
    for original in (first, second):
        payload = deepcopy(original)
        payload['id'] = 'evt_BATCHA_' + uuid4().hex
        payload['created'] += 1
        assert send(s.client, s.settings, payload).status_code == 200
        assert immutable_result(s.db, s.qid) == baseline
    assert counts(s.db, s.qid) == (1, 1, 3)


def test_same_event_identity_with_modified_body_is_rejected(scenario):
    s = scenario
    attempt = start(s)
    payload, _ = s.provider.settle(attempt.session_id)
    assert send(s.client, s.settings, payload).status_code == 200
    baseline = immutable_result(s.db, s.qid)
    altered = deepcopy(payload)
    altered['created'] += 1
    response = send(s.client, s.settings, altered)
    assert response.status_code == 400
    assert response.json()['detail'] == 'stripe_event_verification_failed'
    assert immutable_result(s.db, s.qid) == baseline
    assert counts(s.db, s.qid) == (1, 1, 1)


@pytest.mark.parametrize('case', ['missing', 'malformed', 'digest', 'wrong_secret', 'tampered_body', 'expired', 'duplicate_timestamp'])
def test_invalid_signatures_rejected_before_provider_lookup(scenario, case):
    s = scenario
    attempt = start(s)
    payload, _ = s.provider.settle(attempt.session_id)
    calls_before = len(s.provider.calls)
    response = send(s.client, s.settings, payload, case)
    assert response.status_code == 400
    assert response.json()['detail'] == 'invalid_stripe_signature'
    assert len(s.provider.calls) == calls_before
    assert counts(s.db, s.qid) == (0, 0, 0)


@pytest.mark.parametrize('resource,field,value', [
    ('session', 'amount_total', 2499), ('session', 'amount_total', 2501),
    ('session', 'currency', 'usd'), ('session', 'livemode', True),
    ('session', 'mode', 'subscription'), ('session', 'client_reference_id', 'WRONG'),
    ('pi', 'amount', 2499), ('pi', 'amount', 2501), ('pi', 'currency', 'usd'),
    ('pi', 'livemode', True), ('charge', 'amount', 2499), ('charge', 'currency', 'usd'),
    ('charge', 'livemode', True), ('charge', 'payment_intent', 'pi_WRONG'),
])
def test_canonical_provider_mismatches_rejected(scenario, resource, field, value):
    s = scenario
    attempt = start(s)
    payload, _ = s.provider.settle(attempt.session_id)
    session = s.provider.objects[('checkout/sessions', attempt.session_id)]
    pi = s.provider.objects[('payment_intents', session['payment_intent'])]
    charge = s.provider.objects[('charges', pi['latest_charge'])]
    {'session': session, 'pi': pi, 'charge': charge}[resource][field] = value
    response = send(s.client, s.settings, payload)
    assert response.status_code == 400
    assert response.json()['detail'] == 'stripe_event_verification_failed'
    assert counts(s.db, s.qid) == (0, 0, 0)


@pytest.mark.parametrize('resource,field', [('session', 'quote_id'), ('pi', 'quote_id'), ('pi', 'obligation_id'), ('session', 'submission_id'), ('pi', 'customer_id')])
def test_wrong_quote_or_linkage_metadata_rejected(scenario, resource, field):
    s = scenario
    attempt = start(s)
    payload, _ = s.provider.settle(attempt.session_id)
    session = s.provider.objects[('checkout/sessions', attempt.session_id)]
    obj = session if resource == 'session' else s.provider.objects[('payment_intents', session['payment_intent'])]
    obj['metadata'][field] = str(uuid4())
    assert send(s.client, s.settings, payload).status_code == 400
    assert counts(s.db, s.qid) == (0, 0, 0)


@pytest.mark.parametrize('case', ['envelope_account', 'api_account', 'envelope_live', 'unknown_attempt', 'missing_attempt', 'cross_session'])
def test_wrong_account_environment_or_attempt_rejected(scenario, case):
    s = scenario
    attempt = start(s)
    payload, _ = s.provider.settle(attempt.session_id)
    session = s.provider.objects[('checkout/sessions', attempt.session_id)]
    pi = s.provider.objects[('payment_intents', session['payment_intent'])]
    expected = 400
    if case == 'envelope_account':
        payload['account'] = 'acct_OTHER_SYNTHETIC'
    elif case == 'api_account':
        s.provider.account_id = 'acct_OTHER_SYNTHETIC'
        expected = 503
    elif case == 'envelope_live':
        payload['livemode'] = True
    elif case == 'unknown_attempt':
        pi['metadata']['attempt_id'] = str(uuid4())
    elif case == 'missing_attempt':
        pi['metadata'].pop('attempt_id')
    elif case == 'cross_session':
        other = deepcopy(pi)
        other['id'] = 'pi_OTHER_SYNTHETIC'
        s.provider.objects[('payment_intents', other['id'])] = other
        payload['data']['object'] = deepcopy(other)
    assert send(s.client, s.settings, payload).status_code == expected
    assert counts(s.db, s.qid) == (0, 0, 0)


@pytest.mark.parametrize('resource,field,value', [
    ('pi', 'amount_received', 2499), ('pi', 'status', 'processing'),
    ('session', 'payment_status', 'unpaid'), ('charge', 'paid', False), ('charge', 'captured', False),
])
def test_unsettled_payment_acknowledged_but_never_credited(scenario, resource, field, value):
    s = scenario
    attempt = start(s)
    payload, _ = s.provider.settle(attempt.session_id)
    session = s.provider.objects[('checkout/sessions', attempt.session_id)]
    pi = s.provider.objects[('payment_intents', session['payment_intent'])]
    charge = s.provider.objects[('charges', pi['latest_charge'])]
    {'session': session, 'pi': pi, 'charge': charge}[resource][field] = value
    response = send(s.client, s.settings, payload)
    assert response.status_code == 200
    assert counts(s.db, s.qid) == (0, 0, 1)
    assert payment_state(s.db, s.qid) == 'pending'


@pytest.mark.parametrize('change', [
    {'stripe_mode': 'live'}, {'stripe_secret_key': 'sk_live_SYNTHETIC'},
    {'auth_environment': 'production', 'auth_origin': 'https://example.invalid'},
])
def test_live_or_production_settings_refused(runtime, change):
    values = {'database_url': runtime.settings.database_url, 'stripe_enabled': True,
              'stripe_secret_key': 'sk_test_SYNTHETIC', 'stripe_webhook_secret': 'whsec_SYNTHETIC',
              'stripe_account_id': 'acct_SYNTHETIC', 'auth_environment': 'development', 'stripe_mode': 'test'}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**values, **change})


@pytest.mark.parametrize('field,value', [('stripe_mode', 'live'), ('stripe_secret_key', 'sk_live_SYNTHETIC'), ('auth_environment', 'production'), ('stripe_enabled', False)])
def test_runtime_gate_blocks_checkout_and_signed_webhook(scenario, field, value):
    s = scenario
    setattr(s.settings, field, value)
    if field == 'auth_environment':
        s.client.cookies.set('__Host-spectra_session', s.token)
    payload = {'id': 'evt_BATCHA_' + uuid4().hex, 'livemode': False, 'type': 'payment_intent.succeeded', 'created': int(time.time()), 'data': {'object': {'id': 'pi_NONE'}}}
    assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 503
    assert send(s.client, s.settings, payload).status_code == 503
    assert not s.provider.calls
    assert counts(s.db, s.qid) == (0, 0, 0)


def test_other_customer_cannot_read_or_pay_obligation(scenario):
    s = scenario
    other = seed(s.db, 'SYNTHETIC_IDOR')
    s.db.commit()
    login(s.client, s.settings, other)
    for route in (f'/api/submissions/{s.sid}/payments/{s.qid}', f'/api/submissions/{s.sid}/commercial-state',
                  f'/api/submissions/{s.sid}/quotes/{s.qid}', f'/api/submissions/{s.sid}/order-summary'):
        assert s.client.get(route).status_code == 404
    assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 404
    # Owning one order does not allow injecting someone else's quote into it.
    assert s.client.post(f'/api/submissions/{other.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 409
    assert s.client.get(f'/api/submissions/{other.sid}/payments/{s.qid}').status_code == 404
    assert not s.provider.calls
    assert counts(s.db, s.qid) == (0, 0, 0)


def test_payload_tampering_and_csrf_rejected(scenario):
    s = scenario
    for extra in ({'amount_minor': 1}, {'currency': 'usd'}, {'paid': True}):
        assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid), **extra}).status_code == 422
    s.client.headers.pop('X-CSRF-Token')
    assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 403
    assert not s.provider.calls
    assert counts(s.db, s.qid) == (0, 0, 0)


def test_double_click_reuses_single_attempt_without_credit(scenario):
    s = scenario
    first = s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)})
    second = s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(s.provider.by_key) == 1
    assert s.db.scalar(select(func.count()).select_from(StripeAttempt).where(StripeAttempt.quote_id == s.qid)) == 1
    assert counts(s.db, s.qid) == (0, 0, 0)


def test_lost_provider_response_reuses_same_idempotency_key(scenario):
    s = scenario
    s.provider.lose_next_response = True
    assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 503
    s.db.rollback()  # End the failed request's transaction, as get_session does in production.
    assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 200
    posts = [key for method, path, key in s.provider.calls if method == 'POST']
    assert len(posts) == 2 and len(set(posts)) == 1
    assert len(s.provider.by_key) == 1
    assert counts(s.db, s.qid) == (0, 0, 0)


def test_concurrent_checkout_and_webhook_http_requests(concurrent_scenario, runtime):
    s = concurrent_scenario
    barrier = Barrier(6)

    def checkout(_):
        with TestClient(app) as client:
            login(client, s.settings, s)
            barrier.wait(timeout=15)
            response = client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)})
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(checkout, range(6)))
    assert all(code == 200 for code, body in results)
    assert len({body['url'] for code, body in results}) == 1
    assert len(s.provider.by_key) == 1
    assert len([call for call in s.provider.calls if call[0] == 'POST']) == 1
    with Session(s.engine) as db:
        attempts = db.scalars(select(StripeAttempt).where(StripeAttempt.quote_id == s.qid)).all()
        assert len(attempts) == 1
        session_id = attempts[0].session_id
        assert counts(db, s.qid) == (0, 0, 0)
    pi_event, session_event = s.provider.settle(session_id)
    barrier = Barrier(8)

    def webhook(index):
        with TestClient(app) as client:
            # No customer cookie/CSRF for signed Stripe deliveries.
            barrier.wait(timeout=15)
            return send(client, s.settings, [pi_event, session_event][index % 2]).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(webhook, range(8)))
    assert responses == [200] * 8
    with Session(s.engine) as db:
        assert counts(db, s.qid) == (1, 1, 2)
        original = immutable_result(db, s.qid)
        assert original[5] - original[4] == timedelta(days=30)
    with TestClient(app) as client:
        for payload in [session_event, pi_event] * 3:
            assert send(client, s.settings, payload).status_code == 200
    with Session(s.engine) as db:
        assert counts(db, s.qid) == (1, 1, 2)
        assert immutable_result(db, s.qid) == original
        assert db.scalar(select(func.count()).select_from(CommercialEvent).where(
            CommercialEvent.submission_id == s.sid, CommercialEvent.kind == 'provider_payment_verified')) == 1
    report = {'concurrent_checkout_requests': 6, 'checkout_http_codes': [code for code, body in results],
              'simulated_sessions': 1, 'attempts': 1, 'concurrent_webhook_requests': 8,
              'webhook_http_codes': responses, 'unique_webhook_events': 2, 'confirmations': 1,
              'deadlines': 1, 'initial_dates_preserved': True,
              'snapshot_sha256': original[-1], 'submission_id': str(s.sid), 'quote_id': str(s.qid)}
    (runtime.output / 'concurrency.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
