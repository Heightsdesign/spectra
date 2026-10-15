"""Exercise W3.1 backfill and downgrade in a disposable PostgreSQL schema."""
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.config import get_settings


def test_migration_preserves_existing_confirmed_entries(test_engine, monkeypatch):
    schema = "w32_migration_" + uuid4().hex
    with test_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated_url = test_engine.url.update_query_dict({"options": f"-csearch_path={schema}"})
    customer_id, submission_id, entry_id = uuid4(), uuid4(), uuid4()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    try:
        with monkeypatch.context() as environment:
            environment.setenv("DATABASE_URL", isolated_url.render_as_string(hide_password=False))
            get_settings.cache_clear()
            command.upgrade(config, "0003")
            with test_engine.begin() as connection:
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                connection.execute(text("""INSERT INTO customers (id,email,password_hash,first_name,last_name,preferred_language,email_verified,status)
                    VALUES (:id,'migration@example.invalid','unused','Legacy','Collector','FR',true,'active')"""), {"id": customer_id})
                connection.execute(text("""INSERT INTO customer_submissions (id,reference,customer_id,status,notes,version,confirmed_at)
                    VALUES (:id,'SP-MIGRATION',:customer,'submitted','Keep existing',7,now())"""), {"id": submission_id, "customer": customer_id})
                connection.execute(text("""INSERT INTO customer_submission_entries (id,submission_id,game,card_name,expansion,card_number,language,quantity,notes)
                    VALUES (:id,:submission,'pokemon','Pikachu','Base','58/102','FR',3,'Original description')"""), {"id": entry_id, "submission": submission_id})
                before = dict(connection.execute(text("SELECT * FROM customer_submission_entries")).mappings().one())
                internal_columns = [(c["name"], str(c["type"])) for c in inspect(connection).get_columns("cards", schema=schema)]
            command.upgrade(config, "0004")
            with test_engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                migrated = dict(connection.execute(text("SELECT * FROM customer_submission_entries")).mappings().one())
                assert {key: migrated[key] for key in before} == before
                assert migrated["processing_tier"] == "standard" and migrated["upgrade_ids"] == ["classic"]
                submission = connection.execute(text("SELECT * FROM customer_submissions")).mappings().one()
                assert submission["status"] == "submitted" and submission["version"] == 7
                assert submission["pricing_revision"] == 1 and submission["confirmed_at"]
                assert [(c["name"], str(c["type"])) for c in inspect(connection).get_columns("cards", schema=schema)] == internal_columns
                assert connection.execute(text("SELECT current_version FROM pricing_state")).scalar() is None
            command.upgrade(config, "0005")
            with test_engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                assert dict(connection.execute(text("SELECT * FROM customer_submission_entries")).mappings().one()) == migrated
                assert connection.execute(text("SELECT current_version FROM shipping_state")).scalar() is None
                assert connection.execute(text("SELECT count(*) FROM customer_addresses")).scalar() == 0
            command.upgrade(config, "0006")
            with test_engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                assert dict(connection.execute(text("SELECT * FROM customer_submission_entries")).mappings().one()) == migrated
                assert connection.execute(text("SELECT count(*) FROM staff_memberships")).scalar() == 0
                assert connection.execute(text("SELECT count(*) FROM physical_cards")).scalar() == 0
                assert connection.execute(text("SELECT count(*) FROM submission_intakes")).scalar() == 0
            command.downgrade(config, "0005")
            command.downgrade(config, "0004")
            command.downgrade(config, "0003")
            with test_engine.connect() as connection:
                connection.execute(text(f'SET search_path TO "{schema}"'))
                assert dict(connection.execute(text("SELECT * FROM customer_submission_entries")).mappings().one()) == before
            command.upgrade(config, "0004")
    finally:
        get_settings.cache_clear()
        # This schema was generated and created above in the verified _test DB.
        with test_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
