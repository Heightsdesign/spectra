from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CollectorNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


def as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


# Normalize database session offsets without changing the recorded instant.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(as_utc)]


class CardCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game: Literal["pokemon"] = "pokemon"
    card_name: Name
    set_name: Name
    collector_number: CollectorNumber


class CardRead(CardCreate):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: Literal["registered"]
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ImageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    side: Literal["front", "back"]
    original_filename: str
    mime_type: str
    sha256: str
    file_size: int
    uploaded_at: UtcDatetime
