import json
from datetime import timedelta
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4

import pytest
from sqlalchemy import select, func

from app.auth import digest, now
from app.customer_models import Customer, CustomerSession, CustomerToken
from app.passwords import verify_password

PASSWORD = "Collecting-cards-2026!"
NEW_PASSWORD = "Different-secure-password!"
BASE = "/api/auth"


@pytest.fixture
def auth_api(api, tmp_path):
    client, db, settings = api
    settings.auth_mail_dir = tmp_path / "private_mail"
    settings.auth_rate_limit = 100
    client.headers.update({"Origin": settings.auth_origin, "X-Spectra-Client": "1"})
    return client, db, settings


def registration(email="collector@example.com", **overrides):
    return {"email": email, "password": PASSWORD, "first_name": "Camille", "last_name": "Martin", "preferred_language": "FR", **overrides}


def mail_token(settings, purpose="verify", recipient=None):
    messages = [json.loads(p.read_text()) for p in settings.auth_mail_dir.glob("*.json")]
    messages = [m for m in messages if m["purpose"] == purpose and (recipient is None or m["recipient"] == recipient)]
    assert messages
    return parse_qs(urlsplit(messages[-1]["link"]).fragment)["token"][0]


def setup_customer(fixture, email="collector@example.com"):
    client, _, settings = fixture
    assert client.post(BASE + "/register", json=registration(email)).status_code == 202
    token = mail_token(settings, recipient=email)
    assert client.post(BASE + "/verify-email", json={"token": token}).status_code == 200
    assert client.post(BASE + "/login", json={"email": email, "password": PASSWORD}).status_code == 200
    csrf = client.get(BASE + "/csrf").json()["csrf_token"]
    return {"X-CSRF-Token": csrf}


def test_registration_hash_normalization_and_duplicate(auth_api):
    client, db, settings = auth_api
    payload = registration("  COLLECTOR@Example.COM  ")
    first = client.post(BASE + "/register", json=payload)
    assert first.status_code == 202
    customer = db.scalar(select(Customer))
    assert customer.email == "collector@example.com"
    assert customer.password_hash.startswith("scrypt$131072$8$1$")
    assert PASSWORD not in customer.password_hash
    assert verify_password(PASSWORD, customer.password_hash)
    assert customer.preferred_language == "FR"
    assert not customer.email_verified
    assert customer.created_at and customer.updated_at
    assert client.post(BASE + "/register", json=payload).json() == first.json()
    assert db.scalar(select(func.count()).select_from(Customer)) == 1
    assert len(list(settings.auth_mail_dir.glob("*.json"))) == 1
    token = mail_token(settings)
    assert db.scalar(select(CustomerToken)).token_hash == digest(token)
    assert token not in first.text and PASSWORD not in first.text


@pytest.mark.parametrize("overrides", [{"email": "wrong"}, {"password": "short"}, {"password": "x"*129}, {"first_name": " "}, {"preferred_language": "DE"}, {"customer_id": str(uuid4())}, {"last_name": "x\nname"}])
def test_registration_validation_redacts_secrets(auth_api, overrides):
    client, db, _ = auth_api
    response = client.post(BASE + "/register", json=registration(**overrides))
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert db.scalar(select(func.count()).select_from(Customer)) == 0


