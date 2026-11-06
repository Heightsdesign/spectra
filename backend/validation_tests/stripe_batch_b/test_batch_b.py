import hashlib
import hmac
import json
import time
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.commercial_models import CommercialEvent, DispatchExpectation, ShipmentDeclaration, VerifiedPayment
from app.intake_models import StaffMembership
from app.pricing_models import SubmissionQuote
from app.stripe_checkout import payment_state
from app.stripe_models import StripeAttempt, StripeEvidence
from conftest import A, ui_decision


def send(s, payload):
    raw = json.dumps(payload, separators=(',', ':')).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(s.settings.stripe_webhook_secret.encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return s.client.post('/api/stripe/webhook', content=raw, headers={'stripe-signature': f't={stamp},v1={signature}'})


def start(s):
    response = s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)})
    assert response.status_code == 200, response.json()
    attempt = s.db.scalar(select(StripeAttempt).where(StripeAttempt.quote_id == s.qid).order_by(StripeAttempt.created_at.desc()))
    return attempt, response.json()


def counts(s):
    s.db.expire_all()
    return {name: s.db.scalar(select(func.count()).select_from(model).where(model.quote_id == s.qid))
            for name, model in [('payments', VerifiedPayment), ('deadlines', DispatchExpectation), ('evidence', StripeEvidence)]}


def initial_identity(s):
    s.db.expire_all()
    payment = s.db.get(VerifiedPayment, s.qid)
    deadline = s.db.scalar(select(DispatchExpectation).where(DispatchExpectation.quote_id == s.qid))
    return {'payment_id': payment.provider_payment_id, 'event_id': payment.provider_event_id,
            'verified_at': payment.verified_at.isoformat(), 'recorded_at': payment.recorded_at.isoformat(),
            'deadline_payment_at': deadline.verified_payment_at.isoformat(), 'deadline': deadline.dispatch_deadline.isoformat(),
            'snapshot_hash': A.canonical_hash(s.db.get(SubmissionQuote, s.qid).snapshot)}


def settled(s):
    attempt, _ = start(s)
    pi_event, session_event = s.provider.settle(attempt.session_id)
    assert send(s, pi_event).status_code == 200
    assert counts(s)['payments'] == counts(s)['deadlines'] == 1
    session = s.provider.objects[('checkout/sessions', attempt.session_id)]
    pi = s.provider.objects[('payment_intents', session['payment_intent'])]
    charge = s.provider.objects[('charges', pi['latest_charge'])]
    return attempt, pi_event, session_event, charge


def state(s):
    response = s.client.get(f'/api/submissions/{s.sid}/commercial-state')
    assert response.status_code == 200
    return response.json()


def export_frame(s, runtime, name, **extra):
    commercial = state(s)
    frame = {'name': name, 'commercial': commercial,
             'item': s.client.get(f'/api/submissions/{s.sid}').json(),
             'order': s.client.get(f'/api/submissions/{s.sid}/order-summary').json(),
             'quote': s.client.get(f'/api/submissions/{s.sid}/quotes/{s.qid}').json(),
             'ui': ui_decision(commercial), **extra}
    runtime.frames.append(frame)
    return frame


def event(kind, obj):
    return {'id': 'evt_BATCHB_' + uuid4().hex, 'livemode': False, 'type': kind,
            'created': int(time.time()), 'data': {'object': deepcopy(obj)}}


