"""All amounts, weights, coverage and taxes below are SYNTHETIC test data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.auth import now
from app.checkout import summary
from app.commercial_models import DispatchExpectation, PaymentObligation, VerifiedPayment
from app.logistics import (
    catalog_document, latest_selection, store_catalog, transition_catalog,
)
from app.logistics_calculator import calculate_logistics, catalog_issues, commercial_preview
from app.logistics_schemas import ColissimoCatalog, LogisticsSelection
from app.pricing_models import PricingState, QuoteAcceptance, SubmissionQuote
from app.submission_models import Submission, SubmissionEntry

AT = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def address(postal='75001'):
    return dict(recipient='SYNTHETIC TEST', line1='TEST ADDRESS', city='TEST', postal_code=postal, country='FR')


def charge(amount=100, mode='inclusive', rate=2000):
    return dict(name={'FR': 'SYNTHETIC TEST', 'EN': 'SYNTHETIC TEST'}, amount_minor=amount,
                tax={'mode': mode, 'rate_bps': rate, 'validation_reference': 'SYNTHETIC TAX'},
                source_reference='SYNTHETIC RATE', cost_basis_reference='SYNTHETIC AT COST')


def document():
    coverage = dict(direction='return', level='minimum', total_limit_minor=15000,
                    eligible_categories=['synthetic-card'], eligibility_reference='SYNTHETIC ELIGIBILITY',
                    conditions_reference='SYNTHETIC TERMS', included_in_transport=True)
    product = dict(name={'FR': 'SYNTHETIC', 'EN': 'SYNTHETIC'}, signature=False,
                   delivery_mode='contractual_inbound', direction='inbound',
                   carrier_product_code='NOT_A_REAL_CODE', eligible_categories=['synthetic-card'],
                   eligibility_reference='SYNTHETIC', weight_rule_reference='SYNTHETIC',
                   max_length_mm=400, max_width_mm=300, max_height_mm=200,
                   dimension_reference='SYNTHETIC', bands=[dict(id='test-small', origin_zone='test-zone',
                       destination_zone='test-zone', min_weight_g=1, max_weight_g=500,
                       transport=charge(101), source_reference='SYNTHETIC BAND')],
                   uninsured_allowed=True, uninsured_reference='SYNTHETIC UNINSURED')
    ret = {**deepcopy(product), 'direction': 'return', 'signature': True,
           'delivery_mode': 'domicile', 'uninsured_allowed': False, 'coverage_ids': ['test-minimum']}
    ret['bands'][0]['transport'] = charge(203)
    return dict(provenance='synthetic_test', period={'start': '2026-01-01T00:00:00Z', 'end': '2028-01-01T00:00:00Z'},
                contract_reference='SYNTHETIC CONTRACT', validation_reference='SYNTHETIC VALIDATION',
                documents=[{'reference': 'SYNTHETIC SOURCE', 'sha256': 'a' * 64}],
                future_cost_commitment_reference='SYNTHETIC FIXED COST', return_minimum_minor=15000,
                return_minimum_validation_reference='SYNTHETIC NOT A GUARANTEE', selby_address=address(),
                zones={'test-zone': {'postal_codes': ['75001'], 'validation_reference': 'SYNTHETIC ZONE'}},
                products={'test-inbound': product, 'test-return': ret}, coverages={'test-minimum': coverage},
                packing_profiles={'test-profile': {'reference': 'SYNTHETIC PROFILE', 'direction': 'return',
                    'parcel': {'weight_g': 500, 'length_mm': 100, 'width_mm': 80, 'height_mm': 50},
                    'card_count': 2, 'eligible_categories': ['synthetic-card'], 'validation_reference': 'SYNTHETIC'}})


def selection(keys=('test:1', 'test:2')):
    parcel = {'weight_g': 500, 'length_mm': 100, 'width_mm': 80, 'height_mm': 50}
    return dict(customer_origin=address(), selby_destination=address(), customer_return=address(),
                items=[dict(card_key=k, category='synthetic-card', inbound_value_minor=100, return_value_minor=100) for k in keys],
                inbound={'product_id': 'test-inbound', 'parcel': parcel},
                return_leg={'product_id': 'test-return', 'parcel': parcel,
                            'minimum_coverage_id': 'test-minimum', 'packing_profile_id': 'test-profile'})


def calc(doc=None, choice=None, at=AT):
    return calculate_logistics(ColissimoCatalog.model_validate(doc or document()),
                               LogisticsSelection.model_validate(choice or selection()),
                               at=at, expected_card_keys=['test:1', 'test:2'])


def test_deterministic_integer_calculation_included_minimum_and_cost_trace():
    first = calc()
    assert first == calc() and first['ready']
    assert first['total_minor'] == 304
    assert first['tax_total_minor'] == 51
    assert first['net_total_minor'] == 253
    assert len(first['line_items']) == 2 and len(first['included_services']) == 1
    assert first['trace'][0]['band_id'] == 'test-small'
    assert first['preparatory_return_minimum_minor'] == 15000


@pytest.mark.parametrize('weight,ready', [(1, True), (500, True), (501, False)])
def test_weight_boundaries_and_no_invented_next_band(weight, ready):
    choice = selection()
    choice['inbound']['parcel'] = {**choice['inbound']['parcel'], 'weight_g': weight}
    result = calc(choice=choice)
    assert result['ready'] is ready
    if not ready:
        assert result['total_minor'] is None and 'inbound_weight_rate_missing' in result['issues']


def test_second_band_selects_deterministically_and_gap_stays_unpriced():
    doc = document()
    second = {**deepcopy(doc['products']['test-inbound']['bands'][0]), 'id': 'test-large', 'min_weight_g': 502, 'max_weight_g': 900, 'transport': charge(301)}
    doc['products']['test-inbound']['bands'].append(second)
    choice = selection()
    choice['inbound']['parcel'] = {**choice['inbound']['parcel'], 'weight_g': 502}
    assert calc(doc, choice)['total_minor'] == 504
    choice['inbound']['parcel']['weight_g'] = 501
    assert calc(doc, choice)['total_minor'] is None


@pytest.mark.parametrize('value', [0, -1, True, 1.5, '500'])
def test_weight_rejects_invalid_or_noninteger_inputs(value):
    choice = selection()
    choice['inbound']['parcel'] = {**choice['inbound']['parcel'], 'weight_g': value}
    with pytest.raises(ValidationError):
        LogisticsSelection.model_validate(choice)


@pytest.mark.parametrize('amount', [True, 1.5, '100', -1])
def test_money_never_accepts_float_bool_string_or_negative(amount):
    doc = document()
    doc['products']['test-inbound']['bands'][0]['transport']['amount_minor'] = amount
    with pytest.raises(ValidationError):
        ColissimoCatalog.model_validate(doc)


@pytest.mark.parametrize('field', ['amount_minor', 'tax', 'source_reference', 'cost_basis_reference'])
def test_missing_price_tax_or_validation_cannot_become_zero(field):
    doc = document()
    doc['products']['test-inbound']['bands'][0]['transport'][field] = None
    result = calc(doc)
    assert not result['ready'] and result['total_minor'] is None


@pytest.mark.parametrize('mode,rate,net,tax,total', [('exclusive', 2000, 100, 20, 120), ('inclusive', 2000, 83, 17, 100), ('exempt', 0, 100, 0, 100)])
def test_existing_tax_rounding_conventions(mode, rate, net, tax, total):
    doc = document()
    doc['products']['test-inbound']['bands'][0]['transport'] = charge(100, mode, rate)
    line = calc(doc)['line_items'][0]
    assert (line['net_minor'], line['tax_minor'], line['total_minor']) == (net, tax, total)


def test_mandatory_minimum_not_inferred_from_150_euro_hypothesis():
    doc = document()
    doc['return_minimum_minor'] = None
    doc['return_minimum_validation_reference'] = None
    result = calc(doc)
    assert not result['ready'] and result['contractual_return_minimum_minor'] is None
    assert result['total_minor'] is None
    choice = selection()
    choice['return_leg']['minimum_coverage_id'] = None
    assert 'return_minimum_coverage_required' in calc(choice=choice)['issues']


def test_optional_incremental_coverage_and_effective_total_limit():
    doc = document()
    doc['coverages']['test-extra'] = {**deepcopy(doc['coverages']['test-minimum']), 'level': 'extra',
        'total_limit_minor': 30000, 'included_in_transport': False, 'premium': charge(61),
        'incremental_premium_reference': 'SYNTHETIC INCREMENTAL'}
    doc['products']['test-return']['coverage_ids'].append('test-extra')
    choice = selection()
    choice['return_leg']['extra_coverage_id'] = 'test-extra'
    assert calc(doc, choice)['total_minor'] == 365
    choice['items'][0]['return_value_minor'] = 30000
    assert 'return_declared_value_uncovered' in calc(doc, choice)['issues']  # Not 15000 + 30000.


def test_optional_inbound_insurance_is_charged_only_when_selected():
    doc = document()
    doc['coverages']['inbound-extra'] = {**deepcopy(doc['coverages']['test-minimum']), 'direction': 'inbound',
        'level': 'extra', 'included_in_transport': False, 'premium': charge(41),
        'incremental_premium_reference': 'SYNTHETIC INCREMENTAL'}
    doc['products']['test-inbound']['coverage_ids'] = ['inbound-extra']
    assert calc(doc)['total_minor'] == 304
    choice = selection()
    choice['inbound']['extra_coverage_id'] = 'inbound-extra'
    assert calc(doc, choice)['total_minor'] == 345


@pytest.mark.parametrize('change,issue', [('category', 'return_goods_ineligible'), ('postcode', 'return_metropolitan_address_required'), ('profile', 'return_packing_profile_required'), ('inventory', 'logistics_inventory_incomplete')])
def test_unknown_goods_geography_profile_inventory_fail_closed(change, issue):
    choice = selection()
    if change == 'category':
        choice['items'][0]['category'] = 'unverified-card'
    elif change == 'postcode':
        choice['customer_return']['postal_code'] = '97100'
    elif change == 'profile':
        choice['return_leg']['packing_profile_id'] = None
    else:
        choice['items'].pop()
    result = calc(choice=choice)
    assert issue in result['issues'] and result['total_minor'] is None


@pytest.mark.parametrize('change', ['overlap', 'zone-overlap', 'signature', 'foreign-zone', 'included-premium', 'period'])
def test_catalog_structure_rejects_unsafe_configuration(change):
    doc = document()
    if change == 'overlap':
        band = {**deepcopy(doc['products']['test-inbound']['bands'][0]), 'id': 'overlap', 'min_weight_g': 500}
        doc['products']['test-inbound']['bands'].append(band)
    elif change == 'zone-overlap':
        doc['zones']['duplicate'] = deepcopy(doc['zones']['test-zone'])
    elif change == 'signature':
        doc['products']['test-return']['signature'] = False
    elif change == 'foreign-zone':
        doc['zones']['test-zone']['postal_codes'] = ['97100']
    elif change == 'included-premium':
        doc['coverages']['test-minimum']['premium'] = charge()
    else:
        doc['period']['end'] = doc['period']['start']
    with pytest.raises(ValidationError):
        ColissimoCatalog.model_validate(doc)


def test_period_end_exclusive_and_draft_issues():
    assert not calc(at=datetime(2028, 1, 1, tzinfo=timezone.utc))['ready']
    assert catalog_issues(ColissimoCatalog())


def test_aggregate_preserves_grading_and_exact_tax_sum():
    grading = {'total_minor': 1200, 'net_minor': 1000, 'tax_minor': 200,
               'lines': [{'tax_mode': 'inclusive', 'tax_validation_reference': 'SYNTHETIC'}]}
    original = deepcopy(grading)
    total = commercial_preview(grading, calc())
    assert grading == original
    assert total == {'total_minor': 1504, 'net_total_minor': 1253, 'tax_total_minor': 251}


def pin_catalog(s):
    record = store_catalog(s.db, document())
    for status in ['validated', 'published_test']:
        transition_catalog(s.db, record.version, status, actor_reference='SYNTHETIC OPERATOR', reason='TEST ONLY', settings=s.settings)
    s.db.commit()
    return record


def test_migration_and_immutable_catalog_publication_history(scenario):
    s = scenario
    record = pin_catalog(s)
    assert catalog_document(record).provenance == 'synthetic_test'
    for table, where in [('logistics_catalogs', 'version=:id'), ('logistics_catalog_publications', 'catalog_version=:id')]:
        for verb in ['UPDATE', 'DELETE']:
            with pytest.raises(DBAPIError), s.db.begin_nested():
                query = f'UPDATE {table} SET created_at=created_at WHERE {where}' if verb == 'UPDATE' else f'DELETE FROM {table} WHERE {where}'
                s.db.execute(text(query), {'id': record.version})
    with pytest.raises(RuntimeError, match='destructive downgrade refused'):
        s.migration.downgrade()


def test_no_provisional_or_production_publication(scenario):
    s = scenario
    doc = document()
    doc['provenance'] = 'provisional'
    record = store_catalog(s.db, doc)
    for status in ['validated', 'published_test', 'published_production']:
        with pytest.raises(ValueError):
            transition_catalog(s.db, record.version, status, actor_reference='TEST', reason='TEST', settings=s.settings)
    good = pin_catalog(s)
    s.settings.auth_environment = 'production'
    with pytest.raises(ValueError):
        transition_catalog(s.db, good.version, 'published_test', actor_reference='TEST', reason='TEST', settings=s.settings)


def test_selection_versions_snapshots_and_incomplete_quote_are_nonpayable(scenario):
    s = scenario
    # Seed is an already accepted legacy command: make a separate new draft via API.
    path = '/api/submissions'
    item = s.client.post(path, json={}).json()
    sid = item['id']
    response = s.client.put(f'{path}/{sid}/logistics-selection', json={'version': 0, 'selection': {}})
    assert response.status_code == 200 and response.json()['version'] == 1
    from app.logistics_models import SubmissionLogisticsSelection
    first = latest_selection(s.db, UUID(sid))
    first_document, first_hash = deepcopy(first.document), first.sha256
    assert s.client.put(f'{path}/{sid}/logistics-selection', json={'version': 0, 'selection': {}}).status_code == 409
    assert s.client.put(f'{path}/{sid}/logistics-selection', json={'version': 1, 'selection': {'customer_origin': address()}}).json()['version'] == 2
    assert s.db.get(SubmissionLogisticsSelection, first.id).document == first_document
    assert s.db.get(SubmissionLogisticsSelection, first.id).sha256 == first_hash
    item_id = UUID(sid)
    current = latest_selection(s.db, item_id)
    for sql in ["UPDATE submission_logistics_selections SET document='{}' WHERE id=:id",
                'DELETE FROM submission_logistics_selections WHERE id=:id']:
        with pytest.raises(DBAPIError), s.db.begin_nested():
            s.db.execute(text(sql), {'id': current.id})
    result = summary(s.db.get(Submission, item_id), s.db, s.settings)
    assert result['final_payable_minor'] is None and result['readiness']['ready'] is False
    assert 'logistics_selection_required' not in result['readiness']['states']
    assert 'logistics_catalog_required' in result['readiness']['states']
    assert s.client.get(f'{path}/{sid}/logistics-selection').headers['cache-control'] == 'no-store'
    s.settings.logistics_enabled = False
    # Disabling entry of new C1 choices must not turn an incomplete C1 draft
    # into a legacy return-only payable order.
    result = s.client.get(f'{path}/{sid}/order-summary').json()
    assert result['logistics_schema_version'] == 1
    assert result['final_payable_minor'] is None


def test_complete_calculation_is_preview_only_and_single_obligation_unchanged(scenario):
    s = scenario
    catalog = pin_catalog(s)
    item = s.client.post('/api/submissions', json={}).json()
    sid = item['id']
    parent = s.db.get(Submission, UUID(sid))
    entry = SubmissionEntry(submission_id=parent.id, game='pokemon', card_name='SYNTHETIC', expansion='TEST', card_number='TEST', language='FR', quantity=2, processing_tier='standard', upgrade_ids=['classic'], notes='')
    s.db.add(entry)
    s.db.flush()
    choice = selection([f'{entry.id}:1', f'{entry.id}:2'])
    choice['catalog_version'] = str(catalog.version)
    assert s.client.put(f'/api/submissions/{sid}/logistics-selection', json={'version': 0, 'selection': choice}).status_code == 200
    pricing = s.db.get(SubmissionQuote, s.qid)
    if not s.db.get(PricingState, 1):
        s.db.add(PricingState(id=1, current_version=pricing.catalog_version))
    s.db.get(PricingState, 1).current_version = pricing.catalog_version
    s.db.commit()
    result = s.client.get(f'/api/submissions/{sid}/order-summary').json()
    assert result['logistics']['calculation']['ready'] is True
    assert result['logistics']['commercial_preview']['total_minor'] == result['grading']['total_minor'] + 304
    assert result['final_payable_minor'] is None and result['payment']['charging_enabled'] is False
    response = s.client.post(f'/api/submissions/{sid}/quotes', json={'version': parent.version})
    assert response.status_code == 201, response.json()
    quote = response.json()
    assert quote['snapshot']['quote_schema_version'] == 3
    assert quote['snapshot']['order_total_minor'] is None
    original_snapshot = deepcopy(quote['snapshot'])
    assert s.client.put(f'/api/submissions/{sid}/logistics-selection', json={'version': 1, 'selection': choice}).status_code == 200
    stale = s.client.get(f"/api/submissions/{sid}/quotes/{quote['id']}").json()
    assert stale['status'] == 'invalidated' and stale['snapshot'] == original_snapshot
    s.client.post(f'/api/submissions/{sid}/confirm', json={'version': parent.version})
    acceptance = s.client.post(f"/api/submissions/{sid}/quotes/{quote['id']}/accept", json={'version': parent.version, 'accept_terms': True})
    assert acceptance.status_code == 409
    assert not s.db.get(QuoteAcceptance, parent.id)
    assert s.db.scalar(select(func.count()).select_from(PaymentObligation).where(PaymentObligation.submission_id == parent.id)) == 0
    assert not s.provider.calls


def test_accepted_legacy_snapshot_unchanged_even_with_c1_enabled(scenario):
    s = scenario
    before = deepcopy(s.db.get(SubmissionQuote, s.qid).snapshot)
    result = s.client.get(f'/api/submissions/{s.sid}/order-summary')
    assert result.status_code == 200
    assert result.json()['terms_accepted'] is True
    assert result.json()['final_payable_minor'] == 2500
    assert s.db.get(SubmissionQuote, s.qid).snapshot == before
    assert s.client.put(f'/api/submissions/{s.sid}/logistics-selection', json={'version': 0, 'selection': {}}).status_code == 409
    assert not s.db.get(VerifiedPayment, s.qid)
    assert not s.db.get(DispatchExpectation, s.sid)


def test_historical_grading_only_agreement_is_never_backfilled(scenario):
    s = scenario
    parent = Submission(customer_id=s.customer_id, reference='C1-L-' + uuid4().hex,
                        status='submitted', notes='SYNTHETIC LEGACY')
    s.db.add(parent)
    s.db.flush()
    previous = s.db.get(SubmissionQuote, s.qid)
    snapshot = {'currency': 'EUR', 'development_only': False,
                'total_minor': 2000, 'historical': 'SYNTHETIC GRADING ONLY'}
    quote = SubmissionQuote(submission_id=parent.id, pricing_revision=parent.pricing_revision,
                            catalog_version=previous.catalog_version, snapshot=snapshot,
                            created_at=now() - timedelta(minutes=2), expires_at=now() + timedelta(hours=1))
    s.db.add(quote)
    s.db.flush()
    s.db.add(QuoteAcceptance(submission_id=parent.id, quote_id=quote.id, accepted_at=now()))
    s.db.commit()
    response = s.client.get(f'/api/submissions/{parent.id}/order-summary')
    assert response.status_code == 200
    assert response.json()['final_payable_minor'] is None
    assert response.json()['readiness']['states'] == ['legacy_grading_terms']
    assert s.db.get(SubmissionQuote, quote.id).snapshot == snapshot
    assert not s.db.get(PaymentObligation, quote.id)


def test_no_label_capability_and_foundation_disabled_by_default(scenario):
    s = scenario
    from app.logistics_api import router
    assert len(router.routes) == 2
    assert all(route.path.endswith('/logistics-selection') for route in router.routes)
    assert {method for route in router.routes for method in route.methods} == {'GET', 'PUT'}
    s.settings.logistics_enabled = False
    assert s.client.get(f'/api/submissions/{s.sid}/logistics-selection').status_code == 503
    assert not s.provider.calls


def test_publication_and_selection_versions_invalidate_unaccepted_context_only(scenario):
    s = scenario
    from app.checkout import context
    first = pin_catalog(s)
    parent = Submission(customer_id=s.customer_id, reference='C1-' + uuid4().hex, status='draft', notes='TEST')
    s.db.add(parent)
    s.db.flush()
    from app.logistics import save_selection
    initial = context(parent, s.db, s.settings)
    choice = LogisticsSelection(catalog_version=first.version)
    save_selection(s.db, parent.id, 0, choice)
    after_selection = context(parent, s.db, s.settings)
    assert after_selection != initial and after_selection['logistics_selection_version'] == 1
    second = pin_catalog(s)
    assert second.version != first.version
    after_publication = context(parent, s.db, s.settings)
    assert after_publication != after_selection
    assert latest_selection(s.db, parent.id).catalog_version == first.version
    assert s.db.get(SubmissionQuote, s.qid).snapshot['checkout']['final_payable_minor'] == 2500


def test_selection_database_insert_guard_after_acceptance(scenario):
    s = scenario
    from app.logistics_models import SubmissionLogisticsSelection
    from app.logistics import document_hash
    choice = LogisticsSelection().model_dump(mode='json')
    with pytest.raises(DBAPIError), s.db.begin_nested():
        s.db.add(SubmissionLogisticsSelection(submission_id=s.sid, version=1,
                                             document=choice, sha256=document_hash(choice)))
        s.db.flush()
    assert latest_selection(s.db, s.sid) is None


def test_selection_authentication_ownership_csrf_and_no_client_prices(scenario):
    s = scenario
    from app.customer_models import Customer
    customer = Customer(email=f'{uuid4().hex}@example.invalid', first_name='TEST', last_name='OTHER', password_hash='unused', email_verified=True)
    s.db.add(customer)
    s.db.flush()
    foreign = Submission(customer_id=customer.id, reference='C1-F-' + uuid4().hex, notes='TEST')
    s.db.add(foreign)
    s.db.flush()
    assert s.client.get(f'/api/submissions/{foreign.id}/logistics-selection').status_code == 404
    assert s.client.put(f'/api/submissions/{foreign.id}/logistics-selection', json={'version': 0, 'selection': {}}).status_code == 404
    item = s.client.post('/api/submissions', json={}).json()
    path = f"/api/submissions/{item['id']}/logistics-selection"
    assert s.client.put(path, json={'version': 0, 'selection': {'amount_minor': 1}}).status_code == 422
    token = s.client.headers.pop('X-CSRF-Token')
    assert s.client.put(path, json={'version': 0, 'selection': {}}).status_code == 403
    s.client.headers['X-CSRF-Token'] = token
    s.client.cookies.clear()
    assert s.client.get(path).status_code == 401


@pytest.mark.parametrize('field', ['weight_g', 'length_mm', 'width_mm', 'height_mm'])
def test_incomplete_parcel_never_has_a_total(field):
    choice = selection()
    choice['inbound']['parcel'] = {**choice['inbound']['parcel'], field: None}
    result = calc(choice=choice)
    assert not result['ready'] and result['total_minor'] is None
