import hashlib
import io
import json
import logging
import os
import struct
import warnings
from email.message import Message
from email.utils import collapse_rfc2231_value
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database import get_session
from app.models import Card, CardImage
from app.schemas import CardCreate, CardRead, ImageRead

router = APIRouter(prefix="/api/cards")
logger = logging.getLogger("spectra.uploads")
Db = Annotated[Session, Depends(get_session)]
Config = Annotated[Settings, Depends(get_settings)]


def upload_log(event: str, card_id: UUID, side: str, **fields):
    logger.info(json.dumps({"event": event, "card_id": str(card_id), "side": side, **fields}))


def require_card(session: Session, card_id: UUID) -> Card:
    card = session.get(Card, card_id)
    if card is None:
        raise HTTPException(404, "Card not found")
    return card


@router.post("", response_model=CardRead, status_code=201)
def create_card(payload: CardCreate, session: Db):
    card = Card(**payload.model_dump())
    session.add(card)
    try:
        session.flush()
        result = CardRead.model_validate(card)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Card registration failed") from None
    return result


@router.get("/{card_id}", response_model=CardRead)
def get_card(card_id: UUID, session: Db):
    return require_card(session, card_id)


@router.get("/{card_id}/images", response_model=list[ImageRead])
def list_images(card_id: UUID, session: Db):
    require_card(session, card_id)
    return session.scalars(select(CardImage).where(CardImage.card_id == card_id).order_by(CardImage.uploaded_at, CardImage.id)).all()


def validate_image(data: bytes) -> str:
    formats = {"PNG": "image/png", "JPEG": "image/jpeg", "TIFF": "image/tiff"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                mime = formats.get(image.format)
                if mime is None:
                    raise ValueError("Unsupported format")
                image.verify()
            # Verify alone does not decode pixels; decode every frame as well.
            with Image.open(io.BytesIO(data)) as image:
                for frame in range(getattr(image, "n_frames", 1)):
                    image.seek(frame)
                    image.load()
        return mime
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, EOFError, struct.error, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "Invalid or unsupported image; use PNG, JPEG or TIFF") from None


def write_original(path: Path, data: bytes) -> None:
    # Exclusive creation prevents overwrites, including storage-key collisions.
    with path.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())


def validate_filename(file: UploadFile) -> str:
    filename = file.filename or ""
    candidates = [filename]
    # python-multipart strips legacy Windows absolute paths from file.filename.
    # Inspect the retained headers before that normalization can hide a path.
    for header in file.headers.getlist("content-disposition"):
        message = Message()
        message["content-disposition"] = header
        for name, value in message.get_params(header="content-disposition", failobj=[]):
            if name.lower() == "filename":
                candidates.append(collapse_rfc2231_value(value) if isinstance(value, tuple) else value)
    for candidate in candidates:
        if not candidate or len(candidate) > 255 or any(ord(c) < 32 for c in candidate) or any(c in candidate for c in '/\\:') or candidate in {".", ".."}:
            raise HTTPException(422, "Invalid original filename")
    return filename


@router.post("/{card_id}/images", response_model=ImageRead, status_code=201)
def upload_image(
    card_id: UUID,
    session: Db,
    settings: Config,
    side: Annotated[Literal["front", "back"], Form()],
    file: Annotated[UploadFile, File()],
):
    path = None
    created = False
    try:
        require_card(session, card_id)
        filename = validate_filename(file)
        data = file.file.read(settings.max_image_size_bytes + 1)
        if len(data) > settings.max_image_size_bytes:
            raise HTTPException(413, "Image exceeds maximum file size")
        mime = validate_image(data)
        image = CardImage(
            card_id=card_id, side=side, original_filename=filename,
            mime_type=mime, sha256=hashlib.sha256(data).hexdigest(),
            file_size=len(data), storage_key=uuid4().hex,
        )
        session.add(image)
        # Reserve the side before touching disk; the unique constraint handles races.
        session.flush()
        result = ImageRead.model_validate(image)
        settings.card_image_dir.mkdir(parents=True, exist_ok=True)
        path = settings.card_image_dir / image.storage_key
        # Mark only files this request created for cleanup, never existing files.
        try:
            write_original(path, data)
            created = True
        except FileExistsError:
            raise
        except OSError:
            created = path.exists()
            raise
        session.commit()
        upload_log("image_uploaded", card_id, side, image_id=str(result.id), sha256=result.sha256, file_size=result.file_size)
        return result
    except Exception as exc:
        session.rollback()
        if created and path is not None:
            try:
                path.unlink()
            except OSError:
                upload_log("image_cleanup_failed", card_id, side, storage_key=path.name)
        upload_log("image_upload_failed", card_id, side, error_type=type(exc).__name__)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, IntegrityError) and getattr(exc.orig, "sqlstate", None) == "23505" and getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_card_images_card_side":
            raise HTTPException(409, "An original image already exists for this side") from None
        raise HTTPException(503, "Image upload failed") from None
    finally:
        file.file.close()
