"""Explicit trusted-host development fixtures; never exposed through HTTP.

Run from backend: python -m app.local_test_accounts --database spectra --confirm-local-development
Only the five fixed fictional addresses are supported. No outgoing email is sent.
"""

import argparse
import ipaddress
import os
import secrets
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app import submission_models  # noqa: F401 -- register audit foreign keys
from app.auth import revoke_sessions
from app.config import get_settings
from app.customer_models import Customer
from app.intake_models import IntakeAudit, StaffMembership
from app.passwords import hash_password

ROOT = Path(__file__).resolve().parents[2]
CREDENTIALS = ROOT / "SELBY_LOCAL_TEST_CREDENTIALS.md"
SPECS = (
    (
        "Client Test",
        "01",
        "client01@selby.test",
        None,
        "Customer declaration and draft workflow",
    ),
    (
        "Client Test",
        "02",
        "client02@selby.test",
        None,
        "Independent customer ownership/isolation checks",
    ),
    (
        "Client Test",
        "03",
        "client03@selby.test",
        None,
        "Additional manual card declarations",
    ),
    (
        "Opérateur",
        "Test",
        "operator@selby.test",
        "operator",
        "Incoming orders and authorized physical reception",
    ),
    (
        "Administrateur",
        "Test",
        "admin@selby.test",
        "admin",
        "Existing administrator custody authorization policy",
    ),
)
MARKER = "local_development_account_created"


class SetupError(Exception):
    """Only deliberate, nonsecret diagnostics may be shown to the operator."""


def loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_interface(host).ip.is_loopback
    except (ValueError, TypeError):
        return False


def validate_target(settings, expected_database):
    url = make_url(settings.database_url)
    origin = urlsplit(settings.auth_origin)
    if settings.auth_environment != "development" or not loopback(origin.hostname):
        raise SetupError(
            "Refusing: development authentication and a loopback portal origin are required."
        )
    allowed = {"spectra", "spectra_dev", "selby_dev", "spectra_test", "selby_test"}
    if (
        url.drivername != "postgresql+psycopg"
        or not loopback(url.host)
        or url.database not in allowed
        or expected_database != url.database
        or url.query
    ):
        raise SetupError(
            "Refusing: explicitly confirm an allowed local development database; remote hosts and URL options are forbidden."
        )
    return url


def verify_server(db, expected_database):
    name, address, recovery = db.execute(
        text("SELECT current_database(),inet_server_addr()::text,pg_is_in_recovery()")
    ).one()
    if name != expected_database or not address or not loopback(address) or recovery:
        raise SetupError(
            "Refusing: server identity is not the confirmed writable loopback development database."
        )


@dataclass
class AccountResult:
    email: str
    name: str
    role: str | None
    verified: bool
    scenario: str
    action: str
    password: str | None = field(default=None, repr=False)


def seed(db, settings, expected_database, reset_email=None):
    validate_target(settings, expected_database)
    verify_server(db, expected_database)
    db.execute(text("SELECT pg_advisory_xact_lock(53504543545242)"))
    if reset_email is not None and reset_email not in {spec[2] for spec in SPECS}:
        raise SetupError("Reset is limited to the five fixed fictional addresses.")
    # Validate reset ownership before making any changes. Default reruns never change an account.
    if reset_email:
        customer = db.scalar(
            select(Customer).where(Customer.email == reset_email).with_for_update()
        )
        owned = customer and db.scalar(
            select(IntakeAudit.id)
            .where(IntakeAudit.entity_id == customer.id, IntakeAudit.action == MARKER)
            .limit(1)
        )
        expected_role = next(spec[3] for spec in SPECS if spec[2] == reset_email)
        membership = db.get(StaffMembership, customer.id) if customer else None
        if (
            not owned
            or customer.status != "active"
            or not customer.email_verified
            or (membership.role if membership else None) != expected_role
        ):
            raise SetupError(
                "Refusing reset: an active verified fixture owned by this seeder with unchanged role is required. Existing conflicting accounts are preserved."
            )
    results = []
    generated = set()
    for first, last, email, role, scenario in SPECS:
        customer = db.scalar(
            select(Customer).where(Customer.email == email).with_for_update()
        )
        password = None
        action = "preserved"
        if customer is None:
            password = secrets.token_urlsafe(32)
            while password in generated:
                password = secrets.token_urlsafe(32)
            generated.add(password)
            customer = Customer(
                email=email,
                first_name=first,
                last_name=last,
                password_hash=hash_password(password),
                email_verified=True,
                preferred_language="FR",
                status="active",
            )
            db.add(customer)
            db.flush()
            if role:
                db.add(StaffMembership(customer_id=customer.id, role=role))
            db.add(
                IntakeAudit(
                    actor_id=customer.id,
                    entity_id=customer.id,
                    action=MARKER,
                    data={
                        "source": "trusted_local_development_cli",
                        "staff_role": role,
                    },
                    reason="Explicit fictional local development account setup",
                )
            )
            action = "created"
        elif email == reset_email:
            password = secrets.token_urlsafe(32)
            customer.password_hash = hash_password(password)
            revoke_sessions(db, customer)
            db.add(
                IntakeAudit(
                    actor_id=customer.id,
                    entity_id=customer.id,
                    action="local_development_password_reset",
                    data={"source": "explicit_local_development_reset"},
                    reason="Explicit fixture-only password rotation; sessions revoked",
                )
            )
            action = "reset"
        membership = db.get(StaffMembership, customer.id)
        results.append(
            AccountResult(
                email,
                customer.first_name + " " + customer.last_name,
                membership.role if membership else None,
                customer.email_verified,
                scenario,
                action,
                password,
            )
        )
    db.flush()
    return results