def restrict(s, kind, charge):
    if kind == 'manual_hold':
        s.db.add(StaffMembership(customer_id=s.customer_id, role='admin'))
        s.db.commit()
        response = s.client.post(f'/internal/intake/submissions/{s.sid}/payment-hold', json={
            'quote_id': str(s.qid), 'request_key': str(uuid4()), 'reason': 'SYNTHETIC BATCH B'})
        assert response.status_code == 200
        return None
    if kind == 'partial':
        charge['amount_refunded'] = 500
        payload = event('refund.created', {'id': 're_BATCHB_' + uuid4().hex, 'charge': charge['id'], 'amount': 500, 'status': 'succeeded'})
    elif kind == 'full':
        charge.update(amount_refunded=2500, refunded=True)
        payload = event('charge.refunded', charge)
    elif kind == 'dispute':
        charge['disputed'] = True
        payload = event('charge.dispute.created', {'id': 'dp_BATCHB_' + uuid4().hex, 'charge': charge['id'], 'status': 'needs_response'})
    elif kind == 'refund_failed':
        payload = event('refund.failed', {'id': 're_BATCHB_' + uuid4().hex, 'charge': charge['id'], 'amount': 500, 'status': 'failed'})
    elif kind == 'closed_dispute':
        payload = event('charge.dispute.closed', {'id': 'dp_BATCHB_' + uuid4().hex, 'charge': charge['id'], 'status': 'won'})
    else:
        raise AssertionError('Unknown synthetic restriction')
    assert send(s, payload).status_code == 200
    return payload


@pytest.mark.parametrize('kind,label', [
    ('partial', 'partially_refunded'), ('full', 'refunded'), ('dispute', 'dispute_review'),
    ('refund_failed', 'financial_review'), ('closed_dispute', 'dispute_review'), ('manual_hold', 'commercial_hold'),
])
def test_restriction_api_must_reject_new_shipment(scenario, runtime, kind, label):
    """Security requirement. Keep this test RED if the real API permits the write."""
    s = scenario
    _, _, _, charge = settled(s)
    baseline = initial_identity(s)
    before = state(s)
    assert ui_decision(before)['canDeclareShipment'] is True
    restrict(s, kind, charge)
    frame = export_frame(s, runtime, 'restriction_' + kind)
    restricted = frame['commercial']
    assert restricted['payment_status'] == 'restricted'
    assert restricted['charging_enabled'] is False
    assert label in restricted['financial_restrictions']
    assert frame['ui']['canDeclareShipment'] is False
    assert initial_identity(s) == baseline
    assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 409
    post = s.client.post(f'/api/submissions/{s.sid}/shipment-declarations', json={
        'request_key': str(uuid4()), 'carrier': 'SYNTHETIC', 'tracking': 'NO_REAL_SHIPMENT', 'declared_dispatch_at': None})
    declarations = s.db.scalar(select(func.count()).select_from(ShipmentDeclaration).where(ShipmentDeclaration.submission_id == s.sid))
    audit = s.db.scalar(select(func.count()).select_from(CommercialEvent).where(
        CommercialEvent.submission_id == s.sid, CommercialEvent.kind == 'customer_shipment_declared'))
    assert initial_identity(s) == baseline
    evidence = {'code': 'B-P1', 'variant': kind, 'route': 'POST /api/submissions/{id}/shipment-declarations',
                'commercial_state_before': restricted['payment_status'], 'restriction_labels': restricted['financial_restrictions'],
                'ui_can_declare': frame['ui']['canDeclareShipment'], 'checkout_http': 409,
                'expected_shipment_http': 409, 'actual_shipment_http': post.status_code,
                'declarations_created': declarations, 'declaration_audit_events_created': audit,
                'financial_identity_unchanged': True, 'transaction_rolled_back_at_teardown': True,
                'submission_id': str(s.sid), 'quote_id': str(s.qid)}
    runtime.findings.append(evidence)
    assert post.status_code == 409, f'B-P1 confirmed: restricted={kind}, UI denies, API returned {post.status_code}, declarations={declarations}'
    assert declarations == 0
    assert audit == 0


