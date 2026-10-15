"""Read-only staff directory. Association with an account is not legal ownership."""
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.cards import Config, Db
from app.checkout_models import CustomerAddress, SubmissionDelivery
from app.customer_models import Customer
from app.intake import encoded, staff
from app.intake_models import Intake, Parcel, PhysicalCard
from app.pricing_models import QuoteAcceptance, SubmissionQuote
from app.submission_models import Submission, SubmissionEntry
from app.physical_identity import parse_scan


def require_staff(request: Request, db: Db, settings: Config):
    # Router dependency runs before entity lookup and request parameter validation.
    return staff(request, db, settings)


router = APIRouter(prefix='/internal/customer-operations',
                   dependencies=[Depends(require_staff)], include_in_schema=False)
CUSTOMER_FIELDS = ('id', 'first_name', 'last_name', 'email', 'status', 'created_at')
ADDRESS_FIELDS = ('recipient', 'line1', 'line2', 'postal_code', 'city', 'country', 'phone', 'instructions')
UUID_PATTERN = r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'


def customer_reference(value):
    if not re.fullmatch(UUID_PATTERN, value):
        raise HTTPException(422, 'invalid_customer_reference')
    return UUID(value)


def get_customer(db, identifier):
    row = db.execute(select(*(getattr(Customer, f) for f in (*CUSTOMER_FIELDS, 'email_verified')))
                     .where(Customer.id == customer_reference(identifier))).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, 'customer_not_found')
    return dict(row)


def page(rows, limit, offset):
    return {'items': rows[:limit], 'limit': limit, 'offset': offset, 'has_more': len(rows) > limit}


def address_fields(value):
    # Do not forward arbitrary snapshot JSON or account secrets.
    return {field: value.get(field, '') for field in ADDRESS_FIELDS} if isinstance(value, dict) else None


@router.get('/customers')
def customers(db: Db, search: str = Query('', max_length=254),
              limit: int = Query(25, ge=1, le=50), offset: int = Query(0, ge=0, le=100_000)):
    search = search.strip()
    statement = select(*(getattr(Customer, f) for f in CUSTOMER_FIELDS))
    if search:
        if any(ord(c) < 32 or ord(c) == 127 for c in search):
            raise HTTPException(422, 'invalid_search')
        if re.fullmatch(UUID_PATTERN, search):
            statement = statement.where(Customer.id == UUID(search))
        else:
            if len(search) < 2:
                raise HTTPException(422, 'invalid_search')
            # Treat LIKE metacharacters literally, never as unrestricted wildcard patterns.
            term = search.lower()
            statement = statement.where(or_(
                func.lower(Customer.email).contains(term, autoescape=True),
                func.lower(Customer.first_name + ' ' + Customer.last_name).contains(term, autoescape=True),
            ))
    rows = [dict(r) for r in db.execute(statement.order_by(Customer.created_at.desc(), Customer.id)
                                       .offset(offset).limit(limit + 1)).mappings()]
    return page(rows, limit, offset)


@router.get('/customers/{identifier}')
def customer_detail(identifier: str, db: Db):
    customer = get_customer(db, identifier)
    addresses = list(db.scalars(select(CustomerAddress).where(CustomerAddress.customer_id == customer['id'])
                               .order_by(CustomerAddress.created_at, CustomerAddress.id).limit(101)))
    return {**customer, 'saved_addresses': [encoded(a, 'id ' + ' '.join(ADDRESS_FIELDS)) for a in addresses[:100]],
            'addresses_truncated': len(addresses) > 100}


@router.get('/customers/{identifier}/submissions')
def history(identifier: str, db: Db, limit: int = Query(25, ge=1, le=50),
            offset: int = Query(0, ge=0, le=100_000)):
    customer = get_customer(db, identifier)
    # Count declared quantities in SQL, not a per-submission loop over all card entries.
    quantity = (select(func.coalesce(func.sum(SubmissionEntry.quantity), 0))
                .where(SubmissionEntry.submission_id == Submission.id).correlate(Submission).scalar_subquery())
    statement = (select(Submission.id, Submission.reference, Submission.status, Submission.created_at,
                        Submission.confirmed_at, quantity.label('declared_quantity'),
                        Intake.status.label('intake_status'), QuoteAcceptance.quote_id,
                        SubmissionQuote.snapshot, CustomerAddress)
                 .outerjoin(Intake, Intake.submission_id == Submission.id)
                 .outerjoin(QuoteAcceptance, QuoteAcceptance.submission_id == Submission.id)
                 .outerjoin(SubmissionQuote, (SubmissionQuote.id == QuoteAcceptance.quote_id) &
                            (SubmissionQuote.submission_id == Submission.id))
                 .outerjoin(SubmissionDelivery, SubmissionDelivery.submission_id == Submission.id)
                 .outerjoin(CustomerAddress, (CustomerAddress.id == SubmissionDelivery.address_id) &
                            (CustomerAddress.customer_id == Submission.customer_id))
                 .where(Submission.customer_id == customer['id'])
                 .order_by(Submission.created_at.desc(), Submission.id).offset(offset).limit(limit + 1))
    results = []
    for row in db.execute(statement):
        address, source = None, None
        if row.quote_id:
            checkout = row.snapshot.get('checkout', {}) if isinstance(row.snapshot, dict) else {}
            address = address_fields(checkout.get('return_address'))
            source = 'accepted_snapshot' if address else 'not_recorded'
        elif row.CustomerAddress:
            address = encoded(row.CustomerAddress, ' '.join(ADDRESS_FIELDS))
            source = 'current_selection'
        results.append({field: getattr(row, field) for field in
                        ('id', 'reference', 'status', 'created_at', 'confirmed_at', 'declared_quantity', 'intake_status')}
                       | {'return_address': address, 'return_address_source': source})
    return page(results, limit, offset)


@router.get('/cards/{reference}')
def physical_card(reference: str, db: Db):
    try:
        reference = parse_scan(reference)
    except ValueError:
        raise HTTPException(422, 'invalid_card_reference')
    card = db.scalar(select(PhysicalCard).where(PhysicalCard.reference == reference))
    if card is None:
        raise HTTPException(404, 'card_not_found')
    parcel = db.get(Parcel, card.parcel_id)
    submission = db.get(Submission, card.submission_id)
    entry = db.get(SubmissionEntry, card.entry_id) if card.entry_id else None
    if (not parcel or not submission or parcel.submission_id != submission.id or
            (card.entry_id and (not entry or entry.submission_id != submission.id))):
        raise HTTPException(409, 'trace_inconsistent')
    customer = get_customer(db, str(submission.customer_id))
    return {'card': encoded(card, 'id reference status'),
            'declared_entry': encoded(entry, 'id card_name game expansion card_number language') if entry else None,
            'parcel': encoded(parcel, 'id reference'),
            'submission': encoded(submission, 'id reference status'),
            'customer': {field: customer[field] for field in ('id', 'first_name', 'last_name', 'email')}}
