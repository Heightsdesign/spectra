"""C1 migration exercised transactionally on existing local *_test only.

Every DDL/data change, including the revision marker, is rolled back. Development
is read-only and fingerprinted. Real provider transports fail immediately.
"""
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from dotenv import dotenv_values
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_session
from app.main import app

ROOT = Path(__file__).resolve().parents[2]


def module_at(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = module_at('c1_shared_batch_b', ROOT / 'validation_tests/stripe_batch_b/conftest.py')


@pytest.fixture(scope='session')
def migrated():
    values = dotenv_values(ROOT / '.env')
    raw = os.environ.get('TEST_DATABASE_URL') or values.get('TEST_DATABASE_URL')
    target, source = make_url(raw), make_url(values['DATABASE_URL'])
    assert target.drivername == 'postgresql+psycopg' and target.database.endswith('_test')
    assert target.database != source.database and target.host in {'localhost', '127.0.0.1', '::1'}
    engine = create_engine(target, connect_args={'options': '-c statement_timeout=20000 -c lock_timeout=10000'})
    dev = create_engine(source, connect_args={'options': '-c default_transaction_read_only=on'})
    before, before_dev = B.full_fingerprint(engine), B.full_fingerprint(dev)
    assert before['revision'] == before_dev['revision'] == ['0015']
    output = ROOT / 'validation_artifacts/logistics_c1' / ('run_' + uuid4().hex)
    output.mkdir(parents=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                migration = module_at('c1_migration', ROOT / 'alembic/versions/0016_logistics_foundation.py')
                migration.op = Operations(MigrationContext.configure(connection))
                migration.upgrade()
                connection.execute(text("UPDATE alembic_version SET version_num='0016' WHERE version_num='0015'"))
                assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == '0016'
                yield SimpleNamespace(connection=connection, raw=raw, output=output, migration=migration)
            finally:
                transaction.rollback()
    finally:
        after, after_dev = B.full_fingerprint(engine), B.full_fingerprint(dev)
        proof = {'test_before': before, 'test_after': after,
                 'development_before': before_dev, 'development_after': after_dev,
                 'test_data_schema_and_revision_unchanged': before == after,
                 'development_unchanged': before_dev == after_dev,
                 'migration_0016_exercised_in_rolled_back_transaction': True}
        (output / 'isolation.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
        engine.dispose()
        dev.dispose()
        assert proof['test_data_schema_and_revision_unchanged'] and proof['development_unchanged']
        print('C1 isolation evidence: ' + str(output))


@pytest.fixture(autouse=True)
def no_provider_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('C1 tests forbid real provider I/O and label purchases')
    monkeypatch.setattr('httpx.request', forbidden)
    monkeypatch.setattr('app.stripe_checkout.StripeGateway.call', forbidden)
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


@pytest.fixture
def scenario(migrated, monkeypatch):
    with Session(bind=migrated.connection, join_transaction_mode='create_savepoint') as db:
        outer = migrated.connection.begin_nested()
        try:
            identity = B.seed(db, 'COLISSIMO_C1_SYNTHETIC')
            db.commit()
            settings = B.A.synthetic_settings(migrated.raw)
            settings.logistics_enabled = True
            provider = B.SimulatedStripeB(settings)
            app.dependency_overrides[get_session] = lambda: db
            app.dependency_overrides[get_settings] = lambda: settings
            monkeypatch.setattr('app.stripe_api.StripeGateway', lambda settings: provider)
            with TestClient(app) as client:
                B.A.login(client, settings, identity)
                yield SimpleNamespace(**vars(identity), db=db, client=client, settings=settings,
                                      provider=provider, migration=migrated.migration)
        finally:
            app.dependency_overrides.clear()
            db.close()
            outer.rollback()
