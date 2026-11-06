"""Independent PostgreSQL connections compete for the same customer copy."""
# ruff: noqa: F811

import secrets
from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_intake_concurrency import isolated_intake_engine  # noqa: F401
from test_pricing_concurrency import race

from app.auth import csrf_value, digest, now
from app.config import Settings, get_settings
from app.customer_models import Customer, CustomerSession
from app.database import get_session
from app.library_models import CopyAssignment, CustomerCopy
from app.main import app
from app.submission_models import Submission, SubmissionEntry


def test_two_orders_cannot_concurrently_reserve_one_copy(isolated_intake_engine):
    engine = isolated_intake_engine
    tokens = [secrets.token_urlsafe(32) for _ in range(2)]
    with Session(engine) as db:
        customer = Customer(
            email=uuid4().hex + "@example.invalid",
            password_hash="unused",
            first_name="Synthetic",
            last_name="Library",
            email_verified=True,
        )
        db.add(customer)
        db.flush()
        copy = CustomerCopy(
            customer_id=customer.id,
            game="pokemon",
            card_name="Same physical copy",
            expansion="",
            card_number="",
            language="FR",
            notes="",
        )
        db.add(copy)
        orders = []
        for token in tokens:
            db.add(
                CustomerSession(
                    customer_id=customer.id,
                    token_hash=digest(token),
                    expires_at=now() + timedelta(hours=1),
                )
            )
            order = Submission(
                customer_id=customer.id, reference="SP-" + uuid4().hex.upper()
            )
            db.add(order)
            orders.append(order)
        db.flush()
        sid = [str(o.id) for o in orders]
        cid = str(copy.id)
        db.commit()

    def sessions():
        with Session(engine) as db:
            yield db

    settings = Settings()
    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_settings] = lambda: settings
    clients = [TestClient(app), TestClient(app)]
    try:
        for client, token in zip(clients, tokens):
            client.cookies.set("spectra_session", token)
            client.headers.update(
                {
                    "Origin": settings.auth_origin,
                    "X-Spectra-Client": "1",
                    "X-CSRF-Token": csrf_value(token),
                }
            )
        results = race(
            *[
                lambda c=c, s=s: c.post(
                    f"/api/submissions/{s}/library-copies",
                    json={"version": 1, "copy_id": cid},
                )
                for c, s in zip(clients, sid)
            ]
        )
        assert sorted(r.status_code for r in results) == [201, 409]
        with Session(engine) as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(CopyAssignment)
                    .where(CopyAssignment.released_at.is_(None))
                )
                == 1
            )
            assert db.scalar(select(func.count()).select_from(SubmissionEntry)) == 1
    finally:
        for client in clients:
            client.close()
        app.dependency_overrides.clear()