@pytest.mark.parametrize('kind', ['partial', 'full', 'dispute', 'refund_failed', 'closed_dispute', 'manual_hold'])
def test_historical_shipment_replay_after_restriction(scenario, kind):
    s = scenario
    _, _, _, charge = settled(s)
    payload = {'request_key': str(uuid4()), 'tracking': 'HISTORICAL'}
    path = f'/api/submissions/{s.sid}/shipment-declarations'
    assert s.client.post(path, json=payload).status_code == 201
    restrict(s, kind, charge)
    baseline = initial_identity(s)
    rows = s.db.scalars(select(ShipmentDeclaration).where(ShipmentDeclaration.submission_id == s.sid)).all()
    original = [(row.id, row.recorded_at, row.tracking) for row in rows]
    audits = s.db.scalar(select(func.count()).select_from(CommercialEvent).where(CommercialEvent.submission_id == s.sid))
    assert s.client.post(path, json=payload).status_code == 201
    conflict = s.client.post(path, json={**payload, 'tracking': 'DIVERGENT'})
    assert conflict.status_code == 409 and conflict.json()['detail'] == 'idempotency_conflict'
    s.db.expire_all()
    assert [(row.id, row.recorded_at, row.tracking) for row in s.db.scalars(select(ShipmentDeclaration).where(ShipmentDeclaration.submission_id == s.sid))] == original
    assert s.db.scalar(select(func.count()).select_from(CommercialEvent).where(CommercialEvent.submission_id == s.sid)) == audits
    assert initial_identity(s) == baseline


def unsettled(s, pi_status, session_status='open'):
    attempt, result = start(s)
    s.provider.settle(attempt.session_id)
    session = s.provider.objects[('checkout/sessions', attempt.session_id)]
    pi = s.provider.objects[('payment_intents', session['payment_intent'])]
    charge = s.provider.objects[('charges', pi['latest_charge'])]
    session.update(status=session_status, payment_status='unpaid')
    pi.update(status=pi_status, amount_received=0)
    charge.update(paid=False, captured=False)
    return attempt, session, pi, charge, result


def assert_no_credit(s):
    value = counts(s)
    assert value['payments'] == value['deadlines'] == 0


def test_unpaid_order_cannot_declare_shipment(scenario, runtime):
    s = scenario
    frame = export_frame(s, runtime, 'awaiting_payment')
    assert frame['commercial']['payment_status'] == 'awaiting_payment'
    assert frame['ui']['canDeclareShipment'] is False
    response = s.client.post(f'/api/submissions/{s.sid}/shipment-declarations', json={'request_key': str(uuid4())})
    assert response.status_code == 409
    assert_no_credit(s)


def test_paid_unrestricted_shipment_remains_idempotent(scenario, runtime):
    s = scenario
    settled(s)
    baseline = initial_identity(s)
    frame = export_frame(s, runtime, 'verified')
    assert frame['ui']['canDeclareShipment'] is True
    payload = {'request_key': str(uuid4()), 'carrier': 'SYNTHETIC', 'tracking': 'TEST'}
    first = s.client.post(f'/api/submissions/{s.sid}/shipment-declarations', json=payload)
    second = s.client.post(f'/api/submissions/{s.sid}/shipment-declarations', json=payload)
    assert first.status_code == second.status_code == 201
    assert len(second.json()['shipment_declarations']) == 1
    assert s.db.scalar(select(func.count()).select_from(ShipmentDeclaration).where(ShipmentDeclaration.submission_id == s.sid)) == 1
    conflict = s.client.post(f'/api/submissions/{s.sid}/shipment-declarations', json={**payload, 'tracking': 'DIFFERENT'})
    assert conflict.status_code == 409
    assert initial_identity(s) == baseline


