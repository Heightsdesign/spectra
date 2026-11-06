"""Exercise existing GET routes/auth with an isolated session double; no DB migrations."""

import secrets
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.auth import digest, now
from app.config import Settings, get_settings
from app.database import get_session
from app.intake_models import Intake, StaffMembership
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def preview_contract():
    token = secrets.token_urlsafe(32)
    actor = SimpleNamespace(id=uuid4(), status='active', email_verified=True,
                            preferred_language='EN', first_name='Synthetic', last_name='Operator')
    session = SimpleNamespace(token_hash=digest(token), customer_id=actor.id,
                              expires_at=now() + timedelta(hours=1), revoked_at=None)
    submission = SimpleNamespace(id=uuid4(), reference='SP-' + uuid4().hex.upper(),
                                 customer_id=actor.id, confirmed_at=now())
    state = SimpleNamespace(role='operator')
    db = MagicMock()

    def scalar(statement):
        sql = str(statement)
        if 'FROM customer_sessions' in sql:
            return session
        if 'FROM customers' in sql:
            return actor
        if 'FROM customer_submissions' in sql:
            return submission
        if 'sum(' in sql:
            return 3
        if 'count(' in sql:
            return 0
        raise AssertionError('Unexpected SQL shape')

    def scalars(statement):
        if 'FROM customer_submissions' in str(statement):
            return [submission]
        return []

    def get(model, key):
        if model is StaffMembership:
            return state if state.role else None
        if model is Intake:
            return None
        return None

    db.scalar.side_effect = scalar
    db.scalars.side_effect = scalars
    db.get.side_effect = get
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_session] = lambda: db
    app.dependency_overrides[get_settings] = lambda: Settings()
    try:
        with TestClient(app) as client:
            client.cookies.set('spectra_session', token)
            yield client, db, state, session, submission
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_existing_preview_get_contract_and_no_business_writes(preview_contract):
    client, db, _, _, submission = preview_contract
    assert client.get('/internal/intake/me').json()['role'] == 'operator'
    rows = client.get('/internal/intake/submissions?search=SP-&offset=0&limit=50')
    assert rows.status_code == 200
    assert rows.json()[0]['declared_quantity'] == 3
    assert rows.json()[0]['received_quantity'] == 0
    detail = client.get(f'/internal/intake/submissions/{submission.id}')
    assert detail.status_code == 200
    assert detail.json()['status'] == 'awaiting_receipt'
    assert detail.json()['payment_status'] == 'not_implemented'
    assert all(detail.json()[key] == [] for key in ('entries', 'cards', 'parcels', 'discrepancies'))
    assert 'no-store' in detail.headers['cache-control']
    for method in ('commit', 'add', 'delete', 'execute', 'flush'):
        getattr(db, method).assert_not_called()


@pytest.mark.parametrize('failure,code', [('expired', 401), ('revoked', 401),
                                         ('disabled', 401), ('nonstaff', 403)])
def test_existing_authorization_failures(preview_contract, failure, code):
    client, db, state, session, submission = preview_contract
    if failure == 'expired':
        session.expires_at = now() - timedelta(seconds=1)
    elif failure == 'revoked':
        session.revoked_at = now()
    elif failure == 'disabled':
        # The real authenticated() helper rejects the account before membership.
        original = db.scalar.side_effect
        def disabled(statement):
            value = original(statement)
            if 'FROM customers' in str(statement):
                value.status = 'disabled'
            return value
        db.scalar.side_effect = disabled
    else:
        state.role = None
    for path in ('/internal/intake/me', '/internal/intake/submissions',
                 f'/internal/intake/submissions/{submission.id}'):
        assert client.get(path).status_code == code
    db.commit.assert_not_called()
