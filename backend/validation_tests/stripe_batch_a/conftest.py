"""Existing schema only. No Alembic, CREATE, ALTER, DROP or outbound Stripe calls."""
import hashlib
import json
import os
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth import csrf_value, digest, now
from app.commercial import obligation_for
from app.config import Settings, get_settings
from app.customer_models import Customer, CustomerSession
from app.database import get_session
from app.main import app
from app.pricing import calculate
from app.pricing_models import PricingCatalog, QuoteAcceptance, SubmissionQuote
from app.pricing_schemas import Catalog
from app.submission_models import Submission, SubmissionEntry

ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    'customer_submissions', 'customer_submission_entries', 'submission_quotes',
    'quote_acceptances', 'payment_obligations', 'verified_payments', 'stripe_attempts',
    'stripe_evidence', 'dispatch_expectations', 'order_commercial_events',
    'customer_addresses', 'submission_deliveries',
)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def schema_hash(connection):
    statements = (
        "select table_name,column_name,data_type,is_nullable,column_default from information_schema.columns where table_schema='public' order by table_name,ordinal_position",
        "select c.relname,k.conname,pg_get_constraintdef(k.oid),k.convalidated from pg_constraint k join pg_class c on c.oid=k.conrelid join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' order by c.relname,k.conname",
        "select tablename,indexname,indexdef from pg_indexes where schemaname='public' order by tablename,indexname",
        "select c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) from pg_trigger t join pg_class c on c.oid=t.tgrelid join pg_namespace n on n.oid=c.relnamespace where not t.tgisinternal and n.nspname='public' order by c.relname,t.tgname",
        "select p.proname,pg_get_functiondef(p.oid) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.prokind='f' order by p.proname,p.oid",
    )
    return canonical_hash([[tuple(row) for row in connection.execute(text(sql))] for sql in statements])


def fingerprint(engine):
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        result = {
            'database': connection.execute(text('select current_database()')).scalar_one(),
            'read_only': connection.execute(text("select current_setting('transaction_read_only')")).scalar_one(),
            'revision': connection.execute(text('select version_num from alembic_version')).scalars().all(),
            'schema_sha256': schema_hash(connection),
            'tables': {},
        }
        for table in TABLES:
            rows = connection.execute(text(f'SELECT to_jsonb(t)::text FROM {table} t ORDER BY to_jsonb(t)::text')).scalars().all()
            result['tables'][table] = {'rows': len(rows), 'sha256': canonical_hash(rows)}
        connection.rollback()
        return result


def synthetic_settings(url):
    return Settings(
        _env_file=None, database_url=url, auth_environment='development',
        auth_origin='http://127.0.0.1:3000', stripe_enabled=True, stripe_mode='test',
        stripe_fictitious_enabled=True, stripe_secret_key='sk_test_SYNTHETIC_BATCH_A',
        stripe_webhook_secret='whsec_SYNTHETIC_BATCH_A_NOT_A_SECRET',
        stripe_account_id='acct_SYNTHETIC_BATCH_A',
    )