def test_declined_card_resumes_same_open_checkout_then_settles(scenario, runtime):
    s = scenario
    attempt, session, pi, _, first = unsettled(s, 'requires_payment_method')
    snapshot = A.canonical_hash(s.db.get(SubmissionQuote, s.qid).snapshot)
    assert send(s, event('payment_intent.payment_failed', pi)).status_code == 200
    frame = export_frame(s, runtime, 'failed')
    assert frame['commercial']['payment_status'] == 'failed'
    assert_no_credit(s)
    _, resumed = start(s)
    assert resumed['url'] == first['url']
    assert len(s.provider.by_key) == 1
    success, complete = s.provider.settle(attempt.session_id)
    assert send(s, success).status_code == 200
    baseline = initial_identity(s)
    for item in [complete, success] * 3:
        assert send(s, item).status_code == 200
        assert initial_identity(s) == baseline
    assert counts(s)['payments'] == counts(s)['deadlines'] == 1
    assert baseline['snapshot_hash'] == snapshot
    assert s.db.get(VerifiedPayment, s.qid).amount_minor == 2500
    assert s.db.get(VerifiedPayment, s.qid).currency == 'EUR'


def test_3ds_open_session_challenge_abandon_then_success(scenario, runtime):
    s = scenario
    attempt, session, pi, _, first = unsettled(s, 'requires_action')
    assert send(s, event('payment_intent.requires_action', pi)).status_code == 200
    frame = export_frame(s, runtime, 'action_required_open')
    assert frame['commercial']['payment_status'] == 'action_required'
    assert frame['ui']['canDeclareShipment'] is False
    assert_no_credit(s)
    for suffix in ['?stripe_return=1', '?paid=true', '?stripe_return=1&paid=true']:
        assert s.client.get(f'/api/submissions/{s.sid}/payments/{s.qid}{suffix}').json()['status'] == 'action_required'
    _, resumed = start(s)
    assert resumed['url'] == first['url']
    assert len(s.provider.by_key) == 1
    assert_no_credit(s)
    success, _ = s.provider.settle(attempt.session_id)
    assert send(s, success).status_code == 200
    assert state(s)['payment_status'] == 'verified'


@pytest.mark.parametrize('next_action', ['absent', None, {'type': 'use_stripe_sdk'}, {'type': 'unknown_action', 'url': 'https://example.invalid/do-not-expose'}])
@pytest.mark.parametrize('webhook_first', [False, True])
def test_completed_session_requires_operator_review_without_financial_hold(scenario, runtime, next_action, webhook_first):
    s = scenario
    attempt, session, pi, _, _ = unsettled(s, 'requires_action', 'complete')
    # Deliberately synthetic: not evidence that Stripe can reach these states.
    session['url'] = None
    pi['client_secret'] = 'SYNTHETIC_SECRET_MUST_NOT_LEAK'
    if next_action != 'absent':
        pi['next_action'] = next_action
    delayed_action = event('payment_intent.requires_action', pi)
    if webhook_first:
        assert send(s, delayed_action).status_code == 200
        assert state(s)['payment_review_required'] is True
    old_status = attempt.status
    for _ in range(3):
        current, result = start(s)
        assert current.id == attempt.id
        assert result == {'status': 'action_required', 'url': None, 'payment_review_required': True}
    assert old_status in {'pending', 'action_required'}
    frame = export_frame(s, runtime, 'action_required_complete', checkout_result=result)
    assert frame['commercial']['payment_status'] == 'action_required'
    assert frame['commercial']['payment_review_required'] is True
    assert frame['commercial']['charging_enabled'] is False
    assert frame['ui']['canStartCheckout'] is False
    assert 'SELBY' in frame['ui']['statusFR']
    assert 'SELBY' in frame['ui']['statusEN']
    payment_response = s.client.get(f'/api/submissions/{s.sid}/payments/{s.qid}')
    assert payment_response.status_code == 200
    assert payment_response.json() == {'status': 'action_required', 'restrictions': [], 'payment_review_required': True}
    assert 'SYNTHETIC_SECRET' not in json.dumps([result, frame, payment_response.json()])
    assert frame['commercial']['financial_restrictions'] == []
    assert_no_credit(s)
    assert s.db.scalar(select(func.count()).select_from(CommercialEvent).where(CommercialEvent.submission_id == s.sid, CommercialEvent.kind == 'provider_payment_verified')) == 0
    assert len(s.provider.by_key) == 1
    assert s.db.scalar(select(func.count()).select_from(StripeAttempt).where(StripeAttempt.quote_id == s.qid)) == 1
    assert all(path == 'checkout/sessions' for method, path, _ in s.provider.calls if method == 'POST')

    # Same PI succeeds later; the review indication must not inhibit settlement.
    success, completed = s.provider.settle(attempt.session_id)
    assert success['data']['object']['id'] == pi['id']
    assert send(s, completed).status_code == 200
    baseline = initial_identity(s)
    for payload in [success, completed, delayed_action, delayed_action, success]:
        assert send(s, payload).status_code == 200
        assert initial_identity(s) == baseline
        assert state(s)['payment_review_required'] is False
        assert state(s)['payment_status'] == 'verified'
    assert counts(s)['payments'] == counts(s)['deadlines'] == 1
    assert s.db.scalar(select(func.count()).select_from(CommercialEvent).where(CommercialEvent.submission_id == s.sid, CommercialEvent.kind == 'provider_payment_verified')) == 1
    payment = s.db.get(VerifiedPayment, s.qid)
    deadline = s.db.get(DispatchExpectation, s.sid)
    assert deadline.dispatch_deadline == payment.verified_at + timedelta(days=30)
    assert len(s.provider.by_key) == 1


