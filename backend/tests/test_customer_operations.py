"""W5.1b privacy, authorization, bounded reads and immutable intake traceability."""
import copy
import secrets
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from app.auth import csrf_value, digest, now
from app.checkout_models import CustomerAddress, SubmissionDelivery
from app.customer_models import Customer, CustomerSession, CustomerToken
from app.intake_models import Intake, IntakeAudit, Parcel, PhysicalCard, StaffMembership
from app.pricing_models import PricingCatalog, QuoteAcceptance, SubmissionQuote
from app.submission_models import Submission, SubmissionEntry

BASE = '/internal/customer-operations'


def account(db, email, first='Claire', last='Tracé', **extra):
    row = Customer(email=email, first_name=first, last_name=last,
                   password_hash='PASSWORD-HASH-MUST-NOT-LEAK', email_verified=True, **extra)
    db.add(row)
    db.flush()
    return row


def login(client, db, customer):
    raw = secrets.token_urlsafe(32)
    db.add(CustomerSession(customer_id=customer.id, token_hash=digest(raw), expires_at=now()+timedelta(hours=1)))
    db.flush()
    client.cookies.set('spectra_session', raw)
    return raw


@pytest.fixture
def operations(api):
    client, db, settings = api
    tag = uuid4().hex
    actor = account(db, f'staff-{tag}@example.invalid', first='Operator')
    db.add(StaffMembership(customer_id=actor.id, role='operator'))
    customer = account(db, f'claire-{tag}@example.invalid')
    other = account(db, f'other-{tag}@example.invalid', first='Other', last='Collector')
    saved = CustomerAddress(customer_id=customer.id, recipient='Shipment recipient', line1='2 Current Street',
                            city='Current City', country='FR', phone='+33123456789')
    db.add(saved)
    db.flush()
    old_address = {'recipient': 'Historical recipient', 'line1': '1 Historical Street', 'line2': '',
                   'postal_code': '75001', 'city': 'Historical City', 'country': 'FR', 'phone': '+33987654321',
                   'instructions': 'Historical instructions', 'unexpected_secret': 'SNAPSHOT-SECRET'}
    items = []
    for status in ('submitted', 'draft', 'submitted'):
        submission = Submission(customer_id=customer.id, reference='SP-'+uuid4().hex.upper(), status=status,
                                confirmed_at=now() if status == 'submitted' else None)
        db.add(submission)
        db.flush()
        entry = SubmissionEntry(submission_id=submission.id, game='pokemon', card_name='Test card',
                                expansion='Test set', card_number='1', language='FR', quantity=2)
        db.add(entry)
        db.flush()
        items.append((submission, entry))
    submission, entry = items[0]
    db.add(SubmissionDelivery(submission_id=submission.id, address_id=saved.id))
    db.add(SubmissionDelivery(submission_id=items[1][0].id, address_id=saved.id))
    catalog = PricingCatalog(document={})
    db.add(catalog)
    db.flush()
    quote = SubmissionQuote(submission_id=submission.id, catalog_version=catalog.version,
                            pricing_revision=1, created_at=now(), expires_at=now()+timedelta(hours=1),
                            snapshot={'checkout': {'return_address': old_address}, 'secret': 'QUOTE-SECRET'})
    db.add(quote)
    db.flush()
    db.add(QuoteAcceptance(submission_id=submission.id, quote_id=quote.id))
    db.add(Intake(submission_id=submission.id, status='reconciled', override_reason='Test authorized workflow'))
    parcel = Parcel(reference='PI-'+uuid4().hex.upper(), submission_id=submission.id, received_by=actor.id,
                    request_key=uuid4(), request_data={}, status='reconciled')
    db.add(parcel)
    db.flush()
    card = PhysicalCard(reference='PC-'+uuid4().hex.upper(), submission_id=submission.id, parcel_id=parcel.id,
                        entry_id=entry.id, received_by=actor.id, request_key=uuid4(), request_data={}, status='matched')
    db.add(card)
    db.add(IntakeAudit(actor_id=actor.id, submission_id=submission.id, action='intake_transition', entity_id=submission.id,
                       data={'before': 'reconciliation_pending', 'after': 'reconciled'}, reason='Test finalization'))
    unrelated = Submission(customer_id=other.id, reference='SP-'+uuid4().hex.upper(), status='submitted', confirmed_at=now())
    db.add(unrelated)
    db.add(CustomerAddress(customer_id=other.id, recipient='Private other recipient', line1='Other street', city='Other City', country='FR'))
    db.add(CustomerToken(customer_id=customer.id, purpose='verify', token_hash='TOKEN-MUST-NOT-LEAK', expires_at=now()+timedelta(hours=1)))
    raw = login(client, db, actor)
    db.commit()
    return client, db, settings, actor, customer, other, items, parcel, card, saved, raw


