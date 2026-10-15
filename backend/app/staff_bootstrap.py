"""Trusted-host CLI only; never exposed through HTTP."""
import argparse
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.database import get_engine
from app import submission_models  # noqa: F401 -- register intake audit FK targets in this CLI process
from app.customer_models import Customer
from app.intake_models import StaffMembership, IntakeAudit
from app.auth import revoke_sessions


def bootstrap(db, email, reason):
    if not reason.strip() or len(reason) > 1000:
        raise ValueError('A bounded operational reason is required')
    db.execute(text('SELECT pg_advisory_xact_lock(53504543545241)'))
    if db.scalar(select(StaffMembership.customer_id).limit(1)):
        raise ValueError('Bootstrap is closed: a staff membership already exists')
    customer = db.scalar(select(Customer).where(Customer.email == email.strip().lower()).with_for_update())
    if not customer or not customer.email_verified or customer.status != 'active':
        raise ValueError('An existing active verified account is required')
    db.add(StaffMembership(customer_id=customer.id, role='admin'))
    revoke_sessions(db, customer)
    db.add(IntakeAudit(actor_id=customer.id, action='administrator_bootstrapped', entity_id=customer.id,
                       data={'before':None,'after':'admin','source':'trusted_host_cli'}, reason=reason))
    db.commit()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    parser.add_argument('--reason', required=True)
    args = parser.parse_args()
    with Session(get_engine()) as session:
        try:
            bootstrap(session, args.email, args.reason)
        except ValueError as exc:
            parser.exit(1, str(exc) + '\n')
    print('Administrator authorized. Existing sessions revoked; sign in again.')