@pytest.mark.parametrize('lost_response', [False, True])
def test_failed_completed_checkout_cancels_old_pi_before_replacement(scenario, runtime, lost_response):
    s = scenario
    old, _, pi, _, _ = unsettled(s, 'requires_payment_method', 'complete')
    assert send(s, event('checkout.session.async_payment_failed', s.provider.objects[('checkout/sessions', old.session_id)])).status_code == 200
    s.provider.fail_cancel_response_once = lost_response
    if lost_response:
        assert s.client.post(f'/api/submissions/{s.sid}/stripe-checkout', json={'quote_id': str(s.qid)}).status_code == 503
        s.db.rollback()
    _, cancelled = start(s)
    assert cancelled == {'status': 'cancelled', 'url': None, 'payment_review_required': False}
    assert pi['status'] == 'canceled'
    assert_no_credit(s)
    export_frame(s, runtime, 'cancelled_retry_' + str(lost_response))
    replacement, resumed = start(s)
    assert resumed['url']
    assert replacement.id != old.id
    assert len(s.provider.by_key) == 2
    assert len([value for value in s.provider.calls if value[1].endswith('/cancel')]) == 1
    success, _ = s.provider.settle(replacement.session_id)
    assert send(s, success).status_code == 200
    assert counts(s)['payments'] == counts(s)['deadlines'] == 1


def test_abandoned_checkout_and_browser_return_never_credit(scenario, runtime):
    s = scenario
    _, first = start(s)
    provider_calls = len(s.provider.calls)
    for _ in range(3):
        for suffix in ['?stripe_return=1', '?paid=true', '?stripe_return=1&paid=true']:
            response = s.client.get(f'/api/submissions/{s.sid}/payments/{s.qid}{suffix}')
            assert response.json()['status'] == 'pending'
    assert len(s.provider.calls) == provider_calls
    assert_no_credit(s)
    export_frame(s, runtime, 'abandoned_pending')
    _, resumed = start(s)
    assert resumed == first
    assert len(s.provider.by_key) == 1


def test_expired_checkout_without_pi_can_be_replaced(scenario, runtime):
    s = scenario
    old, _ = start(s)
    session = s.provider.objects[('checkout/sessions', old.session_id)]
    session['status'] = 'expired'
    assert send(s, event('checkout.session.expired', session)).status_code == 200
    frame = export_frame(s, runtime, 'expired')
    assert frame['commercial']['payment_status'] == 'expired'
    assert_no_credit(s)
    new, result = start(s)
    assert new.id != old.id and result['url']
    assert session['status'] == 'expired'
    assert len(s.provider.by_key) == 2
    assert_no_credit(s)


