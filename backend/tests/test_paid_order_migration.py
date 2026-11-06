"""Migrate a disposable schema containing legacy custody, evidence and quote rows."""

from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app.config import get_settings
from app.customer_models import Customer
from app.inspection_models import CustodyEvent, Inspection
from app.intake_models import IntakeAudit, Parcel, PhysicalCard
from app.models import Card, CardImage
from app.submission_models import Submission, SubmissionEntry
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_paid_foundation_migration_preserves_existing_records(test_engine, monkeypatch):
    schema = "paid_migration_" + uuid4().hex
    assert test_engine.url.database.endswith("_test")
    with test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    target = test_engine.url.update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(target)
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    try:
        with monkeypatch.context() as environment:
            environment.setenv(
                "DATABASE_URL", target.render_as_string(hide_password=False)
            )
            get_settings.cache_clear()
            command.upgrade(config, "0012")
            with Session(engine) as db:
                customer = Customer(
                    email="migration@example.invalid",
                    password_hash="unused",
                    first_name="TEST",
                    last_name="Migration",
                    email_verified=True,
                )
                grade = Card(
                    game="pokemon",
                    card_name="TEST legacy",
                    set_name="TEST",
                    collector_number="1",
                )
                db.add_all([customer, grade])
                db.flush()
                order = Submission(
                    customer_id=customer.id,
                    reference="SP-" + uuid4().hex.upper(),
                    status="submitted",
                    notes="Preserve this original order",
                )
                db.add(order)
                db.flush()
                entry = SubmissionEntry(
                    submission_id=order.id,
                    game="pokemon",
                    card_name="TEST legacy",
                    expansion="TEST",
                    card_number="1",
                    language="FR",
                    quantity=1,
                    notes="Original declaration",
                )
                db.add(entry)
                db.flush()
                parcel = Parcel(
                    submission_id=order.id,
                    reference="PK-" + uuid4().hex.upper(),
                    received_by=customer.id,
                    request_key=uuid4(),
                    request_data={},
                )
                db.add(parcel)
                db.flush()
                pc = PhysicalCard(
                    submission_id=order.id,
                    entry_id=entry.id,
                    parcel_id=parcel.id,
                    reference="PC-" + uuid4().hex.upper(),
                    received_by=customer.id,
                    request_key=uuid4(),
                    request_data={},
                    status="matched",
                    grading_card_id=grade.id,
                )
                image = CardImage(
                    card_id=grade.id,
                    side="front",
                    original_filename="unchanged.png",
                    mime_type="image/png",
                    sha256="a" * 64,
                    file_size=1,
                    storage_key=uuid4().hex,
                )
                db.add_all([pc, image])
                db.flush()
                inspection = Inspection(
                    physical_card_id=pc.id,
                    started_by=customer.id,
                    status="in_progress",
                    location="inspection_workstation",
                    version=1,
                )
                db.add(inspection)
                db.flush()
                db.add(
                    CustodyEvent(
                        inspection_id=inspection.id,
                        actor_id=customer.id,
                        request_key=uuid4(),
                        action="start",
                        previous_state="not_started",
                        new_state="in_progress",
                        source="secure_intake_storage",
                        destination="inspection_workstation",
                        reason="Original custody handoff",
                    )
                )
                db.add(
                    IntakeAudit(
                        submission_id=order.id,
                        actor_id=customer.id,
                        action="original_test_event",
                        entity_id=pc.id,
                        data={"preserve": True},
                        reason="Original evidence",
                    )
                )
                db.commit()
            tables = (
                "customers",
                "customer_submissions",
                "customer_submission_entries",
                "intake_parcels",
                "physical_cards",
                "cards",
                "card_images",
                "inspections",
                "inspection_custody_events",
                "intake_audit_events",
            )
            with engine.connect() as connection:
                before = {
                    table: list(
                        connection.execute(text(f"SELECT * FROM {table}")).mappings()
                    )
                    for table in tables
                }
            command.upgrade(config, "head")
            with engine.connect() as connection:
                for table in tables:
                    assert (
                        list(
                            connection.execute(
                                text(f"SELECT * FROM {table}")
                            ).mappings()
                        )
                        == before[table]
                    )
                for table in (
                    "payment_obligations",
                    "verified_payments",
                    "dispatch_expectations",
                    "supplementary_acceptances",
                ):
                    assert (
                        connection.execute(
                            text(f"SELECT count(*) FROM {table}")
                        ).scalar()
                        == 0
                    )
                assert (
                    connection.execute(
                        text(
                            "SELECT data_type FROM information_schema.columns WHERE table_schema=:schema AND table_name='payment_obligations' AND column_name='amount_minor'"
                        ),
                        {"schema": schema},
                    ).scalar()
                    == "bigint"
                )
            command.downgrade(config, "0012")
            command.upgrade(config, "head")
            with engine.connect() as connection:
                for table in tables:
                    assert (
                        list(
                            connection.execute(
                                text(f"SELECT * FROM {table}")
                            ).mappings()
                        )
                        == before[table]
                    )
    finally:
        get_settings.cache_clear()
        engine.dispose()
        with test_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
