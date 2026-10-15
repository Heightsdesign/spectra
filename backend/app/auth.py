"""Customer authentication only; existing card/review routes are unchanged."""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.auth_email import get_email_delivery
from app.auth_schemas import Registration, Login, EmailRequest, TokenRequest, Reset, Profile, PasswordChange
from app.cards import Db, Config
from app.customer_models import Customer, CustomerSession, CustomerToken, AuthRateBucket
from app.passwords import hash_password, verify_password, DUMMY_HASH


def now():
    return datetime.now(timezone.utc)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def cookie_name(settings):
    return "__Host-spectra_session" if settings.auth_environment == "production" else "spectra_session"


def csrf_value(raw):
    return digest("spectra-csrf:" + raw)


def write_guard(request: Request, settings: Config):
    if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
        if request.headers.get("origin") != settings.auth_origin or request.headers.get("x-spectra-client") != "1":
            raise HTTPException(403, "csrf_failed")
        if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
            raise HTTPException(415, "json_required")


router = APIRouter(prefix="/api/auth", dependencies=[Depends(write_guard)])


def throttle(request, db, settings, scope, email=None):
    timestamp = now().timestamp()
    bucket = int(timestamp // settings.auth_rate_window_seconds)
    expiry = datetime.fromtimestamp((bucket + 1) * settings.auth_rate_window_seconds, timezone.utc)
    subjects = ["ip:" + (request.client.host if request.client else "unknown")]
    if email:
        subjects.append("email:" + email)
    exceeded = False
    for subject in subjects:
        key = digest(f"{scope}:{subject}:{bucket}")
        statement = insert(AuthRateBucket).values(key=key, count=1, expires_at=expiry)
        count = db.scalar(statement.on_conflict_do_update(index_elements=[AuthRateBucket.key], set_={"count": AuthRateBucket.count + 1}).returning(AuthRateBucket.count))
        exceeded |= count > settings.auth_rate_limit
    db.commit()  # Failed login/token attempts must still consume their budget.
    if exceeded:
        raise HTTPException(429, "rate_limited", headers={"Retry-After": str(max(1, int(expiry.timestamp() - timestamp)))})


def public_customer(customer):
    return {"id": str(customer.id), "email": customer.email, "first_name": customer.first_name,
            "last_name": customer.last_name, "preferred_language": customer.preferred_language,
            "email_verified": customer.email_verified, "created_at": customer.created_at,
            "updated_at": customer.updated_at}


def send_token(customer, purpose, db, settings):
    # Caller holds the customer lock. Issuing a new token invalidates older links.
    db.execute(update(CustomerToken).where(CustomerToken.customer_id == customer.id, CustomerToken.purpose == purpose, CustomerToken.used_at.is_(None)).values(used_at=now()))
    raw = secrets.token_urlsafe(32)
    lifetime = timedelta(hours=settings.auth_verification_hours) if purpose == "verify" else timedelta(minutes=settings.auth_reset_minutes)
    db.add(CustomerToken(customer_id=customer.id, token_hash=digest(raw), purpose=purpose, expires_at=now() + lifetime))
    route = "verify-email" if purpose == "verify" else "reset-password"
    # Fragments are not transmitted in HTTP requests/access logs/referrers.
    link = f"{settings.auth_origin}/{route}#token={raw}&lang={customer.preferred_language}"
    try:
        get_email_delivery(settings).send(customer.email, purpose, link, customer.preferred_language)
    except (OSError, RuntimeError):
        db.rollback()
        raise HTTPException(503, "email_unavailable") from None


def revoke_sessions(db, customer):
    db.execute(update(CustomerSession).where(CustomerSession.customer_id == customer.id, CustomerSession.revoked_at.is_(None)).values(revoked_at=now()))


def expire_cookie(response, settings):
    response.delete_cookie(cookie_name(settings), path="/", secure=settings.auth_environment == "production" or settings.auth_origin.startswith("https:"), httponly=True, samesite="lax")


def authenticated(request, db, settings, write=False):
    raw = request.cookies.get(cookie_name(settings), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw):
        raise HTTPException(401, "authentication_required")
    record = db.scalar(select(CustomerSession).where(CustomerSession.token_hash == digest(raw)))
    if record is None:
        raise HTTPException(401, "authentication_required")
    # Serialize credential changes and token/session use against this account.
    customer = db.scalar(select(Customer).where(Customer.id == record.customer_id).with_for_update().execution_options(populate_existing=True))
    db.refresh(record)
    if customer is None or customer.status != "active" or not customer.email_verified or record.revoked_at is not None or record.expires_at <= now():
        raise HTTPException(401, "authentication_required")
    if write and not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode("utf-8"), csrf_value(raw).encode("ascii")):
        raise HTTPException(403, "csrf_failed")
    return customer, record, raw


def consume_token(raw, purpose, db):
    record = db.scalar(select(CustomerToken).where(CustomerToken.token_hash == digest(raw), CustomerToken.purpose == purpose))
    if record is None:
        raise HTTPException(400, "invalid_or_expired_token")
    customer = db.scalar(select(Customer).where(Customer.id == record.customer_id).with_for_update().execution_options(populate_existing=True))
    db.refresh(record)
    if customer is None or customer.status != "active" or record.used_at is not None or record.expires_at <= now():
        raise HTTPException(400, "invalid_or_expired_token")
    record.used_at = now()
    return customer