def test_expiration_without_webhook_requires_observation_then_replacement(scenario):
    s = scenario
    old, _ = start(s)
    s.provider.objects[('checkout/sessions', old.session_id)]['status'] = 'expired'
    assert state(s)['payment_status'] == 'pending'
    _, first_click = start(s)
    assert first_click == {'status': 'expired', 'url': None, 'payment_review_required': False}
    _, second_click = start(s)
    assert second_click['url']
    assert len(s.provider.by_key) == 2
    assert_no_credit(s)


@pytest.mark.parametrize('pi_status,expected', [('requires_payment_method', 'failed'), ('canceled', 'cancelled')])
def test_expiration_with_pi_uses_canonical_pi_state(scenario, runtime, pi_status, expected):
    s = scenario
    _, session, _, _, _ = unsettled(s, pi_status, 'expired')
    assert send(s, event('checkout.session.expired', session)).status_code == 200
    frame = export_frame(s, runtime, 'expired_pi_' + expected)
    assert frame['commercial']['payment_status'] == expected
    assert_no_credit(s)


def test_cancelled_french_message_is_not_corrupted(runtime):
    status = {'payment_status': 'cancelled', 'verified_payment_at': None, 'dispatch_deadline': None,
              'shipment_declarations': [], 'parcel_receipts': []}
    actual = ui_decision(status)['statusFR']
    if actual != 'Tentative annulée':
        runtime.findings.append({'code': 'B-P3', 'status': 'cancelled', 'expected': 'Tentative annulée', 'actual': actual,
                                 'description': 'French cancellation label contains a lost character'})
    assert actual == 'Tentative annulée'


@pytest.mark.parametrize('first_kind', ['payment_intent.succeeded', 'checkout.session.completed'])
def test_delayed_webhook_and_browser_return_preserve_settlement_clock(scenario, runtime, monkeypatch, first_kind):
    from app.auth import now
    s = scenario
    attempt, _ = start(s)
    pi_event, session_event = s.provider.settle(attempt.session_id)
    assert_no_credit(s)
    calls = len(s.provider.calls)
    for _ in range(3):
        assert s.client.get(f'/api/submissions/{s.sid}/payments/{s.qid}?stripe_return=1&paid=true').json()['status'] == 'pending'
    assert len(s.provider.calls) == calls
    export_frame(s, runtime, 'webhook_delayed_' + first_kind)
    recorded_clock = now() + timedelta(seconds=60)
    monkeypatch.setattr('app.commercial.now', lambda: recorded_clock)
    delivery = [pi_event, session_event] if first_kind == 'payment_intent.succeeded' else [session_event, pi_event]
    for payload in delivery:
        assert send(s, payload).status_code == 200
    payment = s.db.get(VerifiedPayment, s.qid)
    deadline = s.db.scalar(select(DispatchExpectation).where(DispatchExpectation.quote_id == s.qid))
    assert int(payment.verified_at.timestamp()) == pi_event['created']
    assert payment.recorded_at - payment.verified_at >= timedelta(seconds=59)
    assert deadline.dispatch_deadline == payment.verified_at + timedelta(days=30)
    assert deadline.dispatch_deadline != payment.recorded_at + timedelta(days=30)
    baseline = initial_identity(s)
    for payload in delivery * 3:
        assert send(s, payload).status_code == 200
        assert initial_identity(s) == baseline
    assert counts(s) == {'payments': 1, 'deadlines': 1, 'evidence': 2}


@pytest.mark.parametrize('kind,label', [('partial', 'partially_refunded'), ('full', 'refunded'), ('dispute', 'dispute_review'),
                                        ('refund_failed', 'financial_review'), ('closed_dispute', 'dispute_review')])
