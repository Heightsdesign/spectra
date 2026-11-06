"""Private inspection commands serialize on the same submission lock as intake."""
import base64
import binascii
import hashlib
import logging
from datetime import datetime, timezone
from typing import Literal, Annotated
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import select
from app.auth import write_guard
from app.cards import Db, Config, validate_image, write_original
from app.customer_operations import require_staff
from app.intake import Payload, encoded
from app.intake_models import PhysicalCard
from app.intake_voids import PhysicalCardVoid
from app.submission_models import Submission, SubmissionEntry
from app.physical_identity import parse_scan
from app.inspection_models import Inspection, CustodyEvent, InspectionImage
from app.inspection_commercial import commercial_provider
from app.inspection_eligibility import eligibility

router = APIRouter(prefix='/internal/inspection', dependencies=[Depends(write_guard), Depends(require_staff)], include_in_schema=False)
logger = logging.getLogger('spectra.inspection')
Actor = Annotated[object, Depends(require_staff)]
Commerce = Annotated[object, Depends(commercial_provider)]

def resolve(db, reference, lock=False):
    try: reference = parse_scan(reference)
    except ValueError: raise HTTPException(422, 'invalid_card_reference') from None
    card = db.scalar(select(PhysicalCard).where(PhysicalCard.reference == reference))
    if not card: raise HTTPException(404, 'card_not_found')
    submission = db.scalar(select(Submission).where(Submission.id == card.submission_id).with_for_update()) if lock else db.get(Submission, card.submission_id)
    if lock: db.refresh(card)
    dossier = db.scalar(select(Inspection).where(Inspection.physical_card_id == card.id))
    return card, submission, dossier

def view(db, card, submission, dossier, provider):
    entry = db.get(SubmissionEntry, card.entry_id) if card.entry_id else None
    return {'card': {**encoded(card, 'id reference submission_id entry_id'), 'lifecycle_status': 'voided' if db.get(PhysicalCardVoid, card.id) else card.status}, 'submission': encoded(submission, 'id reference customer_id'), 'entry': encoded(entry, 'card_name expansion card_number language') if entry else None,
        'inspection': encoded(dossier, 'id status location version started_by created_at started_at transitioned_at') if dossier else None,
        'eligibility': {op: eligibility(db, card, provider, op, dossier) for op in ('start','pause','resume','image')},
        'custody': [{**encoded(e, 'id inspection_id actor_id action previous_state new_state source destination reason created_at'), 'physical_card_reference': card.reference} for e in db.scalars(select(CustodyEvent).where(CustodyEvent.inspection_id == dossier.id).order_by(CustodyEvent.created_at, CustodyEvent.id))] if dossier else [],
        'images': [encoded(i, 'id side version sha256 file_size uploaded_by uploaded_at') for i in db.scalars(select(InspectionImage).where(InspectionImage.inspection_id == dossier.id).order_by(InspectionImage.side, InspectionImage.version))] if dossier else []}

@router.get('/lookup')
def lookup(db: Db, actor: Actor, provider: Commerce, reference: str = Query(max_length=100)):
    return view(db, *resolve(db, reference), provider)

class Command(Payload):
    request_key: UUID
    version: int = Field(ge=0, strict=True)
    action: Literal['start','pause','resume']
    reason: str = Field(min_length=1, max_length=1000)

@router.post('/{reference}/command')
def command(reference: str, payload: Command, db: Db, actor: Actor, provider: Commerce):
    card, submission, dossier = resolve(db, reference, True)
    if dossier:
        replay = db.scalar(select(CustodyEvent).where(CustodyEvent.inspection_id == dossier.id, CustodyEvent.request_key == payload.request_key))
        if replay:
            if replay.action != payload.action or replay.reason != payload.reason: raise HTTPException(409, 'idempotency_conflict')
            return view(db, card, submission, dossier, provider)
    result = eligibility(db, card, provider, payload.action, dossier)
    if not result['eligible']: raise HTTPException(409, result)
    if payload.version != (dossier.version if dossier else 0): raise HTTPException(409, 'stale_version')
    before = dossier.status if dossier else 'not_started'
    source = dossier.location if dossier else 'secure_intake_storage'
    if not dossier:
        dossier = Inspection(physical_card_id=card.id, started_by=actor.id)
        db.add(dossier)
        db.flush()
    else: dossier.version += 1
    dossier.status = 'paused' if payload.action == 'pause' else 'in_progress'
    dossier.location = 'inspection_hold_storage' if payload.action == 'pause' else 'inspection_workstation'
    dossier.transitioned_at = datetime.now(timezone.utc)
    db.add(CustodyEvent(inspection_id=dossier.id, actor_id=actor.id, request_key=payload.request_key, action=payload.action, previous_state=before, new_state=dossier.status, source=source, destination=dossier.location, reason=payload.reason, created_at=dossier.transitioned_at))
    db.flush()
    result = view(db, card, submission, dossier, provider)
    db.commit()
    return result

