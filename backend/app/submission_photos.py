"""Optional customer originals using existing private image storage primitives."""
import base64
import binascii
import hashlib
import io
import logging
import warnings
from typing import Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError
from pydantic import Field
from sqlalchemy import select
from app.auth import write_guard, now
from app.cards import Db, Config, validate_image, write_original
from app.submission_models import SubmissionEntry, SubmissionPhoto
from app.submission_schemas import Version, Text
from app.submissions import owned, editable, entry_for, save, public

router = APIRouter(prefix='/api/submissions', dependencies=[Depends(write_guard)])
MAX_BYTES = 8 * 1024 * 1024
logger = logging.getLogger('spectra.uploads')


class PhotoInput(Version):
    copy_number: int = Field(ge=1, le=100, strict=True)
    side: Literal['front', 'back']
    filename: Text
    data: str = Field(max_length=((MAX_BYTES + 2) // 3) * 4)


def photo_public(photo):
    return {**{key: getattr(photo, key) for key in ('id', 'entry_id', 'copy_number', 'side',
            'uploaded_by', 'uploaded_at', 'original_filename', 'mime_type', 'sha256', 'file_size')},
            'provenance': 'customer_pre_shipment', 'identity_verified': False}


def photo_list(db, entry_id):
    return [photo_public(photo) for photo in db.scalars(select(SubmissionPhoto).where(
        SubmissionPhoto.entry_id == entry_id, SubmissionPhoto.removed_at.is_(None)
    ).order_by(SubmissionPhoto.copy_number, SubmissionPhoto.side, SubmissionPhoto.id))]


def scoped_photo(db, entry_id, photo_id):
    photo = db.get(SubmissionPhoto, photo_id)
    if photo is None or photo.entry_id != entry_id or photo.removed_at is not None:
        raise HTTPException(404, 'photo_not_found')
    return photo


def image_bytes(payload, settings):
    if any(c in payload.filename for c in '/\\:') or payload.filename in {'.', '..'}:
        raise HTTPException(422, 'invalid_filename')
    maximum = min(settings.max_image_size_bytes, MAX_BYTES)
    if len(payload.data) > ((maximum + 2) // 3) * 4:
        raise HTTPException(413, 'photo_too_large')
    try:
        data = base64.b64decode(payload.data, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, 'invalid_photo') from None
    if len(data) > maximum:
        raise HTTPException(413, 'photo_too_large')
    # Bound decoded pixels and reject animation/unsupported types before full decoding.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {'JPEG', 'PNG'} or getattr(image, 'n_frames', 1) != 1 or image.width * image.height > 20_000_000:
                    raise ValueError()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise HTTPException(422, 'invalid_photo') from None
    return data, validate_image(data)


@router.post('/{identifier}/entries/{entry_id}/photos', status_code=201)
def upload(identifier: UUID, entry_id: UUID, payload: PhotoInput, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)  # Same lock as entry edits and confirmation.
    editable(item, payload.version)
    entry = entry_for(item, entry_id, db)
    if payload.copy_number > entry.quantity:
        raise HTTPException(422, 'photo_copy_out_of_range')
    data, mime = image_bytes(payload, settings)
    previous = db.scalar(select(SubmissionPhoto).where(SubmissionPhoto.entry_id == entry_id,
        SubmissionPhoto.copy_number == payload.copy_number, SubmissionPhoto.side == payload.side,
        SubmissionPhoto.removed_at.is_(None)))
    if previous:
        previous.removed_at = now()
        db.flush()
    photo = SubmissionPhoto(entry_id=entry_id, copy_number=payload.copy_number, side=payload.side,
        uploaded_by=item.customer_id, original_filename=payload.filename, mime_type=mime,
        sha256=hashlib.sha256(data).hexdigest(), file_size=len(data), storage_key=uuid4().hex)
    db.add(photo)
    path = settings.card_image_dir / photo.storage_key
    created = False
    try:
        db.flush()
        settings.card_image_dir.mkdir(parents=True, exist_ok=True)
        try:
            write_original(path, data)
            created = True
        except FileExistsError:
            raise
        except OSError:
            created = path.exists()
            raise
        # Photos do not alter quantity/options or invalidate an accepted price calculation.
        save(item, db, invalidate_pricing=False, serialize=False)
    except Exception as exc:
        db.rollback()
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.error('submission_photo_cleanup_failed')
        if isinstance(exc, OSError):
            raise HTTPException(503, 'photo_storage_unavailable') from None
        raise
    return public(item, db)


@router.delete('/{identifier}/entries/{entry_id}/photos/{photo_id}')
def remove(identifier: UUID, entry_id: UUID, photo_id: UUID, payload: Version, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    entry_for(item, entry_id, db)
    scoped_photo(db, entry_id, photo_id).removed_at = now()
    return save(item, db, invalidate_pricing=False)


def photo_content(photo, settings):
    try:
        with (settings.card_image_dir / photo.storage_key).open('rb') as original:
            data = original.read(MAX_BYTES + 1)
    except OSError:
        raise HTTPException(503, 'photo_unavailable') from None
    if len(data) != photo.file_size or hashlib.sha256(data).hexdigest() != photo.sha256:
        raise HTTPException(409, 'photo_integrity_failure')
    return Response(data, media_type=photo.mime_type, headers={'Content-Disposition': 'inline',
        'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/{identifier}/entries/{entry_id}/photos/{photo_id}')
def original(identifier: UUID, entry_id: UUID, photo_id: UUID, request: Request, db: Db, settings: Config):
    item = owned(identifier, request, db, settings)
    entry_for(item, entry_id, db)
    return photo_content(scoped_photo(db, entry_id, photo_id), settings)
