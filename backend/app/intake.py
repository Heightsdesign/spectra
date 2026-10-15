"""Staff-only custody workflow. Every write serializes on the submission row."""
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.auth_schemas import valid_unicode
from sqlalchemy import select, func
from app.auth import authenticated, write_guard
from app.cards import Db, Config
from app.submission_models import Submission, SubmissionEntry
from app.pricing_models import QuoteAcceptance
from app.intake_models import StaffMembership, Intake, Parcel, PhysicalCard, Discrepancy, IntakeAudit

router = APIRouter(prefix='/internal/intake', dependencies=[Depends(write_guard)], include_in_schema=False)
STATES = {'awaiting_receipt', 'partially_received', 'reconciliation_pending', 'reconciled', 'on_hold'}


def staff(request, db, settings):
    customer = authenticated(request, db, settings, write=request.method != 'GET')[0]
    membership = db.get(StaffMembership, customer.id)
    if membership is None:
        raise HTTPException(403, 'staff_required')
    return customer


def audit(db, actor, submission, action, entity, data, reason=None):
    db.add(IntakeAudit(actor_id=actor.id, submission_id=submission, action=action,
                      entity_id=entity, data=data, reason=reason))


def rows(db, model, sid):
    return list(db.scalars(select(model).where(model.submission_id == sid).order_by(model.created_at if hasattr(model, 'created_at') else model.received_at, model.id)))


def encoded(row, fields):
    return {key: getattr(row, key) for key in fields.split()}


def summary(db, item):
    state = db.get(Intake, item.id)
    return dict(id=item.id, reference=item.reference, customer_reference=item.customer_id,
                declared_quantity=db.scalar(select(func.coalesce(func.sum(SubmissionEntry.quantity), 0)).where(SubmissionEntry.submission_id == item.id)),
                received_quantity=db.scalar(select(func.count()).select_from(PhysicalCard).where(PhysicalCard.submission_id == item.id)),
                status=state.status if state else 'awaiting_receipt', submitted_at=item.confirmed_at,
                commercially_accepted=db.get(QuoteAcceptance, item.id) is not None,
                operational_override=bool(state and state.override_reason), payment_status='not_implemented')


def detail(db, item):
    return {**summary(db, item),
        'entries': [encoded(e, 'id card_name game expansion card_number language quantity') for e in rows(db, SubmissionEntry, item.id)],
        'parcels': [encoded(p, 'id reference carrier tracking notes status received_by received_at updated_at') for p in rows(db, Parcel, item.id)],
        'cards': [encoded(c, 'id reference parcel_id entry_id notes status received_by received_at updated_at grading_card_id') for c in rows(db, PhysicalCard, item.id)],
        'discrepancies': [encoded(d, 'id card_id entry_id kind quantity notes status resolution created_by resolved_by created_at updated_at') for d in rows(db, Discrepancy, item.id)],
        'events': [encoded(e, 'id actor_id action entity_id data reason created_at') for e in rows(db, IntakeAudit, item.id)]}


@router.get('/me')
def me(request: Request, db: Db, settings: Config):
    actor = staff(request, db, settings)
    return {'id': actor.id, 'role': db.get(StaffMembership, actor.id).role, 'language': actor.preferred_language}