def private(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers['cache-control'] == 'private, no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert response.headers['x-content-type-options'] == 'nosniff'
    for value in ('password_hash', 'token_hash', 'customer_sessions', 'PASSWORD-HASH-MUST-NOT-LEAK',
                  'TOKEN-MUST-NOT-LEAK', 'SNAPSHOT-SECRET', 'QUOTE-SECRET', 'unexpected_secret'):
        assert value not in response.text
    return response.json()


@pytest.mark.parametrize('endpoint', ['/customers', '/customers/not-a-uuid', '/customers/not-a-uuid/submissions', '/cards/bad'])
@pytest.mark.parametrize('access', ['anonymous', 'customer', 'revoked', 'disabled', 'unverified', 'removed_staff'])
def test_staff_boundary_before_lookup_and_validation(operations, endpoint, access):
    client, db, _, actor, customer, *rest = operations
    if access == 'anonymous':
        client.cookies.clear()
    elif access == 'customer':
        login(client, db, customer)
    elif access == 'removed_staff':
        db.delete(db.get(StaffMembership, actor.id))
    elif access == 'revoked':
        db.scalar(select(CustomerSession).where(CustomerSession.customer_id == actor.id)).revoked_at = now()
    elif access == 'disabled':
        actor.status = 'disabled'
    else:
        actor.email_verified = False
    db.commit()
    private(client.get(BASE+endpoint), 403 if access in {'customer', 'removed_staff'} else 401)


def test_directory_search_and_minimal_payload(operations):
    client, db, _, actor, customer, other, *_ = operations
    for search in ('cLaIrE', 'Claire Tracé', customer.email.upper(), str(customer.id).upper()):
        data = private(client.get(BASE+'/customers', params={'search': search}))
        assert customer.id in {UUID(row['id']) for row in data['items']}
        assert other.id not in {UUID(row['id']) for row in data['items']}
        assert set(data['items'][0]) == {'id','first_name','last_name','email','status','created_at'}
    assert private(client.get(BASE+'/customers', params={'search': str(uuid4())}))['items'] == []
    assert private(client.get(BASE+'/customers', params={'search': '%%'}))['items'] == []
    assert private(client.get(BASE+'/customers', params={'search': '__'}))['items'] == []
    literal = account(db, uuid4().hex+'@example.invalid', first='Literal%_name', last='Only')
    db.commit()
    assert [row['id'] for row in private(client.get(BASE+'/customers', params={'search': '%_'}))['items']] == [str(literal.id)]
    actor.status = 'active'
    other.status = 'disabled'
    db.commit()
    assert private(client.get(BASE+'/customers', params={'search': str(other.id)}))['items'][0]['status'] == 'disabled'


def test_directory_pagination_is_bounded_and_stable(operations):
    client, *_ = operations
    expected = private(client.get(BASE+'/customers', params={'limit':50}))['items']
    seen = []
    for offset in range(len(expected)):
        result = private(client.get(BASE+'/customers', params={'limit':1, 'offset':offset}))
        assert result['limit'] == 1 and result['offset'] == offset
        assert result['has_more'] == (offset < len(expected)-1)
        seen.extend(result['items'])
    assert seen == expected
    assert private(client.get(BASE+'/customers', params={'offset':100_000}))['items'] == []


@pytest.mark.parametrize('query', [{'limit':0}, {'limit':51}, {'offset':-1}, {'offset':100001}, {'limit':'all'},
                                  {'search':'x'}, {'search':'x'*255}, {'search':'a\x00b'}])
def test_directory_parameter_validation(operations, query):
    private(operations[0].get(BASE+'/customers', params=query), 422)


def test_customer_account_and_shipment_contacts_are_separate(operations):
    client, _, _, _, customer, other, *_ = operations
    detail = private(client.get(BASE+'/customers/'+str(customer.id)))
    assert detail['first_name'] == 'Claire' and detail['email_verified'] is True
    assert 'phone' not in detail
    assert detail['saved_addresses'][0]['recipient'] == 'Shipment recipient'
    assert detail['saved_addresses'][0]['phone'] == '+33123456789'
    assert 'Private other recipient' not in str(detail)
    assert detail['addresses_truncated'] is False
    assert private(client.get(BASE+'/customers/'+str(other.id)))['saved_addresses'][0]['recipient'] == 'Private other recipient'
    private(client.get(BASE+'/customers/'+str(uuid4())), 404)
    private(client.get(BASE+'/customers/not-a-uuid'), 422)


def test_history_scopes_quantities_states_and_address_provenance(operations):
    client, db, _, _, customer, other, items, _, _, saved, *_ = operations
    data = private(client.get(BASE+'/customers/'+str(customer.id)+'/submissions'))
    assert {row['id'] for row in data['items']} == {str(s.id) for s,e in items}
    assert all(row['declared_quantity'] == 2 for row in data['items'])
    frozen = next(row for row in data['items'] if row['id'] == str(items[0][0].id))
    assert frozen['intake_status'] == 'reconciled'
    assert frozen['return_address_source'] == 'accepted_snapshot'
    assert frozen['return_address']['recipient'] == 'Historical recipient'
    draft = next(row for row in data['items'] if row['status'] == 'draft')
    assert draft['return_address_source'] == 'current_selection'
    assert draft['return_address']['recipient'] == 'Shipment recipient'
    saved.recipient = 'Changed saved recipient'
    db.commit()
    current = private(client.get(BASE+'/customers/'+str(customer.id)+'/submissions'))
    assert next(row for row in current['items'] if row['id'] == frozen['id']) == frozen
    unrelated = private(client.get(BASE+'/customers/'+str(other.id)+'/submissions'))
    assert not {row['id'] for row in unrelated['items']} & {row['id'] for row in data['items']}
    pages = [private(client.get(BASE+'/customers/'+str(customer.id)+'/submissions', params={'limit':1,'offset':i})) for i in range(3)]
    assert [p['items'][0]['id'] for p in pages] == [r['id'] for r in data['items']]
    assert [p['has_more'] for p in pages] == [True,True,False]
    private(client.get(BASE+'/customers/'+str(customer.id)+'/submissions?limit=51'), 422)


def test_legacy_snapshot_is_not_replaced_by_current_address(operations):
    client, db, _, _, customer, _, items, *_ = operations
    quote = db.scalar(select(SubmissionQuote).where(SubmissionQuote.submission_id == items[0][0].id))
    # A separate accepted legacy submission, not a modification of an immutable quote.
    legacy = Submission(customer_id=customer.id, reference='SP-'+uuid4().hex.upper(), status='submitted')
    db.add(legacy); db.flush()
    old = SubmissionQuote(submission_id=legacy.id, catalog_version=quote.catalog_version, pricing_revision=1,
                          created_at=now(), expires_at=now()+timedelta(hours=1), snapshot={'grading': {}})
    db.add(old); db.flush()
    db.add(QuoteAcceptance(submission_id=legacy.id, quote_id=old.id)); db.commit()
    data = private(client.get(BASE+'/customers/'+str(customer.id)+'/submissions'))
    row = next(row for row in data['items'] if row['id'] == str(legacy.id))
    assert row['return_address'] is None and row['return_address_source'] == 'not_recorded'


def test_exact_card_trace_and_unidentified_card(operations):
    client, db, _, _, customer, _, items, parcel, card, *_ = operations
    result = private(client.get(BASE+'/cards/'+card.reference.lower()))
    assert result['card']['reference'] == card.reference
    assert result['parcel']['id'] == str(parcel.id)
    assert result['submission']['id'] == str(items[0][0].id)
    assert result['customer'] == {'id':str(customer.id),'first_name':customer.first_name,'last_name':customer.last_name,'email':customer.email}
    assert result['declared_entry']['id'] == str(items[0][1].id)
    unknown = PhysicalCard(reference='PC-'+uuid4().hex.upper(), submission_id=items[2][0].id, parcel_id=parcel.id,
                           received_by=operations[3].id, request_key=uuid4(), request_data={})
    # Deliberate cross-submission corruption is detected, never silently resolved.
    db.add(unknown); db.commit()
    private(client.get(BASE+'/cards/'+unknown.reference), 409)
    unknown.submission_id = items[0][0].id
    db.commit()
    assert private(client.get(BASE+'/cards/'+unknown.reference))['declared_entry'] is None
    unknown.entry_id = items[2][1].id
    db.commit()
    private(client.get(BASE+'/cards/'+unknown.reference), 409)


@pytest.mark.parametrize('reference', ['PC-', 'PC-123', 'SP-'+'A'*32, 'PC-'+'Z'*32, 'PC-'+'A'*33, '*'])
def test_invalid_card_reference(operations, reference):
    private(operations[0].get(BASE+'/cards/'+reference), 422)


def test_unknown_card_and_no_public_tracking_leak(operations):
    client, db, _, _, customer, _, items, _, card, *_ = operations
    private(client.get(BASE+'/cards/PC-'+uuid4().hex.upper()), 404)
    login(client, db, customer); db.commit()
    response = client.get('/api/submissions/'+str(items[0][0].id))
    assert response.status_code == 200
    assert card.reference not in response.text and 'physical_cards' not in response.text
    assert client.get('/api/customers').status_code == 404


def test_new_reads_do_not_mutate_frozen_records_or_audit(operations):
    client, db, settings, _, customer, _, items, _, card, _, raw = operations
    tables = ['submission_intakes','intake_parcels','physical_cards','intake_discrepancies','intake_audit_events',
              'customer_submissions','customer_submission_entries','submission_quotes','quote_acceptances',
              'submission_deliveries','customer_addresses','customers']
    def snapshot():
        return {table: copy.deepcopy([dict(row) for row in db.execute(text(f'SELECT * FROM {table}')).mappings()]) for table in tables}
    before = snapshot()
    for path in ['/customers', '/customers/'+str(customer.id), '/customers/'+str(customer.id)+'/submissions', '/cards/'+card.reference]:
        private(client.get(BASE+path))
        assert client.post(BASE+path, json={}).status_code == 405
    assert snapshot() == before
    # Existing W5.1 finalization guards still reject a real CSRF-authorized mutation.
    headers = {'Origin':settings.auth_origin,'X-Spectra-Client':'1','X-CSRF-Token':csrf_value(raw)}
    assert client.post('/internal/intake/submissions/'+str(items[0][0].id)+'/transition',
                       json={'action':'hold','reason':'Cannot alter finalized intake'}, headers=headers).status_code == 409
    assert snapshot() == before