def test_restrictions_preserve_historical_payment_dates_and_snapshot(scenario, runtime, kind, label):
    s = scenario
    _, success, complete, charge = settled(s)
    baseline = initial_identity(s)
    restriction = restrict(s, kind, charge)
    for payload in [restriction, success, complete, restriction, complete]:
        assert send(s, payload).status_code == 200
        assert initial_identity(s) == baseline
    frame = export_frame(s, runtime, 'persistent_' + kind)
    assert frame['commercial']['payment_status'] == 'restricted'
    assert label in frame['commercial']['financial_restrictions']
    assert frame['ui']['canDeclareShipment'] is False
    assert frame['ui']['isTracking'] is True
    assert counts(s)['payments'] == counts(s)['deadlines'] == 1
    assert s.db.get(VerifiedPayment, s.qid).amount_minor == 2500
    assert s.db.scalar(select(func.count()).select_from(CommercialEvent).where(
        CommercialEvent.submission_id == s.sid, CommercialEvent.kind == 'provider_payment_verified')) == 1


def test_full_refund_supersedes_partial_label_without_summing_snapshots(scenario, runtime):
    s = scenario
    _, _, _, charge = settled(s)
    baseline = initial_identity(s)
    restrict(s, 'partial', charge)
    assert 'partially_refunded' in state(s)['financial_restrictions']
    restrict(s, 'full', charge)
    final = state(s)
    assert 'refunded' in final['financial_restrictions']
    assert 'partially_refunded' not in final['financial_restrictions']
    amounts = s.db.scalars(select(StripeEvidence.data).where(StripeEvidence.quote_id == s.qid, StripeEvidence.restricted.is_(True))).all()
    assert sorted(value['amount_refunded_minor'] for value in amounts) == [500, 2500]
    assert max(value['amount_refunded_minor'] for value in amounts) == 2500
    assert initial_identity(s) == baseline
    export_frame(s, runtime, 'full_after_partial')


@pytest.mark.parametrize('outcome', ['won', 'lost'])
def test_dispute_closed_never_implicitly_removes_restriction(scenario, runtime, outcome):
    s = scenario
    _, _, _, charge = settled(s)
    baseline = initial_identity(s)
    created = restrict(s, 'dispute', charge)
    charge['disputed'] = False
    closed = event('charge.dispute.closed', {**created['data']['object'], 'status': outcome})
    assert send(s, closed).status_code == 200
    assert state(s)['payment_status'] == 'restricted'
    assert 'dispute_review' in state(s)['financial_restrictions']
    assert initial_identity(s) == baseline
    export_frame(s, runtime, 'dispute_closed_' + outcome)


@pytest.mark.parametrize('kind', ['partial', 'full', 'dispute'])
def test_restriction_before_success_delivery_never_creates_late_credit(scenario, runtime, kind):
    s = scenario
    attempt, _ = start(s)
    success, complete = s.provider.settle(attempt.session_id)
    pi = s.provider.objects[('payment_intents', success['data']['object']['id'])]
    charge = s.provider.objects[('charges', pi['latest_charge'])]
    restrict(s, kind, charge)
    for payload in [complete, success] * 2:
        assert send(s, payload).status_code == 200
        assert_no_credit(s)
    frame = export_frame(s, runtime, 'restriction_before_verification_' + kind)
    assert frame['commercial']['payment_status'] == 'restricted'
    assert frame['commercial']['verified_payment_at'] is None
    assert frame['ui']['isTracking'] is False


def test_commercial_card_restriction_does_not_unlock_custody(scenario):
    from types import SimpleNamespace
    from app.commercial import card_commercial_state
    s = scenario
    _, _, _, charge = settled(s)
    restrict(s, 'partial', charge)
    # A domain-only stand-in; no physical card, intake or custody record is created.
    result = card_commercial_state(s.db, SimpleNamespace(id=uuid4(), submission_id=s.sid))
    assert result['commercially_eligible'] is False
    assert 'original_shipping_financial_restriction' in result['reasons']
