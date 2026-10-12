import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session
from app.main import app


@pytest.fixture(scope="session")
def test_engine():
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        # Read local .env without putting test settings into the application cache.
        from dotenv import dotenv_values
        raw_url = dotenv_values(Path(__file__).resolve().parents[1] / ".env").get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.fail("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    test_url = make_url(raw_url)
    dev_url = make_url(get_settings().database_url)
    if test_url.drivername != "postgresql+psycopg" or not test_url.database or not test_url.database.endswith("_test"):
        pytest.fail("Test database must use postgresql+psycopg and a database name ending in _test")
    # Compare names regardless of host spelling to reject localhost/IP aliases.
    if test_url.database == dev_url.database:
        pytest.fail("Test database name must differ from development database")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = raw_url
    get_settings.cache_clear()
    try:
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()
    engine = create_engine(test_url)
    yield engine
    engine.dispose()


@pytest.fixture
def api(test_engine, tmp_path):
    # An outer transaction isolates every test, including endpoint commits.
    with test_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            settings = Settings(card_image_dir=tmp_path / "images", max_image_size_bytes=4096)
            app.dependency_overrides[get_session] = lambda: session
            app.dependency_overrides[get_settings] = lambda: settings
            try:
                with TestClient(app) as client:
                    yield client, session, settings
            finally:
                app.dependency_overrides.clear()
                transaction.rollback()
