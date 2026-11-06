"""Independent actors/connections enforce backend registry ownership."""
# ruff: noqa: F811

import secrets
from datetime import timedelta
from uuid import uuid4

import pytest
from app.auth import csrf_value, digest, now
from app.config import Settings, get_settings
from app.customer_models import Customer, CustomerSession
from app.database import get_session
from app.intake_models import Intake, IntakeAudit, Parcel, PhysicalCard, StaffMembership
from app.main import app
from app.production_models import ProductionCard, ProductionOrder
from app.submission_models import Submission, SubmissionEntry
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_intake_concurrency import isolated_intake_engine  # noqa: F401
from test_pricing_concurrency import race


def test_competing_registries_and_exact_confirmation_replay(isolated_intake_engine, tmp_path):
    engine = isolated_intake_engine
    settings = Settings(auth_mail_dir=tmp_path / "mail")
    tokens = []
    with Session(engine) as db:
        for _ in range(2):
            actor = Customer(
                email=uuid4().hex + "@example.invalid",
                password_hash="unused",
                first_name="Synthetic",
                last_name="Staff",
                email_verified=True,
            )
            db.add(actor)
            db.flush()
            db.add(StaffMembership(customer_id=actor.id, role="operator"))
            raw = secrets.token_urlsafe(32)
            db.add(
                CustomerSession(
                    customer_id=actor.id,
                    token_hash=digest(raw),
                    expires_at=now() + timedelta(hours=1),
                )
            )
            tokens.append(raw)
        item = Submission(
            customer_id=actor.id,
            reference="SP-" + uuid4().hex.upper(),
            status="submitted",
            confirmed_at=now(),
        )
        db.add(item)
        db.flush()
        sid = str(item.id)
        entry = SubmissionEntry(
            submission_id=item.id,
            game="pokemon",
            card_name="Synthetic",
            expansion="",
            card_number="",
            language="FR",
            quantity=1,
        )
        parcel = Parcel(
            reference="PI-" + uuid4().hex.upper(),
            submission_id=item.id,
            received_by=actor.id,
            request_key=uuid4(),
            request_data={},
            carrier="",
            tracking="",
            notes="",
        )
        db.add_all([entry, parcel, Intake(submission_id=item.id, status="reconciled")])
        db.flush()
        card = PhysicalCard(
            reference="PC-" + uuid4().hex.upper(),
            submission_id=item.id,
            parcel_id=parcel.id,
            entry_id=entry.id,
            received_by=actor.id,
            request_key=uuid4(),
            request_data={},
            notes="",
            status="matched",
        )
        db.add(card)
        db.flush()
        pc = str(card.id)
        db.commit()

    def sessions():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = sessions
    app.dependency_overrides[get_settings] = lambda: settings
    clients = [TestClient(app), TestClient(app)]
    try:
        for client, token in zip(clients, tokens, strict=True):
            client.cookies.set("spectra_session", token)
            client.headers.update(
                {
                    "Origin": settings.auth_origin,
                    "X-Spectra-Client": "1",
                    "X-CSRF-Token": csrf_value(token),
                }
            )
        path = f"/internal/intake/submissions/{sid}/production"
        registries = [str(uuid4()), str(uuid4())]
        responses = race(
            *[
                lambda c=c, r=r: c.post(
                    path + "/reserve",
                    json={
                        "registry_id": r,
                        "mode": "create",
                        "reason": "Concurrent verified preparation",
                    },
                )
                for c, r in zip(clients, registries, strict=True)
            ]
        )
        assert sorted(r.status_code for r in responses) == [200, 409]
        winner = registries[next(i for i, r in enumerate(responses) if r.status_code == 200)]
        reserve = {"registry_id": winner, "mode": "create", "reason": "Retry same reservation"}
        assert all(
            r.status_code == 200
            for r in race(*[lambda c=c: c.post(path + "/reserve", json=reserve) for c in clients])
        )
        payload = {
            "registry_id": winner,
            "local_order_id": "ORD-000001",
            "cards": [{"physical_card_id": pc, "local_card_id": "SLB-C-000001"}],
            "reason": "Exact confirmation retry",
        }
        confirmed = race(*[lambda c=c: c.post(path + "/confirm", json=payload) for c in clients])
        assert all(r.status_code == 200 for r in confirmed)
        wrong = {**payload, "local_order_id": "ORD-000002"}
        assert clients[0].post(path + "/confirm", json=wrong).status_code == 409
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(ProductionOrder)) == 1
            assert db.scalar(select(func.count()).select_from(ProductionCard)) == 1
            for action in ("production_reserved", "production_confirmed"):
                assert (
                    db.scalar(
                        select(func.count())
                        .select_from(IntakeAudit)
                        .where(IntakeAudit.action == action)
                    )
                    == 1
                )
            # A fresh schema exercises the entire new migration.
            for sql in (
                "TRUNCATE production_cards",
                "TRUNCATE production_orders CASCADE",
                "UPDATE production_cards SET local_card_id='SLB-C-999999'",
            ):
                with pytest.raises(DBAPIError), db.begin_nested():
                    db.execute(text(sql))
    finally:
        for client in clients:
            client.close()
        app.dependency_overrides.clear()
