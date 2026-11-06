"""Development fixtures use production auth primitives, never production targets."""

from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.auth import now
from app.config import Settings
from app.customer_models import Customer, CustomerSession
from app.intake_models import StaffMembership
from app.local_test_accounts import (
    SPECS,
    SetupError,
    credentials_text,
    seed,
    validate_target,
    verify_server,
)
from app.passwords import hash_password, verify_password


@pytest.mark.parametrize(
    "metadata",
    [
        ("spectra", "192.0.2.1", False),
        ("wrong_database", "127.0.0.1", False),
        ("spectra", "127.0.0.1", True),
        ("spectra", None, False),
    ],
)
def test_refuses_unexpected_server_before_creating_records(metadata):
    db = SimpleNamespace(
        execute=lambda statement: SimpleNamespace(one=lambda: metadata)
    )
    with pytest.raises(SetupError):
        verify_server(db, "spectra")


def target(api):
    _, db, settings = api
    settings.database_url = db.bind.engine.url.render_as_string(hide_password=False)
    return settings, db.bind.engine.url.database


@pytest.mark.parametrize(
    "url,environment,origin",
    [
        (
            "postgresql+psycopg://localhost/spectra",
            "production",
            "https://portal.example",
        ),
        (
            "postgresql+psycopg://remote.example/spectra",
            "development",
            "http://127.0.0.1:3000",
        ),
        (
            "postgresql+psycopg://localhost/production",
            "development",
            "http://127.0.0.1:3000",
        ),
        (
            "postgresql+psycopg://localhost/spectra?hostaddr=192.0.2.1",
            "development",
            "http://127.0.0.1:3000",
        ),
        (
            "postgresql+psycopg://localhost/spectra",
            "development",
            "https://portal.example",
        ),
    ],
)
def test_refuses_unsafe_configuration(url, environment, origin):
    settings = Settings(
        database_url=url, auth_environment=environment, auth_origin=origin
    )
    with pytest.raises(SetupError):
        validate_target(settings, "spectra")


def test_seed_five_unique_verified_accounts_login_roles_and_idempotency(
    api, monkeypatch
):
    client, db, _ = api
    settings, name = target(api)
    monkeypatch.setattr(
        "app.auth.send_token", lambda *args: pytest.fail("Seeder must not send email")
    )
    results = seed(db, settings, name)
    db.commit()
    assert len(results) == 5 and len({r.password for r in results}) == 5
    assert all(
        r.password and len(r.password) >= 32 and r.password not in repr(r)
        for r in results
    )
    before = {
        c.email: (c.id, c.password_hash, c.email_verified, c.status)
        for c in db.scalars(select(Customer))
    }
    for result in results:
        row = db.scalar(select(Customer).where(Customer.email == result.email))
        assert row.email_verified and verify_password(
            result.password, row.password_hash
        )
        assert (
            row.password_hash.startswith("scrypt$")
            and result.password not in row.password_hash
        )
        response = client.post(
            "/api/auth/login",
            json={"email": result.email, "password": result.password},
            headers={"Origin": settings.auth_origin, "X-Spectra-Client": "1"},
        )
        assert response.status_code == 200
        assert client.get("/api/auth/me").json()["email"] == result.email
        staff = client.get("/internal/intake/me")
        if result.role:
            assert staff.status_code == 200 and staff.json()["role"] == result.role
        else:
            assert staff.status_code == 403
        client.cookies.clear()
    rerun = seed(db, settings, name)
    assert all(r.action == "preserved" and r.password is None for r in rerun)
    assert {
        c.email: (c.id, c.password_hash, c.email_verified, c.status)
        for c in db.scalars(select(Customer))
    } == before
    assert len(list(db.scalars(select(StaffMembership)))) == 2
    document = credentials_text(results, settings.auth_origin)
    assert all(r.password in document for r in results)
    assert "LOCAL DEVELOPMENT ONLY" in document


def test_existing_conflicting_account_is_not_reset_or_promoted(api):
    _, db, _ = api
    settings, name = target(api)
    existing = Customer(
        email=SPECS[0][2],
        password_hash=hash_password("Synthetic-existing-test-password"),
        first_name="Existing",
        last_name="Fixture",
        email_verified=False,
        status="disabled",
    )
    db.add(existing)
    db.flush()
    original = (
        existing.id,
        existing.password_hash,
        existing.email_verified,
        existing.status,
    )
    results = seed(db, settings, name)
    assert results[0].action == "preserved" and results[0].password is None
    db.refresh(existing)
    assert (
        existing.id,
        existing.password_hash,
        existing.email_verified,
        existing.status,
    ) == original
    assert db.get(StaffMembership, existing.id) is None
    with pytest.raises(SetupError, match="Refusing reset"):
        seed(db, settings, name, reset_email=existing.email)


def test_explicit_owned_reset_only_changes_target_password_and_revokes_sessions(api):
    _, db, _ = api
    settings, name = target(api)
    first = seed(db, settings, name)
    db.commit()
    account = db.scalar(select(Customer).where(Customer.email == SPECS[3][2]))
    old = {c.email: c.password_hash for c in db.scalars(select(Customer))}
    session = CustomerSession(
        customer_id=account.id,
        token_hash=uuid4().hex + uuid4().hex,
        expires_at=now() + timedelta(hours=1),
    )
    db.add(session)
    db.commit()
    changed = seed(db, settings, name, reset_email=account.email)
    db.commit()
    current = next(r for r in changed if r.email == account.email)
    assert current.action == "reset" and verify_password(
        current.password, account.password_hash
    )
    assert not verify_password(
        next(r.password for r in first if r.email == account.email),
        account.password_hash,
    )
    assert session.revoked_at is not None
    assert all(
        c.password_hash == old[c.email]
        for c in db.scalars(select(Customer))
        if c.email != account.email
    )


def test_normal_registration_still_requires_verification(api, tmp_path):
    client, db, settings = api
    settings.auth_mail_dir = tmp_path / "private_mail"
    headers = {"Origin": settings.auth_origin, "X-Spectra-Client": "1"}
    payload = {
        "email": "ordinary-fixture@example.invalid",
        "password": "Synthetic-normal-registration-pass",
        "first_name": "Ordinary",
        "last_name": "Fixture",
    }
    assert (
        client.post("/api/auth/register", json=payload, headers=headers).status_code
        == 202
    )
    customer = db.scalar(select(Customer).where(Customer.email == payload["email"]))
    assert customer and not customer.email_verified
    assert (
        client.post(
            "/api/auth/login",
            json={k: payload[k] for k in ("email", "password")},
            headers=headers,
        ).status_code
        == 401
    )