def ensure_ignored(path=CREDENTIALS):
    if path.is_symlink():
        raise SetupError("Refusing a symlink for the local credentials document.")
    args = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
    tracked = (
        subprocess.run(
            [*args, "ls-files", "--error-unmatch", path.as_posix()],
            cwd=ROOT,
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )
    ignored = (
        subprocess.run(
            [*args, "check-ignore", "-q", path.as_posix()],
            cwd=ROOT,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )
    if tracked or not ignored:
        raise SetupError(
            "Credentials must be untracked and explicitly Git-ignored before creating accounts."
        )


def credentials_text(results, origin):
    header = f"""# SELBY — LOCAL DEVELOPMENT ONLY

Fictional accounts for the confirmed local development database only. Never deploy,
commit, share publicly, or reuse these passwords on another service. This local file
is excluded by .gitignore, .dockerignore and Git archive export rules. No real emails
are sent. Passwords exist in PostgreSQL only as the existing salted scrypt hashes.

Portal login: {origin}/login

Workstation: launch scanner_agent/Launch_SELBY.vbs; verify Settings has the intended
local FastAPI/portal origins, open Incoming Orders and use the operator or admin
account below. Customers intentionally have no Incoming Orders permission. Admin
custody authorization does not prove payment or grant inspection clearance.

Missing plaintext for a preserved account is never guessed or silently reset.
For an owned fixture only, an explicit trusted-host reset is available from backend:
`.venv/Scripts/python.exe -m app.local_test_accounts --database spectra --confirm-local-development --reset-email <one-listed-email> --confirm-reset`.
Reset refuses accounts without this seeder's provenance; it revokes that fixture's
sessions. Old rows below are historical after a reset; the latest issued row wins.
Never use this command to elevate or reset arbitrary customer accounts.

| Display name | Email | Password | Role | Email verified | Scenario | Action |
| --- | --- | --- | --- | --- | --- | --- |
"""
    rows = []
    for item in results:
        # Existing profile text is not copied into credentials: all labels are fixed fictional specs.
        spec = next(spec for spec in SPECS if spec[2] == item.email)
        rows.append(
            f"| {spec[0]} {spec[1]} | {item.email} | {item.password or 'Not generated: existing account preserved'} | {item.role or 'Customer (no staff membership)'} | {item.verified} | {item.scenario} | {item.action} |"
        )
    return header + "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        help="Exact allowed local development database name",
    )
    parser.add_argument("--confirm-local-development", action="store_true")
    parser.add_argument("--reset-email", choices=[spec[2] for spec in SPECS])
    parser.add_argument("--confirm-reset", action="store_true")
    args = parser.parse_args()
    if (
        not args.confirm_local_development
        or bool(args.reset_email) != args.confirm_reset
    ):
        parser.error(
            "Explicit local-development confirmation is required; reset additionally requires both --reset-email and --confirm-reset."
        )
    engine = None
    original = None
    touched = False
    committed = False
    try:
        settings = get_settings()
        url = validate_target(settings, args.database)
        ensure_ignored()
        # Do not let libpq environment/service options redirect an ostensibly local host.
        hostaddr = "127.0.0.1" if url.host == "localhost" else url.host
        engine = create_engine(
            url,
            connect_args={
                "connect_timeout": 3,
                "hostaddr": hostaddr,
                "port": url.port or 5432,
            },
        )
        with Session(engine) as db:
            results = seed(db, settings, args.database, args.reset_email)
            issued = [item for item in results if item.password]
            if issued or not CREDENTIALS.exists():
                original = CREDENTIALS.read_bytes() if CREDENTIALS.exists() else None
                document = credentials_text(results, settings.auth_origin)
                if original:
                    document = (
                        original.decode("utf-8")
                        + "\n## Additional credentials issued (latest rows supersede older rows)\n\n"
                        + credentials_text(issued, settings.auth_origin)
                    )
                flags = (
                    os.O_WRONLY
                    | os.O_CREAT
                    | (os.O_TRUNC if original is not None else os.O_EXCL)
                )
                fd = os.open(CREDENTIALS, flags, 0o600)
                touched = True
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                    output.write(document)
                    output.flush()
                    os.fsync(output.fileno())
            db.commit()
            committed = True
        for item in results:
            print(
                f"{item.email}: {item.action}; staff role={item.role or 'none'}; verified={item.verified}"
            )
        print(f"Local credentials document: {CREDENTIALS}")
        print("No outgoing mail, submissions or global verification changes were made.")
    except Exception as exc:  # noqa: BLE001 -- CLI errors must not echo database URLs or secret-bearing exceptions.
        if touched and not committed:
            # A commit connection failure can have an unknown outcome. Never destroy
            # the only copy of newly issued credentials in that case.
            try:
                with CREDENTIALS.open("a", encoding="utf-8") as output:
                    output.write(
                        "\nSetup did not confirm database commit. Verify account state before using this batch. Rerunning preserves existing accounts.\n"
                    )
            except OSError:
                pass
        message = (
            str(exc)
            if isinstance(exc, SetupError)
            else f"Local setup failed ({type(exc).__name__}); no secrets printed."
        )
        parser.exit(1, message + "\n")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