class ImageInput(Payload):
    inspection_id: UUID
    version: int = Field(ge=1, strict=True)
    side: Literal['front','back']
    filename: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    data: str = Field(max_length=35_000_000)
    reason: str = Field(min_length=1, max_length=1000)

@router.post('/{reference}/images')
def image(reference: str, payload: ImageInput, db: Db, settings: Config, actor: Actor, provider: Commerce):
    card, submission, dossier = resolve(db, reference, True)
    result = eligibility(db, card, provider, 'image', dossier)
    if not result['eligible']: raise HTTPException(409, result)
    if dossier.id != payload.inspection_id: raise HTTPException(409, 'cross_card_attachment')
    if dossier.version != payload.version: raise HTTPException(409, 'stale_version')
    if any(c in payload.filename for c in '/\\:') or payload.filename in {'.','..'}: raise HTTPException(422, 'invalid_filename')
    maximum = min(settings.max_image_size_bytes, 25 * 1024 * 1024)
    if len(payload.data) > ((maximum + 2) // 3) * 4: raise HTTPException(413, 'image_too_large')
    try: data = base64.b64decode(payload.data, validate=True)
    except (ValueError, binascii.Error): raise HTTPException(422, 'invalid_image') from None
    if len(data) > maximum: raise HTTPException(413, 'image_too_large')
    digest = hashlib.sha256(data).hexdigest()
    if digest != payload.sha256: raise HTTPException(422, 'integrity_mismatch')
    mime = validate_image(data)
    previous = list(db.scalars(select(InspectionImage).where(InspectionImage.inspection_id == dossier.id, InspectionImage.side == payload.side)))
    evidence = InspectionImage(inspection_id=dossier.id, side=payload.side, version=len(previous)+1, uploaded_by=actor.id, original_filename=payload.filename, mime_type=mime, sha256=digest, file_size=len(data), storage_key=uuid4().hex, reason=payload.reason, uploaded_at=datetime.now(timezone.utc))
    db.add(evidence)
    dossier.version += 1
    db.flush()
    path = settings.card_image_dir / evidence.storage_key
    created = False
    try:
        settings.card_image_dir.mkdir(parents=True, exist_ok=True)
        try:
            write_original(path, data)
            created = True
        except FileExistsError:
            raise
        except OSError:
            created = path.exists()
            raise
        db.commit()
    except Exception as exc:
        db.rollback()
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.error('inspection_image_cleanup_failed')
        if isinstance(exc, OSError):
            raise HTTPException(503, 'image_storage_unavailable') from None
        raise
    return view(db, card, submission, dossier, provider)

@router.get('/{reference}/images/{image_id}')
def original_image(reference: str, image_id: UUID, db: Db, settings: Config, actor: Actor):
    from fastapi.responses import Response
    card, submission, dossier = resolve(db, reference)
    evidence = db.get(InspectionImage, image_id)
    if not dossier or not evidence or evidence.inspection_id != dossier.id:
        raise HTTPException(404, 'image_not_found')
    try: data = (settings.card_image_dir / evidence.storage_key).read_bytes()
    except OSError: raise HTTPException(503, 'image_unavailable') from None
    if len(data) != evidence.file_size or hashlib.sha256(data).hexdigest() != evidence.sha256:
        raise HTTPException(409, 'image_integrity_failure')
    return Response(data, media_type=evidence.mime_type, headers={'Content-Disposition': 'inline', 'Cache-Control': 'private, no-store'})
