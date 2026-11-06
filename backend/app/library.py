"""Customer-declared copy library and transactional draft reservation."""

import hashlib
import logging
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select

from app.auth import now, write_guard
from app.auth_schemas import Payload
from app.cards import Config, Db, write_original
from app.inspection_models import Inspection
from app.intake import Payload as IntakePayload
from app.intake import audit, staff, submission
from app.intake_models import Intake, PhysicalCard, StaffMembership
from app.library_models import CopyAssignment, CustomerCopy
from app.pricing import common_configuration, current_catalog, validate_selection
from app.submission_models import SubmissionEntry, SubmissionPhoto
from app.submission_photos import PhotoInput, image_bytes, photo_content, photo_public
from app.submission_schemas import (
    GAMES,
    Notes,
    OptionalShortText,
    OptionalText,
    ShortText,
    Text,
    Version,
)
from app.submissions import editable, entries, owned, owner, public, save
from app.tcg_api import validate_catalog_entry

router = APIRouter(prefix="/api/library", dependencies=[Depends(write_guard)])
orders = APIRouter(prefix="/api/submissions", dependencies=[Depends(write_guard)])
staff_router = APIRouter(
    prefix="/internal/intake",
    dependencies=[Depends(write_guard)],
    include_in_schema=False,
)
DECLARATION = (
    "catalog_card_id",
    "game",
    "card_name",
    "expansion",
    "card_number",
    "language",
    "notes",
)
logger = logging.getLogger("spectra.uploads")


class CopyInput(Payload):
    catalog_card_id: UUID | None = None
    game: ShortText
    card_name: Text
    expansion: OptionalText = ""
    card_number: OptionalShortText = ""
    language: ShortText
    notes: Notes = ""


class CopyUpdate(CopyInput, Version):
    pass


class OrderRegistration(CopyInput, Version):
    quantity: int = Field(default=1, ge=1, le=100, strict=True)


class Assign(Version):
    copy_id: UUID


class CopyPhotoInput(PhotoInput):
    copy_number: Literal[1] = 1


class ReturnInput(IntakePayload):
    reason: str = Field(min_length=1, max_length=900)