@router.post("/register", status_code=202)
def register(payload: Registration, request: Request, db: Db, settings: Config):
    throttle(request, db, settings, "register", payload.email)
    password_hash = hash_password(payload.password)
    existing = db.scalar(select(Customer).where(Customer.email == payload.email))
    if existing is None:
        customer = Customer(email=payload.email, password_hash=password_hash, first_name=payload.first_name,
                            last_name=payload.last_name, preferred_language=payload.preferred_language)
        db.add(customer)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            return {"message": "check_email"}
        send_token(customer, "verify", db, settings)
        db.commit()
    return {"message": "check_email"}


@router.post("/verification/request", status_code=202)
def request_verification(payload: EmailRequest, request: Request, db: Db, settings: Config):
    throttle(request, db, settings, "verification-request", payload.email)
    customer = db.scalar(select(Customer).where(Customer.email == payload.email).with_for_update())
    if customer and customer.status == "active" and not customer.email_verified:
        try:
            send_token(customer, "verify", db, settings)
            db.commit()
        except (HTTPException, SQLAlchemyError) as exc:
            if isinstance(exc, HTTPException) and exc.status_code != 503:
                raise
            db.rollback()
            logging.getLogger("spectra.auth").warning("auth_email_delivery_failed")
    return {"message": "check_email"}


@router.post("/verify-email")
def verify_email(payload: TokenRequest, request: Request, db: Db, settings: Config):
    throttle(request, db, settings, "verify")
    customer = consume_token(payload.token, "verify", db)
    customer.email_verified = True
    db.execute(update(CustomerToken).where(CustomerToken.customer_id == customer.id, CustomerToken.purpose == "verify", CustomerToken.used_at.is_(None)).values(used_at=now()))
    db.commit()
    return {"message": "email_verified"}


@router.post("/login")
def login(payload: Login, request: Request, response: Response, db: Db, settings: Config):
    throttle(request, db, settings, "login", payload.email)
    customer = db.scalar(select(Customer).where(Customer.email == payload.email).with_for_update())
    valid = verify_password(payload.password, customer.password_hash if customer else DUMMY_HASH)
    if not valid or customer is None or not customer.email_verified or customer.status != "active":
        raise HTTPException(401, "invalid_credentials")
    # A successful login always creates a fresh identifier; never adopt a client ID.
    old = request.cookies.get(cookie_name(settings))
    if old:
        db.execute(update(CustomerSession).where(CustomerSession.token_hash == digest(old)).values(revoked_at=now()))
    raw = secrets.token_urlsafe(32)
    db.add(CustomerSession(customer_id=customer.id, token_hash=digest(raw), expires_at=now() + timedelta(hours=settings.auth_session_hours)))
    db.commit()
    response.set_cookie(cookie_name(settings), raw, max_age=settings.auth_session_hours * 3600, path="/",
                        secure=settings.auth_environment == "production" or settings.auth_origin.startswith("https:"), httponly=True, samesite="lax")
    return public_customer(customer)


@router.get("/me")
def me(request: Request, db: Db, settings: Config):
    return public_customer(authenticated(request, db, settings)[0])


@router.get("/csrf")
def csrf(request: Request, db: Db, settings: Config):
    return {"csrf_token": csrf_value(authenticated(request, db, settings)[2])}


@router.post("/logout")
def logout(request: Request, response: Response, db: Db, settings: Config):
    _, record, _ = authenticated(request, db, settings, write=True)
    record.revoked_at = now()
    db.commit()
    expire_cookie(response, settings)
    return {"message": "logged_out"}


@router.patch("/profile")
def update_profile(payload: Profile, request: Request, db: Db, settings: Config):
    customer, _, _ = authenticated(request, db, settings, write=True)
    for key, value in payload.model_dump().items():
        setattr(customer, key, value)
    db.commit()
    return public_customer(customer)


@router.post("/password/change")
def change_password(payload: PasswordChange, request: Request, response: Response, db: Db, settings: Config):
    throttle(request, db, settings, "password-change")
    customer, _, _ = authenticated(request, db, settings, write=True)
    if not verify_password(payload.current_password, customer.password_hash):
        raise HTTPException(400, "invalid_current_password")
    customer.password_hash = hash_password(payload.new_password)
    revoke_sessions(db, customer)
    db.execute(update(CustomerToken).where(CustomerToken.customer_id == customer.id, CustomerToken.purpose == "reset", CustomerToken.used_at.is_(None)).values(used_at=now()))
    db.commit()
    expire_cookie(response, settings)
    return {"message": "password_changed"}


@router.post("/password/reset/request", status_code=202)
def reset_request(payload: EmailRequest, request: Request, db: Db, settings: Config):
    throttle(request, db, settings, "reset-request", payload.email)
    customer = db.scalar(select(Customer).where(Customer.email == payload.email).with_for_update())
    if customer and customer.status == "active":
        try:
            send_token(customer, "reset", db, settings)
            db.commit()
        except (HTTPException, SQLAlchemyError) as exc:
            if isinstance(exc, HTTPException) and exc.status_code != 503:
                raise
            db.rollback()
            logging.getLogger("spectra.auth").warning("auth_email_delivery_failed")
    return {"message": "check_email"}


@router.post("/password/reset")
def reset_password(payload: Reset, request: Request, response: Response, db: Db, settings: Config):
    throttle(request, db, settings, "reset")
    customer = consume_token(payload.token, "reset", db)
    customer.password_hash = hash_password(payload.password)
    revoke_sessions(db, customer)
    db.execute(update(CustomerToken).where(CustomerToken.customer_id == customer.id, CustomerToken.purpose == "reset", CustomerToken.used_at.is_(None)).values(used_at=now()))
    db.commit()
    expire_cookie(response, settings)
    return {"message": "password_reset"}
