"""Customer entries are deliberately independent from internal grading cards."""
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from app.auth import authenticated, write_guard, now
from app.cards import Db, Config
from app.auth_schemas import Payload
from app.submission_models import Submission, SubmissionEntry
from app.submission_schemas import Version, Details, Entry, GAMES
from app.pricing import current_catalog, validate_options, validate_selection

router = APIRouter(prefix='/api/submissions', dependencies=[Depends(write_guard)])
TRANSITIONS = {'draft': {'submitted'}, 'submitted': set()}

def owner(request, db, settings):
    return authenticated(request, db, settings, write=request.method != 'GET')[0]

def owned(identifier, request, db, settings):
    customer = owner(request, db, settings)
    item = db.scalar(select(Submission).where(Submission.id == identifier, Submission.customer_id == customer.id).with_for_update().execution_options(populate_existing=True))
    if item is None:
        raise HTTPException(404, 'submission_not_found')
    return item

def entries(item, db):
    return db.scalars(select(SubmissionEntry).where(SubmissionEntry.submission_id == item.id).order_by(SubmissionEntry.created_at, SubmissionEntry.id)).all()

def public(item, db):
    cards = entries(item, db)
    return {**{key: getattr(item, key) for key in ('id', 'reference', 'status', 'notes', 'version', 'created_at', 'updated_at', 'confirmed_at')},
            'card_count': sum(c.quantity for c in cards),
            'entries': [{key: getattr(c, key) for key in ('id', 'game', 'card_name', 'expansion', 'card_number', 'language', 'quantity', 'notes', 'processing_tier', 'upgrade_ids')} for c in cards]}

def editable(item, version):
    if item.status != 'draft':
        raise HTTPException(409, 'submission_immutable')
    if item.version != version:
        raise HTTPException(409, 'submission_conflict')

def save(item, db, invalidate_pricing=True):
    item.version += 1
    if invalidate_pricing:
        item.pricing_revision += 1
    item.updated_at = now()
    db.commit()
    return public(item, db)

@router.post('', status_code=201)
def create(payload: Payload, request: Request, db: Db, settings: Config):
    customer = owner(request, db, settings)
    identifier = uuid4()
    item = Submission(id=identifier, customer_id=customer.id, reference='SP-' + identifier.hex.upper())
    db.add(item)
    db.commit()
    return public(item, db)

@router.get('')
def listing(request: Request, db: Db, settings: Config, offset: int = 0, limit: int = 50):
    customer = owner(request, db, settings)
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, 'invalid_input')
    items = db.scalars(select(Submission).where(Submission.customer_id == customer.id).order_by(Submission.created_at.desc(), Submission.id).offset(offset).limit(limit)).all()
    return [public(item, db) for item in items]

@router.get('/{identifier}')
def retrieve(identifier: UUID, request: Request, db: Db, settings: Config):
    return public(owned(identifier, request, db, settings), db)

@router.patch('/{identifier}')
def details(identifier: UUID, payload: Details, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    item.notes = payload.notes
    return save(item, db)

@router.post('/{identifier}/entries', status_code=201)
def add(identifier: UUID, payload: Entry, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    if payload.game not in GAMES:
        raise HTTPException(422, 'invalid_input')
    if len(entries(item, db)) >= 100:
        raise HTTPException(422, 'entry_limit')
    validate_selection(db, settings, payload.processing_tier, payload.upgrade_ids,
                       required=bool({'processing_tier', 'upgrade_ids'} & payload.model_fields_set))
    db.add(SubmissionEntry(submission_id=item.id, **payload.model_dump(exclude={'version'})))
    return save(item, db)

def entry_for(item, entry_id, db):
    entry = db.scalar(select(SubmissionEntry).where(SubmissionEntry.id == entry_id, SubmissionEntry.submission_id == item.id))
    if entry is None:
        raise HTTPException(404, 'submission_not_found')
    return entry

@router.put('/{identifier}/entries/{entry_id}')
def update_entry(identifier: UUID, entry_id: UUID, payload: Entry, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    if payload.game not in GAMES:
        raise HTTPException(422, 'invalid_input')
    entry = entry_for(item, entry_id, db)
    # W3.1 clients omit new configuration fields; preserve those existing choices.
    omitted = {'processing_tier', 'upgrade_ids'} - payload.model_fields_set
    values = payload.model_dump(exclude={'version'} | omitted)
    validate_selection(db, settings, values.get('processing_tier', entry.processing_tier),
                       values.get('upgrade_ids', entry.upgrade_ids), required=False)
    for key, value in values.items():
        setattr(entry, key, value)
    return save(item, db)

@router.delete('/{identifier}/entries/{entry_id}')
def remove(identifier: UUID, entry_id: UUID, payload: Version, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    db.delete(entry_for(item, entry_id, db))
    return save(item, db)

@router.post('/{identifier}/confirm')
def confirm(identifier: UUID, payload: Version, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    if item.status == 'submitted':
        return public(item, db)  # Idempotent retry: no new timestamps or side effects.
    editable(item, payload.version)
    cards = entries(item, db)
    if not cards:
        raise HTTPException(422, 'submission_empty')
    configured = current_catalog(db, settings, required=False)
    if configured:
        for card in cards:
            validate_options(configured[1], card.processing_tier, card.upgrade_ids)
    if 'submitted' not in TRANSITIONS.get(item.status, set()):
        raise HTTPException(409, 'submission_immutable')
    item.status = 'submitted'
    item.confirmed_at = now()
    return save(item, db, invalidate_pricing=False)
