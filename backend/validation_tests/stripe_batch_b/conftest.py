"""Batch B uses the existing test schema and rolls back EVERY simulated case."""
import importlib.util
import json
import os
import subprocess
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth import digest, now
from app.commercial import obligation_for
from app.config import get_settings
from app.customer_models import Customer, CustomerSession
from app.database import get_session
from app.main import app
from app.pricing import calculate
from app.pricing_models import PricingCatalog, QuoteAcceptance, SubmissionQuote
from app.pricing_schemas import Catalog
from app.submission_models import Submission, SubmissionEntry

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('selby_batch_a_shared', ROOT / 'validation_tests/stripe_batch_a/conftest.py')
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)  # Helpers only: none of batch A's pytest fixtures are invoked.


def source_fingerprint():
    files = sorted((ROOT / 'app').glob('*.py')) + sorted((ROOT.parent / 'frontend/src').rglob('*.ts')) + sorted((ROOT.parent / 'frontend/src').rglob('*.tsx')) + sorted((ROOT.parent / 'frontend/src').rglob('*.css'))
    return {str(path.relative_to(ROOT.parent)): A.canonical_hash(path.read_bytes().hex()) for path in files}


def full_fingerprint(engine):
    with engine.connect() as connection:
        connection.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY'))
        tables = connection.execute(text("select tablename from pg_tables where schemaname='public' order by tablename")).scalars().all()
        result = {'database': connection.execute(text('select current_database()')).scalar_one(),
                  'revision': connection.execute(text('select version_num from alembic_version')).scalars().all(),
                  'schema_sha256': A.schema_hash(connection), 'tables': {}}
        for table in tables:
            quoted = connection.dialect.identifier_preparer.quote(table)
            rows = connection.execute(text(f'SELECT to_jsonb(t)::text FROM public.{quoted} t ORDER BY to_jsonb(t)::text')).scalars().all()
            result['tables'][table] = {'rows': len(rows), 'sha256': A.canonical_hash(rows)}
        connection.rollback()
        return result


def ui_decision(state):
    """Execute the actual V1 helper code, not a Python reconstruction of its rules."""
    commercial = (ROOT.parent / 'frontend/src/lib/commercial.ts').as_uri()
    flow = (ROOT.parent / 'frontend/src/lib/order-flow.ts').as_uri()
    script = "const c=await import(process.argv[1]);const f=await import(process.argv[2]);let raw='';for await(const chunk of process.stdin)raw+=chunk;const state=JSON.parse(raw);console.log(JSON.stringify({canDeclareShipment:c.canDeclareShipment(state),nextAction:f.nextAction(state),isTracking:f.isTracking({commercial:state}),canStartCheckout:c.canStartCheckout(state),statusFR:c.paymentStatusLabel(state,'FR'),statusEN:c.paymentStatusLabel(state,'EN')}));"
    result = subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', script, commercial, flow],
                            input=json.dumps(state), capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(result.stdout)