def test_verification_single_use_expiry_and_purpose(auth_api):
    client, db, settings = auth_api
    client.post(BASE + "/register", json=registration())
    token = mail_token(settings)
    assert client.post(BASE + "/login", json={"email": "collector@example.com", "password": PASSWORD}).status_code == 401
    assert client.post(BASE + "/password/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 400
    record = db.scalar(select(CustomerToken))
    record.expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert client.post(BASE + "/verify-email", json={"token": token}).status_code == 400
    record.expires_at = now() + timedelta(hours=1)
    db.commit()
    assert client.post(BASE + "/verify-email", json={"token": token}).status_code == 200
    assert client.post(BASE + "/verify-email", json={"token": token}).status_code == 400


def test_new_verification_invalidates_previous_link(auth_api):
    client, db, settings = auth_api
    client.post(BASE + "/register", json=registration())
    old = mail_token(settings)
    assert client.post(BASE + "/verification/request", json={"email": "collector@example.com"}).status_code == 202
    tokens = db.scalars(select(CustomerToken).order_by(CustomerToken.created_at)).all()
    assert len(tokens) == 2 and sum(t.used_at is None for t in tokens) == 1
    assert client.post(BASE + "/verify-email", json={"token": old}).status_code == 400


def test_login_cookie_session_logout(auth_api):
    client, db, _ = auth_api
    headers = setup_customer(auth_api)
    raw = client.cookies.get("spectra_session")
    record = db.scalar(select(CustomerSession))
    assert record.token_hash == digest(raw)
    assert raw != record.token_hash
    response = client.get(BASE + "/me")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "password" not in response.text and "token" not in response.text
    assert client.post(BASE + "/logout", json={}, headers=headers).status_code == 200
    assert record.revoked_at is not None
    assert client.get(BASE + "/me").status_code == 401
    client.cookies.set("spectra_session", raw)
    assert client.get(BASE + "/me").status_code == 401


def test_cookie_attributes_login_rotation_and_failure(auth_api):
    client, db, _ = auth_api
    setup_customer(auth_api)
    previous = client.cookies.get("spectra_session")
    response = client.post(BASE + "/login", json={"email": "COLLECTOR@EXAMPLE.COM", "password": PASSWORD})
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Domain=" not in cookie
    assert client.cookies.get("spectra_session") != previous
    assert db.scalar(select(CustomerSession).where(CustomerSession.token_hash == digest(previous))).revoked_at
    for email, password in [("unknown@example.com", PASSWORD), ("collector@example.com", "wrong")]:
        response = client.post(BASE + "/login", json={"email": email, "password": password})
        assert response.status_code == 401 and response.json()["detail"] == "invalid_credentials"


def test_session_expiration_and_disable(auth_api):
    client, db, _ = auth_api
    setup_customer(auth_api)
    record = db.scalar(select(CustomerSession))
    record.expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert client.get(BASE + "/me").status_code == 401
    record.expires_at = now() + timedelta(hours=1)
    customer = db.scalar(select(Customer))
    customer.status = "disabled"
    db.commit()
    assert client.get(BASE + "/me").status_code == 401
    assert client.post(BASE + "/login", json={"email": customer.email, "password": PASSWORD}).status_code == 401


def test_profile_isolation_and_language(auth_api):
    client, db, _ = auth_api
    headers = setup_customer(auth_api)
    first = db.scalar(select(Customer))
    original_id = first.id
    setup_customer(auth_api, "second@example.com")
    second_headers = {"X-CSRF-Token": client.get(BASE + "/csrf").json()["csrf_token"]}
    payload = {"first_name": "Alex", "last_name": "Collector", "preferred_language": "EN"}
    assert client.patch(BASE + "/profile", json=payload, headers=headers).status_code == 403
    assert client.patch(BASE + "/profile", json={**payload, "id": str(original_id)}, headers=second_headers).status_code == 422
    response = client.patch(BASE + "/profile", json=payload, headers=second_headers)
    assert response.status_code == 200 and response.json()["preferred_language"] == "EN"
    db.refresh(first)
    assert first.first_name == "Camille" and first.preferred_language == "FR"
    assert client.get(BASE + "/me").json()["email"] == "second@example.com"


def test_csrf_and_unauthenticated_profile(auth_api):
    client, _, settings = auth_api
    payload = registration()
    assert client.post(BASE + "/register", json=payload, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(BASE + "/register", json=payload, headers={"X-Spectra-Client": ""}).status_code == 403
    assert client.patch(BASE + "/profile", json={"first_name": "A", "last_name": "B", "preferred_language": "EN"}).status_code == 401
    setup_customer(auth_api)
    assert client.post(BASE + "/logout", json={}).status_code == 403
    assert client.post(BASE + "/logout", json={}, headers={"X-CSRF-Token": "invalid"}).status_code == 403


def test_password_reset_generic_responses_and_reuse(auth_api):
    client, db, settings = auth_api
    headers = setup_customer(auth_api)
    raw = client.cookies.get("spectra_session")
    responses = [client.post(BASE + "/password/reset/request", json={"email": e}) for e in ("unknown@example.com", "collector@example.com")]
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json() == responses[1].json()
    token = mail_token(settings, "reset")
    assert client.post(BASE + "/password/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 200
    assert client.post(BASE + "/password/reset", json={"token": token, "password": NEW_PASSWORD}).status_code == 400
    assert db.scalar(select(CustomerSession)).revoked_at
    client.cookies.set("spectra_session", raw)
    assert client.get(BASE + "/me").status_code == 401
    assert client.post(BASE + "/login", json={"email": "collector@example.com", "password": PASSWORD}).status_code == 401
    assert client.post(BASE + "/login", json={"email": "collector@example.com", "password": NEW_PASSWORD}).status_code == 200


def test_reset_expiration(auth_api):
    client, db, settings = auth_api
    setup_customer(auth_api)
    client.post(BASE + "/password/reset/request", json={"email": "collector@example.com"})
    token = mail_token(settings, "reset")
    record = db.scalar(select(CustomerToken).where(CustomerToken.token_hash == digest(token)))
    record.expires_at = now() - timedelta(seconds=1)
    db.commit()
    response = client.post(BASE + "/password/reset", json={"token": token, "password": NEW_PASSWORD})
    assert response.status_code == 400


def test_password_change_requires_current_and_revokes_all(auth_api):
    client, db, _ = auth_api
    headers = setup_customer(auth_api)
    assert client.post(BASE + "/password/change", json={"current_password": "bad", "new_password": NEW_PASSWORD}, headers=headers).status_code == 400
    assert client.post(BASE + "/password/change", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}, headers=headers).status_code == 200
    assert client.get(BASE + "/me").status_code == 401
    assert all(s.revoked_at for s in db.scalars(select(CustomerSession)).all())
    assert client.post(BASE + "/login", json={"email": "collector@example.com", "password": NEW_PASSWORD}).status_code == 200


@pytest.mark.parametrize("endpoint,payload", [("/register", registration()), ("/login", {"email": "unknown@example.com", "password": PASSWORD}), ("/verify-email", {"token": "x"*43}), ("/verification/request", {"email": "unknown@example.com"}), ("/password/reset/request", {"email": "unknown@example.com"}), ("/password/reset", {"token": "x"*43, "password": NEW_PASSWORD})])
def test_rate_limiting(auth_api, endpoint, payload):
    client, _, settings = auth_api
    settings.auth_rate_limit = 1
    assert client.post(BASE + endpoint, json=payload).status_code != 429
    response = client.post(BASE + endpoint, json=payload)
    assert response.status_code == 429 and int(response.headers["retry-after"]) >= 1


def test_private_email_and_production_cookie(auth_api):
    client, _, settings = auth_api
    setup_customer(auth_api)
    for path in ("/data/auth_mail", "/api/auth/mail", "/internal/boundary/auth_mail"):
        assert client.get(path).status_code == 404
    settings.auth_environment = "production"
    settings.auth_origin = "https://spectra.example"
    response = client.post(BASE + "/login", json={"email": "collector@example.com", "password": PASSWORD}, headers={"Origin": settings.auth_origin})
    assert response.status_code == 200
    assert "__Host-spectra_session=" in response.headers["set-cookie"] and "Secure" in response.headers["set-cookie"]


def test_mail_failure_rolls_back_registration(auth_api, monkeypatch):
    client, db, _ = auth_api
    def fail(*args):
        raise OSError("private mail path")
    monkeypatch.setattr("app.auth_email.LocalEmailDelivery.send", fail)
    response = client.post(BASE + "/register", json=registration())
    assert response.status_code == 503 and "private" not in response.text
    assert db.scalar(select(func.count()).select_from(Customer)) == 0


def test_reset_delivery_failure_is_not_an_enumeration_oracle(auth_api, monkeypatch, caplog):
    client, db, settings = auth_api
    setup_customer(auth_api)
    def fail(*args):
        raise OSError("private path or token")
    monkeypatch.setattr("app.auth_email.LocalEmailDelivery.send", fail)
    responses = [client.post(BASE + "/password/reset/request", json={"email": address}) for address in ("collector@example.com", "unknown@example.com")]
    assert all(response.status_code == 202 for response in responses)
    assert responses[0].json() == responses[1].json()
    assert "private path or token" not in caplog.text
    assert db.scalar(select(func.count()).select_from(CustomerToken).where(CustomerToken.purpose == "reset")) == 0


def test_english_registration_and_disabled_tokens(auth_api):
    client, db, settings = auth_api
    assert client.post(BASE + "/register", json=registration(preferred_language="EN")).status_code == 202
    token = mail_token(settings)
    messages = [json.loads(p.read_text()) for p in settings.auth_mail_dir.glob("*.json")]
    assert messages[0]["language"] == "EN"
    customer = db.scalar(select(Customer))
    customer.status = "disabled"
    db.commit()
    assert client.post(BASE + "/verify-email", json={"token": token}).status_code == 400
    assert client.post(BASE + "/password/reset/request", json={"email": customer.email}).status_code == 202
    assert len(list(settings.auth_mail_dir.glob("*.json"))) == 1


def test_auth_config_rejects_insecure_production():
    from pydantic import ValidationError
    from app.config import Settings
    with pytest.raises(ValidationError):
        Settings(auth_environment="production", auth_origin="http://127.0.0.1:3000")
    with pytest.raises(ValidationError):
        Settings(auth_origin="https://example.com/untrusted/path")
    with pytest.raises(ValidationError):
        Settings(auth_origin="http://public.example.com")


def test_authentication_secrets_are_absent_from_logs(auth_api, caplog):
    client, _, settings = auth_api
    setup_customer(auth_api)
    assert PASSWORD not in caplog.text
    assert mail_token(settings) not in caplog.text
    assert client.cookies.get("spectra_session") not in caplog.text


def test_invalid_unicode_and_non_ascii_csrf_fail_safely(auth_api):
    client, _, _ = auth_api
    payload = registration(password="x"*12 + "\ud800")
    response = client.post(BASE + "/register", content=json.dumps(payload, ensure_ascii=True), headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    setup_customer(auth_api)
    assert client.post(BASE + "/logout", json={}, headers={"X-CSRF-Token": b"\xff"}).status_code == 403