@router.get('/submissions')
def listing(request: Request, db: Db, settings: Config, search: str = Query('', max_length=40), status: str | None = None,
            limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    staff(request, db, settings)
    if status and status not in STATES:
        raise HTTPException(422, 'invalid_status')
    statement = select(Submission).outerjoin(Intake, Intake.submission_id == Submission.id).where(Submission.status == 'submitted')
    if search:
        statement = statement.where(Submission.reference.contains(search.upper(), autoescape=True))
    if status:
        statement = statement.where(func.coalesce(Intake.status, 'awaiting_receipt') == status)
    return [summary(db, item) for item in db.scalars(statement.order_by(Submission.confirmed_at.desc(), Submission.id).offset(offset).limit(limit))]


def submission(db, sid):
    item = db.scalar(select(Submission).where(Submission.id == sid, Submission.status == 'submitted').with_for_update())
    if item is None:
        raise HTTPException(404, 'submission_not_found')
    return item


@router.get('/submissions/{sid}')
def retrieve(sid: UUID, request: Request, db: Db, settings: Config):
    staff(request, db, settings)
    return detail(db, submission(db, sid))


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

    @field_validator('*')
    @classmethod
    def safe_text(cls, value, info):
        if isinstance(value, str):
            valid_unicode(value)
            allowed = {'\n', '\t', '\r'} if info.field_name in {'notes', 'reason'} else set()
            if any((ord(c) < 32 or ord(c) == 127) and c not in allowed for c in value):
                raise ValueError('Invalid control character')
        return value


class ParcelInput(Payload):
    request_key: UUID
    carrier: str = Field('', max_length=100)
    tracking: str = Field('', max_length=200)
    notes: str = Field('', max_length=2000)


class CardInput(Payload):
    request_key: UUID
    parcel_id: UUID
    notes: str = Field('', max_length=2000)


class MatchInput(Payload):
    entry_id: UUID | None
    reason: str = Field(min_length=1, max_length=1000)


class IssueInput(Payload):
    kind: Literal['missing','unexpected','mismatch','damaged','unresolved']
    entry_id: UUID | None = None
    card_id: UUID | None = None
    quantity: int = Field(1, ge=1, le=10000, strict=True)
    notes: str = Field(min_length=1, max_length=2000)


class Resolution(Payload):
    status: Literal['resolved','acknowledged']
    reason: str = Field(min_length=1, max_length=2000)


class Transition(Payload):
    action: Literal['begin','hold','resume','complete','override']
    reason: str = Field(min_length=1, max_length=1000)


def context(sid, request, db, settings):
    actor = staff(request, db, settings)
    item = submission(db, sid)
    state = db.get(Intake, sid)
    if state is None:
        state = Intake(submission_id=sid, status='awaiting_receipt')
        db.add(state)
        db.flush()
    return actor, item, state


def scoped(db, model, sid, identifier):
    row = db.get(model, identifier)
    if row is None or row.submission_id != sid:
        raise HTTPException(404, 'entity_not_found')
    return row


def transition(db, actor, state, target, reason):
    before = state.status
    state.status = target
    audit(db, actor, state.submission_id, 'intake_transition', state.submission_id, {'before': before, 'after': target}, reason)


def replay(db, model, sid, payload):
    data = payload.model_dump(mode='json', exclude={'request_key'})
    existing = db.scalar(select(model).where(model.submission_id == sid, model.request_key == payload.request_key))
    if existing and existing.request_data != data:
        raise HTTPException(409, 'idempotency_conflict')
    return existing, data


@router.post('/submissions/{sid}/parcels', status_code=201)
def register_parcel(sid: UUID, payload: ParcelInput, request: Request, db: Db, settings: Config):
    actor, item, state = context(sid, request, db, settings)
    existing, data = replay(db, Parcel, sid, payload)
    if existing:
        return {'id': existing.id, 'reference': existing.reference}
    if state.status in {'reconciled','on_hold'}:
        raise HTTPException(409, 'invalid_transition')
    identifier = uuid4()
    row = Parcel(id=identifier, reference='PI-'+identifier.hex.upper(), submission_id=sid, received_by=actor.id,
                 request_key=payload.request_key, request_data=data, **payload.model_dump(exclude={'request_key'}))
    db.add(row)
    audit(db, actor, sid, 'parcel_registered', identifier, {'reference': row.reference})
    transition(db, actor, state, 'partially_received', 'physical_receipt')
    db.commit()
    return {'id': row.id, 'reference': row.reference}


@router.post('/submissions/{sid}/cards', status_code=201)
def create_card(sid: UUID, payload: CardInput, request: Request, db: Db, settings: Config):
    actor, item, state = context(sid, request, db, settings)
    existing, data = replay(db, PhysicalCard, sid, payload)
    if existing:
        return {'id': existing.id, 'reference': existing.reference}
    if state.status != 'reconciliation_pending':
        raise HTTPException(409, 'begin_reconciliation_required')
    parcel = scoped(db, Parcel, sid, payload.parcel_id)
    identifier = uuid4()
    card = PhysicalCard(id=identifier, reference='PC-'+identifier.hex.upper(), submission_id=sid,
                        received_by=actor.id, request_key=payload.request_key, request_data=data,
                        **payload.model_dump(exclude={'request_key'}))
    db.add(card)
    parcel.status = 'reconciling'
    audit(db, actor, sid, 'physical_card_created', identifier, {'parcel_id': str(parcel.id), 'reference': card.reference})
    db.commit()
    return {'id': card.id, 'reference': card.reference}


def reconciling(state):
    if state.status != 'reconciliation_pending':
        raise HTTPException(409, 'begin_reconciliation_required')


@router.post('/submissions/{sid}/cards/{cid}/match')
def match(sid: UUID, cid: UUID, payload: MatchInput, request: Request, db: Db, settings: Config):
    actor, item, state = context(sid, request, db, settings)
    reconciling(state)
    card = scoped(db, PhysicalCard, sid, cid)
    if payload.entry_id:
        entry = scoped(db, SubmissionEntry, sid, payload.entry_id)
        count = db.scalar(select(func.count()).select_from(PhysicalCard).where(PhysicalCard.entry_id == entry.id, PhysicalCard.id != cid))
        if count >= entry.quantity:
            raise HTTPException(409, 'declared_quantity_exceeded')
    before = str(card.entry_id) if card.entry_id else None
    card.entry_id = payload.entry_id
    card.status = 'matched' if payload.entry_id else 'unidentified'
    audit(db, actor, sid, 'card_matched', cid, {'before': before, 'after': str(payload.entry_id) if payload.entry_id else None}, payload.reason)
    db.commit()
    return detail(db, item)


@router.post('/submissions/{sid}/discrepancies', status_code=201)
def discrepancy(sid: UUID, payload: IssueInput, request: Request, db: Db, settings: Config):
    actor, item, state = context(sid, request, db, settings)
    reconciling(state)
    if payload.entry_id:
        scoped(db, SubmissionEntry, sid, payload.entry_id)
    if payload.card_id:
        scoped(db, PhysicalCard, sid, payload.card_id)
    if payload.kind == 'missing' and (not payload.entry_id or payload.card_id):
        raise HTTPException(422, 'missing_requires_entry')
    if payload.kind != 'missing' and (not payload.card_id or payload.quantity != 1):
        raise HTTPException(422, 'discrepancy_requires_individual_card')
    identifier = uuid4()
    issue = Discrepancy(id=identifier, submission_id=sid, created_by=actor.id, **payload.model_dump())
    db.add(issue)
    audit(db, actor, sid, 'discrepancy_recorded', identifier, payload.model_dump(mode='json'))
    db.commit()
    return detail(db, item)


@router.post('/submissions/{sid}/discrepancies/{did}/resolve')
def resolve(sid: UUID, did: UUID, payload: Resolution, request: Request, db: Db, settings: Config):
    actor, item, state = context(sid, request, db, settings)
    reconciling(state)
    issue = scoped(db, Discrepancy, sid, did)
    if issue.status != 'open':
        raise HTTPException(409, 'discrepancy_closed')
    issue.status, issue.resolution, issue.resolved_by = payload.status, payload.reason, actor.id
    audit(db, actor, sid, 'discrepancy_resolved', did, {'before':'open', 'after':payload.status}, payload.reason)
    db.commit()
    return detail(db, item)


def validate_complete(db, sid):
    cards, entries, issues = rows(db, PhysicalCard, sid), rows(db, SubmissionEntry, sid), rows(db, Discrepancy, sid)
    if any(d.status == 'open' for d in issues):
        raise HTTPException(409, 'open_discrepancies')
    for entry in entries:
        missing = entry.quantity - sum(c.entry_id == entry.id for c in cards)
        acknowledged = sum(d.quantity for d in issues if d.kind == 'missing' and d.entry_id == entry.id and d.status == 'acknowledged')
        if missing != acknowledged:
            raise HTTPException(409, 'quantity_unreconciled')
    for card in cards:
        if card.entry_id is None and not any(d.card_id == card.id and d.kind in {'unexpected','mismatch','unresolved'} and d.status == 'acknowledged' for d in issues):
            raise HTTPException(409, 'unidentified_card')


@router.post('/submissions/{sid}/transition')
def change(sid: UUID, payload: Transition, request: Request, db: Db, settings: Config):
    actor, item, state = context(sid, request, db, settings)
    action = payload.action
    if state.status == 'reconciled':
        raise HTTPException(409, 'invalid_transition')
    if action == 'override':
        if db.get(StaffMembership, actor.id).role != 'admin':
            raise HTTPException(403, 'administrator_required')
        before = bool(state.override_reason)
        state.override_reason = payload.reason
        audit(db, actor, sid, 'operational_override', sid, {'before':before,'after':True, 'payment_status':'not_implemented'}, payload.reason)
    elif action == 'hold' and state.status != 'on_hold':
        transition(db, actor, state, 'on_hold', payload.reason)
    elif action == 'resume' and state.status == 'on_hold':
        transition(db, actor, state, 'partially_received' if rows(db, Parcel, sid) else 'awaiting_receipt', payload.reason)
    elif action == 'begin' and state.status == 'partially_received':
        # W4 has no payment evidence. Admin explicitly authorizes custody processing only.
        if not state.override_reason:
            raise HTTPException(409, 'operational_override_required')
        transition(db, actor, state, 'reconciliation_pending', payload.reason)
        for parcel in rows(db, Parcel, sid):
            parcel.status = 'reconciling'
    elif action == 'complete' and state.status == 'reconciliation_pending':
        validate_complete(db, sid)
        transition(db, actor, state, 'reconciled', payload.reason)
        for parcel in rows(db, Parcel, sid):
            parcel.status = 'reconciled'
    else:
        raise HTTPException(409, 'invalid_transition')
    db.commit()
    return detail(db, item)