@pytest.fixture(scope='session')
def runtime():
    values = dotenv_values(ROOT / '.env')
    raw = os.environ.get('TEST_DATABASE_URL') or values.get('TEST_DATABASE_URL')
    development = values.get('DATABASE_URL')
    if not raw or not development:
        pytest.fail('Dedicated local test and development database configuration required')
    target, source = make_url(raw), make_url(development)
    if target.drivername != 'postgresql+psycopg' or not target.database or not target.database.endswith('_test') or target.database == source.database or target.host not in {'localhost', '127.0.0.1', '::1'}:
        pytest.fail('Unsafe test database refused')
    engine = create_engine(target, connect_args={'options': '-c statement_timeout=20000 -c lock_timeout=10000'})
    dev = create_engine(source, connect_args={'options': '-c default_transaction_read_only=on'})
    output = ROOT / 'validation_artifacts/stripe_batch_b' / os.environ['SELBY_STRIPE_BATCH_B_RUN_ID']
    output.mkdir(parents=True, exist_ok=True)
    before_dev, before_test, before_source = full_fingerprint(dev), full_fingerprint(engine), source_fingerprint()
    if before_dev['revision'] != ['0015'] or before_test['revision'] != ['0015']:
        pytest.fail('Schema 0015 must already exist; migrations are forbidden')
    forbidden, outbound, findings, frames = [], [], [], []

    @event.listens_for(engine, 'before_cursor_execute')
    def sql_guard(connection, cursor, statement, parameters, context, executemany):
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb not in {'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'SET', 'SHOW', 'SAVEPOINT', 'RELEASE', 'ROLLBACK'}:
            forbidden.append(verb)
            raise AssertionError('DDL/purge forbidden in isolated batch B')

    def no_network(*args, **kwargs):
        outbound.append('blocked')
        raise AssertionError('Real Stripe HTTP forbidden in isolated batch B')

    def no_migration(*args, **kwargs):
        forbidden.append('ALEMBIC')
        raise AssertionError('Migrations forbidden in isolated batch B')

    patch = pytest.MonkeyPatch()
    patch.setattr('httpx.request', no_network)
    patch.setattr('app.stripe_checkout.StripeGateway.call', no_network)
    patch.setattr('alembic.command.upgrade', no_migration)
    patch.setattr('alembic.command.downgrade', no_migration)
    value = SimpleNamespace(engine=engine, settings=A.synthetic_settings(raw), output=output, findings=findings, frames=frames)
    try:
        yield value
    finally:
        app.dependency_overrides.clear()
        after_dev, after_test, after_source = full_fingerprint(dev), full_fingerprint(engine), source_fingerprint()
        report = {'development_before': before_dev, 'development_after': after_dev,
                  'test_before': before_test, 'test_after': after_test,
                  'development_unchanged': before_dev == after_dev, 'test_data_and_schema_unchanged': before_test == after_test,
                  'application_sources_unchanged': before_source == after_source,
                  'source_hashes_before': before_source, 'source_hashes_after': after_source,
                  'forbidden_sql_or_migration_attempts': forbidden, 'real_stripe_http_attempts': len(outbound),
                  'all_fixtures_rolled_back': True}
        (output / 'isolation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        (output / 'findings.json').write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding='utf-8')
        (output / 'ui-cases.json').write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding='utf-8')
        patch.undo()
        engine.dispose()
        dev.dispose()
        assert report['development_unchanged'], 'Development changed during validation'
        assert report['test_data_and_schema_unchanged'], 'Rollback did not preserve existing test data/schema'
        assert report['application_sources_unchanged'], 'Application source changed during validation'
        assert not forbidden and not outbound


class SimulatedStripeB(A.SimulatedStripe):
    def __init__(self, settings):
        super().__init__(settings)
        self.fail_cancel_response_once = False

    def call(self, method, path, data=None, key=None):
        if method == 'POST' and path.startswith('payment_intents/') and path.endswith('/cancel'):
            with self.lock:
                self.calls.append((method, path, key))
                pi = self.objects[('payment_intents', path.split('/')[1])]
                pi['status'] = 'canceled'
                if self.fail_cancel_response_once:
                    self.fail_cancel_response_once = False
                    raise HTTPException(503, 'synthetic_cancel_response_lost')
                return deepcopy(pi)
        return super().call(method, path, data, key)


def seed(db, run_id):
    customer = Customer(email=f'batch-b-{uuid4().hex}@example.invalid', password_hash='unused',
                        first_name='SYNTHETIC', last_name='BATCH B', email_verified=True)
    catalog = Catalog.model_validate(json.loads((ROOT / 'pricing/fictitious-stripe-test-pricing.json').read_text(encoding='utf-8')))
    record = PricingCatalog(document=catalog.model_dump())
    db.add_all([customer, record])
    db.flush()
    order = Submission(customer_id=customer.id, reference='SP-' + uuid4().hex.upper(), status='submitted',
                       notes='SYNTHETIC BATCH B ' + run_id, confirmed_at=now() - timedelta(minutes=3))
    db.add(order)
    db.flush()
    entry = SubmissionEntry(submission_id=order.id, game='pokemon', card_name='SYNTHETIC BATCH B', expansion='TEST',
                            card_number='TEST', language='FR', quantity=2, processing_tier='standard', upgrade_ids=['classic'], notes='')
    db.add(entry)
    db.flush()
    snapshot = calculate(catalog, [entry])
    address_id = str(uuid4())
    snapshot['checkout'] = {
        'stripe_test_only': True, 'currency': 'EUR', 'quantity': 2, 'submission_reference': order.reference,
        'commercial_terms_version': catalog.commercial_terms_version, 'grading': deepcopy(snapshot),
        'return_address': {'id': address_id, 'version': 1, 'recipient': 'TEST', 'line1': 'TEST', 'line2': '', 'postal_code': '75001', 'city': 'TEST', 'country': 'FR', 'phone': '', 'instructions': ''},
        'delivery': {'version': 1, 'address_id': address_id, 'declared_value_minor': 10000, 'service_id': 'test-return', 'parcel': {}},
        'shipping': {'status': 'configured', 'charge_minor': 500, 'service': {'name': {'FR': 'Retour TEST', 'EN': 'TEST return'}, 'coverage': {'FR': 'Simulation', 'EN': 'Simulation'}, 'exclusions': {'FR': 'Aucun transport', 'EN': 'No transport'}}},
        'available_services': [], 'readiness': {'ready': True, 'states': ['ready_for_checkout']},
        'inbound_receiving_address': None, 'tax_total_minor': 0, 'net_total_minor': 2500, 'final_payable_minor': 2500,
    }
    snapshot['order_total_minor'] = 2500
    quote = SubmissionQuote(submission_id=order.id, pricing_revision=order.pricing_revision, catalog_version=record.version,
                            snapshot=snapshot, created_at=now() - timedelta(minutes=3), expires_at=now() + timedelta(hours=1))
    db.add(quote)
    db.flush()
    accepted_at = now() - timedelta(minutes=2)
    db.add(QuoteAcceptance(submission_id=order.id, quote_id=quote.id, accepted_at=accepted_at))
    obligation_for(db, quote, accepted_at)
    token = 'BATCHB_' + uuid4().hex + 'TEST'
    db.add(CustomerSession(customer_id=customer.id, token_hash=digest(token), expires_at=now() + timedelta(hours=1)))
    db.flush()
    return SimpleNamespace(sid=order.id, qid=quote.id, customer_id=customer.id, token=token)


@pytest.fixture
def scenario(runtime, monkeypatch):
    with runtime.engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as db:
            value = seed(db, os.environ['SELBY_STRIPE_BATCH_B_RUN_ID'])
            db.commit()
            settings = A.synthetic_settings(runtime.settings.database_url)
            provider = SimulatedStripeB(settings)
            app.dependency_overrides[get_session] = lambda: db
            app.dependency_overrides[get_settings] = lambda: settings
            monkeypatch.setattr('app.stripe_api.StripeGateway', lambda settings: provider)
            try:
                with TestClient(app) as client:
                    A.login(client, settings, value)
                    yield SimpleNamespace(**vars(value), db=db, client=client, settings=settings, provider=provider)
            finally:
                app.dependency_overrides.clear()
                transaction.rollback()
