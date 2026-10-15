"""Run real HTTP tests against the dedicated PostgreSQL test DB, never development.

Invoke with backend/.venv/Scripts/python.exe after a frontend production build.
Uses existing FastAPI app and a Next production server; removes only its test user.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen
from uuid import uuid4

frontend = Path(__file__).resolve().parents[1]
backend = frontend.parent / "backend"
sys.path.insert(0, str(backend))

from dotenv import dotenv_values
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
import uvicorn
from app.config import Settings, get_settings
from app.database import get_session
from app.customer_models import Customer
from app.submission_models import Submission
from app.pricing_catalog import publish
from app.pricing_models import PricingCatalog, PricingState
from app.main import app


def main():
    raw = os.environ.get("TEST_DATABASE_URL") or dotenv_values(backend / ".env").get("TEST_DATABASE_URL")
    if not raw:
        raise RuntimeError("TEST_DATABASE_URL is required")
    url = make_url(raw)
    if url.drivername != "postgresql+psycopg" or not url.database.endswith("_test") or url.database == make_url(get_settings().database_url).database:
        raise RuntimeError("A separate PostgreSQL database ending in _test is required")
    backend_port = int(os.environ.get("SPECTRA_TEST_BACKEND_PORT", "8000"))
    frontend_port = int(os.environ.get("SPECTRA_TEST_FRONTEND_PORT", "13000"))
    for port in (backend_port, frontend_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))  # Fail if a user's server already owns it.
    engine = create_engine(raw)
    email = f"w2-smoke-{uuid4().hex}@example.invalid"
    origin = f"http://127.0.0.1:{frontend_port}"
    with tempfile.TemporaryDirectory(prefix="test_tmp_auth_http_", dir=frontend) as folder:
        settings = Settings(database_url=raw, auth_origin=origin, auth_mail_dir=Path(folder) / "mail", auth_rate_limit=100)
        import json
        with Session(engine) as db:
            previous_catalog = db.get(PricingState, 1).current_version
            example = json.loads((backend / "pricing" / "development-example.json").read_text(encoding="utf-8"))
            temporary_catalog = publish(db, example, settings).version
            db.commit()
        def sessions():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_session] = sessions
        app.dependency_overrides[get_settings] = lambda: settings
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=backend_port, access_log=False, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        process = None
        try:
            env = {**os.environ, "SPECTRA_BACKEND_URL": f"http://127.0.0.1:{backend_port}", "SPECTRA_INTEGRATION_URL": origin, "SPECTRA_TEST_MAIL": str(settings.auth_mail_dir), "SPECTRA_TEST_EMAIL": email}
            with (Path(folder) / "next.log").open("w") as log:
                process = subprocess.Popen(["node", "node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", str(frontend_port)], cwd=frontend, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("Next integration server did not start")
                    try:
                        with urlopen(origin + "/login", timeout=1):
                            if server.started:
                                break
                    except OSError:
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError("Integration servers did not become ready")
                result = subprocess.run(["node", "--test", "tests/auth.integration.mjs"], cwd=frontend, env=env, timeout=90)
                return result.returncode
        finally:
            if process is not None:
                process.terminate()
                process.wait(timeout=10)
            server.should_exit = True
            thread.join(timeout=10)
            app.dependency_overrides.clear()
            with engine.begin() as connection:
                connection.execute(delete(Submission).where(Submission.customer_id.in_(select(Customer.id).where(Customer.email == email))))
                connection.execute(delete(Customer).where(Customer.email == email))
            with Session(engine) as db:
                state = db.get(PricingState, 1, with_for_update=True)
                if state.current_version == temporary_catalog:
                    state.current_version = previous_catalog
                    db.flush()
                db.execute(delete(PricingCatalog).where(PricingCatalog.version == temporary_catalog))
                db.commit()
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