@staff_router.post("/submissions/{sid}/library-copies/{copy_id}/return")
def confirm_return(
    sid: UUID,
    copy_id: UUID,
    payload: ReturnInput,
    request: Request,
    db: Db,
    settings: Config,
):
    actor = staff(request, db, settings)
    if db.get(StaffMembership, actor.id).role != "admin":
        raise HTTPException(403, "administrator_required")
    item = submission(db, sid)
    copy = get_copy(db, copy_id, item.customer_id)
    assignment = db.scalar(
        select(CopyAssignment)
        .where(
            CopyAssignment.copy_id == copy.id,
            CopyAssignment.submission_id == sid,
            CopyAssignment.entry_id.is_not(None),
        )
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(404, "copy_not_found")
    if assignment.released_at:
        return {"released": True, "copy_id": copy.id}
    state = db.get(Intake, sid)
    cards = list(
        db.scalars(
            select(PhysicalCard).where(
                PhysicalCard.submission_id == sid,
                PhysicalCard.entry_id == assignment.entry_id,
            )
        )
    )
    if (
        not state
        or state.status != "reconciled"
        or len(cards) != 1
        or cards[0].status != "matched"
        or cards[0].grading_card_id is not None
    ):
        raise HTTPException(409, "return_not_ready")
    if db.scalar(
        select(Inspection.id).where(Inspection.physical_card_id == cards[0].id)
    ):
        raise HTTPException(409, "inspection_return_workflow_required")
    assignment.released_at = now()
    assignment.released_by = actor.id
    assignment.release_reason = "returned_to_customer: " + payload.reason
    audit(
        db,
        actor,
        sid,
        "customer_copy_returned",
        copy.id,
        {"entry_id": str(assignment.entry_id), "physical_card_id": str(cards[0].id)},
        payload.reason,
    )
    db.commit()
    return {"released": True, "copy_id": copy.id}


def get_copy(db, identifier, customer_id):
    copy = db.scalar(
        select(CustomerCopy)
        .where(CustomerCopy.id == identifier, CustomerCopy.customer_id == customer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if copy is None:
        raise HTTPException(404, "copy_not_found")
    return copy


def active_assignment(db, identifier):
    return db.scalar(
        select(CopyAssignment).where(
            CopyAssignment.copy_id == identifier, CopyAssignment.released_at.is_(None)
        )
    )


def available(db, copy, version=None):
    if active_assignment(db, copy.id):
        raise HTTPException(409, "copy_unavailable")
    if version is not None and copy.version != version:
        raise HTTPException(409, "copy_conflict")


def photos(db, identifier):
    return list(
        db.scalars(
            select(SubmissionPhoto)
            .where(
                SubmissionPhoto.customer_copy_id == identifier,
                SubmissionPhoto.removed_at.is_(None),
            )
            .order_by(SubmissionPhoto.side, SubmissionPhoto.id)
        )
    )


def copy_public(db, copy):
    assignment = active_assignment(db, copy.id)
    return {
        **{
            key: getattr(copy, key)
            for key in ("id", "version", "created_at", *DECLARATION)
        },
        "reference": "CC-" + copy.id.hex.upper(),
        "available": assignment is None,
        "active_submission_id": assignment.submission_id if assignment else None,
        "identity_verified": False,
        "pre_shipment_photos": [photo_public(p) for p in photos(db, copy.id)],
    }


def new_copy(db, customer_id, values):
    values = {key: values.get(key) for key in DECLARATION}
    if values["game"] not in GAMES:
        raise HTTPException(422, "invalid_input")
    validate_catalog_entry(db, values)
    copy = CustomerCopy(customer_id=customer_id, **values)
    db.add(copy)
    db.flush()
    return copy


@router.get("/copies")
def listing(
    request: Request,
    db: Db,
    settings: Config,
    search: str = Query("", max_length=200),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    customer = owner(request, db, settings)
    query = select(CustomerCopy).where(CustomerCopy.customer_id == customer.id)
    if search.strip():
        query = query.where(
            CustomerCopy.card_name.icontains(search.strip(), autoescape=True)
            | CustomerCopy.expansion.icontains(search.strip(), autoescape=True)
        )
    rows = list(
        db.scalars(
            query.order_by(CustomerCopy.created_at.desc(), CustomerCopy.id)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return {
        "items": [copy_public(db, c) for c in rows[:limit]],
        "has_more": len(rows) > limit,
    }


@router.post("/copies", status_code=201)
def create(payload: CopyInput, request: Request, db: Db, settings: Config):
    customer = owner(request, db, settings)
    copy = new_copy(db, customer.id, payload.model_dump())
    db.commit()
    return copy_public(db, copy)


@router.put("/copies/{identifier}")
def update(
    identifier: UUID, payload: CopyUpdate, request: Request, db: Db, settings: Config
):
    copy = get_copy(db, identifier, owner(request, db, settings).id)
    available(db, copy, payload.version)
    values = payload.model_dump(exclude={"version"})
    if values["game"] not in GAMES:
        raise HTTPException(422, "invalid_input")
    validate_catalog_entry(db, values)
    for key, value in values.items():
        setattr(copy, key, value)
    copy.version += 1
    db.commit()
    return copy_public(db, copy)


def clone_photos(db, copy, entry, settings, created):
    for original in photos(db, copy.id):
        data = photo_content(
            original, settings
        ).body  # Existing hash/size/private-original validation.
        key = uuid4().hex
        path = settings.card_image_dir / key
        write_private(path, data, created)
        db.add(
            SubmissionPhoto(
                entry_id=entry.id,
                copy_number=1,
                side=original.side,
                uploaded_by=original.uploaded_by,
                uploaded_at=original.uploaded_at,
                original_filename=original.original_filename,
                mime_type=original.mime_type,
                sha256=original.sha256,
                file_size=original.file_size,
                storage_key=key,
            )
        )


def attach(db, item, copy, settings, created):
    available(db, copy)
    current = entries(item, db)
    if len(current) >= 100:
        raise HTTPException(422, "entry_limit")
    configuration = common_configuration(current)
    configured = current_catalog(db, settings, required=False)
    unselected = bool(current and configuration is None) or bool(configured and configured[1].schema_version == 2)
    configuration = configuration or {
        "processing_tier": "" if unselected else "standard",
        "upgrade_ids": ["classic"],
    }
    validate_selection(
        db,
        settings,
        tier_id=configuration["processing_tier"], upgrade_ids=configuration["upgrade_ids"],
        required=False,
    )
    entry = SubmissionEntry(
        submission_id=item.id,
        quantity=1,
        **configuration,
        **{key: getattr(copy, key) for key in DECLARATION},
    )
    db.add(entry)
    db.flush()
    db.add(CopyAssignment(copy_id=copy.id, submission_id=item.id, entry_id=entry.id))
    db.flush()
    clone_photos(db, copy, entry, settings, created)


def cleanup(created):
    for path in created:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.error("library_photo_cleanup_failed")


def write_private(path, data, created):
    try:
        write_original(path, data)
    except FileExistsError:
        raise
    except OSError:
        if path.exists():
            created.append(path)
        raise
    else:
        created.append(path)


@orders.post("/{identifier}/library-copies", status_code=201)
def assign(
    identifier: UUID, payload: Assign, request: Request, db: Db, settings: Config
):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    copy = get_copy(db, payload.copy_id, item.customer_id)
    created = []
    try:
        attach(db, item, copy, settings, created)
        save(item, db, serialize=False)
    except Exception as exc:
        db.rollback()
        cleanup(created)
        if isinstance(exc, OSError):
            raise HTTPException(503, "photo_storage_unavailable") from None
        raise
    return public(item, db)


@orders.post("/{identifier}/library-register", status_code=201)
def register_in_order(
    identifier: UUID,
    payload: OrderRegistration,
    request: Request,
    db: Db,
    settings: Config,
):
    item = owned(identifier, request, db, settings)
    editable(item, payload.version)
    if len(entries(item, db)) + payload.quantity > 100:
        raise HTTPException(422, "entry_limit")
    created = []
    try:
        for _ in range(payload.quantity):
            copy = new_copy(db, item.customer_id, payload.model_dump())
            attach(db, item, copy, settings, created)
        save(item, db, serialize=False)
    except Exception as exc:
        db.rollback()
        cleanup(created)
        if isinstance(exc, OSError):
            raise HTTPException(503, "photo_storage_unavailable") from None
        raise
    return public(item, db)


@router.post("/copies/{identifier}/photos", status_code=201)
def upload(
    identifier: UUID,
    payload: CopyPhotoInput,
    request: Request,
    db: Db,
    settings: Config,
):
    copy = get_copy(db, identifier, owner(request, db, settings).id)
    available(db, copy, payload.version)
    data, mime = image_bytes(payload, settings)
    previous = db.scalar(
        select(SubmissionPhoto).where(
            SubmissionPhoto.customer_copy_id == copy.id,
            SubmissionPhoto.side == payload.side,
            SubmissionPhoto.removed_at.is_(None),
        )
    )
    if previous:
        previous.removed_at = now()
        db.flush()
    photo = SubmissionPhoto(
        customer_copy_id=copy.id,
        copy_number=1,
        side=payload.side,
        uploaded_by=copy.customer_id,
        original_filename=payload.filename,
        mime_type=mime,
        sha256=hashlib.sha256(data).hexdigest(),
        file_size=len(data),
        storage_key=uuid4().hex,
    )
    path = settings.card_image_dir / photo.storage_key
    created = []
    try:
        settings.card_image_dir.mkdir(parents=True, exist_ok=True)
        write_private(path, data, created)
        db.add(photo)
        copy.version += 1
        db.commit()
    except Exception as exc:
        db.rollback()
        cleanup(created)
        if isinstance(exc, OSError):
            raise HTTPException(503, "photo_storage_unavailable") from None
        raise
    return copy_public(db, copy)


@router.get("/copies/{identifier}/photos/{photo_id}")
def view_photo(
    identifier: UUID, photo_id: UUID, request: Request, db: Db, settings: Config
):
    copy = get_copy(db, identifier, owner(request, db, settings).id)
    photo = db.get(SubmissionPhoto, photo_id)
    if not photo or photo.customer_copy_id != copy.id or photo.removed_at:
        raise HTTPException(404, "photo_not_found")
    return photo_content(photo, settings)


@router.delete("/copies/{identifier}/photos/{photo_id}")
def remove_photo(
    identifier: UUID,
    photo_id: UUID,
    payload: Version,
    request: Request,
    db: Db,
    settings: Config,
):
    copy = get_copy(db, identifier, owner(request, db, settings).id)
    available(db, copy, payload.version)
    photo = db.get(SubmissionPhoto, photo_id)
    if not photo or photo.customer_copy_id != copy.id or photo.removed_at:
        raise HTTPException(404, "photo_not_found")
    photo.removed_at = now()
    copy.version += 1
    db.commit()
    return copy_public(db, copy)
