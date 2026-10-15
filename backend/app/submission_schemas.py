from typing import Annotated
from pydantic import Field, StringConstraints, AfterValidator
from app.auth_schemas import Payload, valid_unicode

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200, pattern=r'^[^\x00-\x1f\x7f]+$'), AfterValidator(valid_unicode)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64, pattern=r'^[^\x00-\x1f\x7f]+$'), AfterValidator(valid_unicode)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000, pattern=r'^[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]*$'), AfterValidator(valid_unicode)]
GAMES = ('pokemon', 'one-piece', 'dragon-ball', 'naruto')

class Version(Payload):
    version: int = Field(ge=1, strict=True)

class Details(Version):
    notes: Notes = ''

class Entry(Version):
    game: ShortText
    card_name: Text
    expansion: Text
    card_number: ShortText
    language: ShortText
    quantity: int = Field(default=1, ge=1, le=100, strict=True)
    notes: Notes = ''
    processing_tier: ShortText = 'standard'
    upgrade_ids: list[ShortText] = Field(default_factory=lambda: ['classic'], min_length=1, max_length=16)
