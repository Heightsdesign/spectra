"""Independent actors race on the shared submission lock, not just a session lock."""
# ruff: noqa: F811

import secrets
from datetime import timedelta
from uuid import uuid4

import pytest
from app.auth import csrf_value, digest, now
from app.config import Settings, get_settings
from app.customer_models import CustomerSession
from app.database import get_session
from app.intake_models import Intake, IntakeAudit, Parcel, PhysicalCard, StaffMembership
from app.intake_voids import PhysicalCardVoid
from app.main import app
from app.submission_models import Submission, SubmissionEntry
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_intake_concurrency import customer, isolated_intake_engine  # noqa: F401
from test_pricing_concurrency import race


@pytest.mark.parametrize("competing", ["void", "match"])
def test_void_and_conflicting_transition_serialize(isolated_intake_engine, tmp_path, competing):
    engine = isolated_intake_engine
    settings = Settings(auth_mail_dir=tmp_path / "mail")
    tokens = []
    with Session(engine) as db:
        for _ in range(2):
            actor = customer(db)
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
        db.add_all(
            [
                entry,
                parcel,
                Intake(
                    submission_id=item.id,
                    status="reconciliation_pending",
                    override_reason="Synthetic custody authorization",
                ),
            ]
        )
        db.flush()
        card = PhysicalCard(
            reference="PC-" + uuid4().hex.upper(),
            submission_id=item.id,
            parcel_id=parcel.id,
            received_by=actor.id,
            request_key=uuid4(),
            request_data={},
            notes="",
            status="unidentified",
        )
        db.add(card)
        db.flush()
        sid, cid, eid = str(item.id), str(card.id), str(entry.id)
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
        path = f"/internal/intake/submissions/{sid}/cards/{cid}"
        payload = {"reason": "Synthetic erroneous registration; no object exists"}
        second = (
            payload
            if competing == "void"
            else {"entry_id": eid, "reason": "Physically verified card"}
        )
        results = race(
            lambda: clients[0].post(path + "/void", json=payload),
            lambda: clients[1].post(path + "/" + competing, json=second),
        )
        assert sorted(r.status_code for r in results) == (
            [200, 200] if competing == "void" else [200, 409]
        )
        with Session(engine) as db:
            voids = db.scalar(select(func.count()).select_from(PhysicalCardVoid))
            events = db.scalar(
                select(func.count())
                .select_from(IntakeAudit)
                .where(IntakeAudit.action == "physical_card_voided")
            )
            matched = db.scalar(
                select(func.count())
                .select_from(PhysicalCard)
                .where(PhysicalCard.entry_id.is_not(None))
            )
            assert events == voids
            assert (voids, matched) in ([(1, 0)] if competing == "void" else [(1, 0), (0, 1)])
    finally:
        for client in clients:
            client.close()
        app.dependency_overrides.clear()