@pytest.fixture(scope='session')
def runtime():
    values = dotenv_values(ROOT / '.env')
    raw = os.environ.get('TEST_DATABASE_URL') or values.get('TEST_DATABASE_URL')
    development = values.get('DATABASE_URL')
    if not raw or not development:
        pytest.fail('Both local development and dedicated test database settings are required')
    target, source = make_url(raw), make_url(development)
    if target.drivername != 'postgresql+psycopg' or not target.database.endswith('_test') or target.database == source.database or target.host not in {'127.0.0.1', 'localhost', '::1'}:
        pytest.fail('Dedicated local PostgreSQL test database guard refused the target')
    test_engine = create_engine(target, pool_size=12, max_overflow=4, connect_args={'options': '-c statement_timeout=20000 -c lock_timeout=12000'})
    dev_engine = create_engine(source, connect_args={'options': '-c default_transaction_read_only=on'})
    output = ROOT / 'validation_artifacts' / 'stripe_batch_a' / os.environ['SELBY_STRIPE_BATCH_A_RUN_ID']
    output.mkdir(parents=True, exist_ok=True)
    before_dev, before_test = fingerprint(dev_engine), fingerprint(test_engine)
    if before_dev['revision'] != ['0015'] or before_test['revision'] != ['0015']:
        pytest.fail('Already-migrated schema 0015 required; no migration will be applied')
    forbidden = []
    outbound = []
    retained = []

    @event.listens_for(test_engine, 'before_cursor_execute')
    def reject_ddl(connection, cursor, statement, parameters, context, executemany):
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb not in {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SET', 'SHOW', 'SAVEPOINT', 'RELEASE', 'ROLLBACK'}:
            forbidden.append(verb)
            raise AssertionError('DDL or unsupported SQL forbidden in batch A')

    def no_network(*args, **kwargs):
        outbound.append('blocked')
        raise AssertionError('Real Stripe HTTP is forbidden in batch A')

    def no_migration(*args, **kwargs):
        forbidden.append('ALEMBIC')
        raise AssertionError('Migrations are forbidden in batch A')

    patch = pytest.MonkeyPatch()
    patch.setattr('httpx.request', no_network)
    patch.setattr('app.stripe_checkout.StripeGateway.call', no_network)
    patch.setattr('alembic.command.upgrade', no_migration)
    patch.setattr('alembic.command.downgrade', no_migration)
    settings = synthetic_settings(raw)
    result = SimpleNamespace(engine=test_engine, settings=settings, output=output, retained=retained)
    try:
        yield result
    finally:
        app.dependency_overrides.clear()
        patch.undo()
        after_dev, after_test = fingerprint(dev_engine), fingerprint(test_engine)
        report = {
            'development_before': before_dev, 'development_after': after_dev,
            'development_unchanged': before_dev == after_dev,
            'test_database': after_test['database'],
            'test_schema_before': before_test['schema_sha256'],
            'test_schema_after': after_test['schema_sha256'],
            'test_schema_unchanged': before_test['schema_sha256'] == after_test['schema_sha256'],
            'test_revision': after_test['revision'], 'forbidden_sql_or_migration_attempts': forbidden,
            'real_http_attempts': len(outbound), 'retained_synthetic_concurrency_fixtures': retained,
            'test_financial_counts_after': {key: after_test['tables'][key]['rows'] for key in TABLES[4:10]},
        }
        (output / 'isolation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        test_engine.dispose()
        dev_engine.dispose()
        assert report['development_unchanged'], 'Development data changed during the test window'
        assert report['test_schema_unchanged'], 'Test schema changed'
        assert not forbidden, 'A schema modification was attempted'
        assert not outbound, 'An outbound Stripe call was attempted'


class SimulatedStripe:
    """Shared, thread-safe provider state with no sockets and no real credentials."""
    def __init__(self, settings):
        self.settings = settings
        self.objects = {}
        self.by_key = {}
        self.successes = {}
        self.calls = []
        self.lock = Lock()
        self.account_id = settings.stripe_account_id
        self.lose_next_response = False

    def account(self):
        if self.account_id != self.settings.stripe_account_id:
            raise HTTPException(503, 'stripe_account_mismatch')

    def get(self, resource, identifier):
        with self.lock:
            return deepcopy(self.objects[(resource, identifier)])

    def call(self, method, path, data=None, key=None):
        with self.lock:
            self.calls.append((method, path, key))
            if method == 'GET' and path.startswith('events?'):
                return {'data': deepcopy(list(self.successes.values())), 'has_more': False}
            if method != 'POST' or path != 'checkout/sessions' or not key:
                raise AssertionError('Unexpected simulated provider operation')
            if key not in self.by_key:
                meta = {name[9:-1]: value for name, value in data.items() if name.startswith('metadata[')}
                session_id = 'cs_test_BATCHA_' + meta['attempt_id'].replace('-', '')
                obj = {
                    'id': session_id, 'livemode': False, 'mode': 'payment', 'currency': 'eur',
                    'amount_total': int(data['line_items[0][price_data][unit_amount]']),
                    'client_reference_id': meta['attempt_id'], 'metadata': meta,
                    'status': 'open', 'payment_status': 'unpaid', 'payment_intent': None,
                    'url': 'https://checkout.stripe.com/c/pay/SYNTHETIC_BATCH_A_' + meta['attempt_id'],
                }
                self.by_key[key] = session_id
                self.objects[('checkout/sessions', session_id)] = obj
            result = deepcopy(self.objects[('checkout/sessions', self.by_key[key])])
            if self.lose_next_response:
                self.lose_next_response = False
                raise HTTPException(503, 'synthetic_response_lost')
            return result

    def settle(self, session_id):
        import time
        with self.lock:
            obj = self.objects[('checkout/sessions', session_id)]
            identity = obj['metadata']['attempt_id'].replace('-', '')
            pi_id, charge_id = 'pi_BATCHA_' + identity, 'ch_BATCHA_' + identity
            obj.update(status='complete', payment_status='paid', payment_intent=pi_id)
            pi = {'id': pi_id, 'livemode': False, 'metadata': deepcopy(obj['metadata']),
                  'currency': 'eur', 'amount': obj['amount_total'], 'amount_received': obj['amount_total'],
                  'status': 'succeeded', 'latest_charge': charge_id}
            charge = {'id': charge_id, 'livemode': False, 'payment_intent': pi_id,
                      'amount': obj['amount_total'], 'currency': 'eur', 'paid': True, 'captured': True,
                      'refunded': False, 'amount_refunded': 0, 'disputed': False}
            self.objects[('payment_intents', pi_id)] = pi
            self.objects[('charges', charge_id)] = charge
            first = {'id': 'evt_BATCHA_' + uuid4().hex, 'livemode': False, 'type': 'payment_intent.succeeded',
                     'created': int(time.time()), 'data': {'object': deepcopy(pi)}}
            second = {'id': 'evt_BATCHA_' + uuid4().hex, 'livemode': False, 'type': 'checkout.session.completed',
                      'created': first['created'], 'data': {'object': deepcopy(obj)}}
            self.successes[pi_id] = deepcopy(first)
            return first, second


def seed(db, run_id):
    customer = Customer(email=f'batch-a-{uuid4().hex}@example.invalid', password_hash='unused',
                        first_name='SYNTHETIC', last_name='BATCH A', email_verified=True)
    document = json.loads((ROOT / 'pricing' / 'fictitious-stripe-test-pricing.json').read_text(encoding='utf-8'))
    catalog = Catalog.model_validate(document)
    record = PricingCatalog(document=catalog.model_dump())
    db.add_all([customer, record])
    db.flush()
    order = Submission(customer_id=customer.id, reference='SP-' + uuid4().hex.upper(), status='submitted',
                       notes='SYNTHETIC BATCH A ' + run_id, confirmed_at=now() - timedelta(minutes=3))
    db.add(order)
    db.flush()
    entry = SubmissionEntry(submission_id=order.id, game='pokemon', card_name='SYNTHETIC BATCH A',
                            expansion='TEST', card_number='TEST', language='FR', quantity=2,
                            processing_tier='standard', upgrade_ids=['classic'], notes='No physical cards')
    db.add(entry)
    db.flush()
    snapshot = calculate(catalog, [entry])
    snapshot['checkout'] = {'stripe_test_only': True, 'currency': 'EUR', 'quantity': 2,
                            'readiness': {'ready': True, 'states': ['ready_for_checkout']},
                            'grading': deepcopy(snapshot), 'shipping': {'charge_minor': 500},
                            'tax_total_minor': 0, 'net_total_minor': 2500, 'final_payable_minor': 2500}
    snapshot['order_total_minor'] = 2500
    quote = SubmissionQuote(submission_id=order.id, pricing_revision=order.pricing_revision,
                            catalog_version=record.version, snapshot=snapshot,
                            created_at=now() - timedelta(minutes=3), expires_at=now() + timedelta(hours=1))
    db.add(quote)
    db.flush()
    accepted_at = now() - timedelta(minutes=2)
    db.add(QuoteAcceptance(submission_id=order.id, quote_id=quote.id, accepted_at=accepted_at))
    obligation_for(db, quote, accepted_at)
    token = 'BATCHA_' + uuid4().hex + 'TEST'  # Same 43-character format as real session tokens.
    db.add(CustomerSession(customer_id=customer.id, token_hash=digest(token), expires_at=now() + timedelta(hours=1)))
    db.flush()
    return SimpleNamespace(sid=order.id, qid=quote.id, customer_id=customer.id, token=token)


def login(client, settings, fixture):
    client.cookies.set('spectra_session', fixture.token)
    client.headers.update({'Origin': settings.auth_origin, 'X-Spectra-Client': '1', 'X-CSRF-Token': csrf_value(fixture.token)})


@pytest.fixture
def scenario(runtime, monkeypatch):
    with runtime.engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as db:
            fixture = seed(db, os.environ['SELBY_STRIPE_BATCH_A_RUN_ID'])
            db.commit()
            settings = synthetic_settings(runtime.settings.database_url)
            provider = SimulatedStripe(settings)
            app.dependency_overrides[get_session] = lambda: db
            app.dependency_overrides[get_settings] = lambda: settings
            monkeypatch.setattr('app.stripe_api.StripeGateway', lambda settings: provider)
            try:
                with TestClient(app) as client:
                    login(client, settings, fixture)
                    yield SimpleNamespace(**vars(fixture), db=db, client=client, settings=settings, provider=provider)
            finally:
                app.dependency_overrides.clear()
                transaction.rollback()


@pytest.fixture
def concurrent_scenario(runtime, monkeypatch):
    settings = synthetic_settings(runtime.settings.database_url)
    provider = SimulatedStripe(settings)
    with Session(runtime.engine) as db:
        fixture = seed(db, os.environ['SELBY_STRIPE_BATCH_A_RUN_ID'])
        db.commit()
    runtime.retained.append({'submission_id': str(fixture.sid), 'quote_id': str(fixture.qid),
                             'reason': 'Independent PostgreSQL commits required for concurrency; immutable synthetic evidence retained in test database only'})

    def session():
        with Session(runtime.engine) as db:
            yield db

    app.dependency_overrides[get_session] = session
    app.dependency_overrides[get_settings] = lambda: settings
    monkeypatch.setattr('app.stripe_api.StripeGateway', lambda settings: provider)
    try:
        yield SimpleNamespace(**vars(fixture), engine=runtime.engine, settings=settings, provider=provider)
    finally:
        app.dependency_overrides.clear()
