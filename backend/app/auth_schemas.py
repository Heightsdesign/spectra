import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, BeforeValidator, AfterValidator


def normalize_email(value):
    if not isinstance(value, str):
        raise ValueError("Invalid email")
    value = value.strip().lower()
    if len(value) > 254 or value.count("@") != 1:
        raise ValueError("Invalid email")
    local, domain = value.split("@")
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("Invalid email") from None
    if not 1 <= len(local) <= 64 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+", local) or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Invalid email")
    labels = domain.split(".")
    if len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in labels) or len(local + "@" + domain) > 254:
        raise ValueError("Invalid email")
    return local + "@" + domain


def valid_unicode(value):
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Invalid text encoding") from None
    return value


Email = Annotated[str, BeforeValidator(normalize_email)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128), AfterValidator(valid_unicode)]
ExistingPassword = Annotated[str, StringConstraints(min_length=1, max_length=128), AfterValidator(valid_unicode)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$"), AfterValidator(valid_unicode)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Registration(Payload):
    email: Email
    password: Password = Field(repr=False)
    first_name: Name
    last_name: Name
    preferred_language: Literal["FR", "EN"] = "FR"


class Login(Payload):
    email: Email
    password: ExistingPassword = Field(repr=False)


class EmailRequest(Payload):
    email: Email


class TokenRequest(Payload):
    token: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")] = Field(repr=False)


class Reset(TokenRequest):
    password: Password = Field(repr=False)


class PasswordChange(Payload):
    current_password: ExistingPassword = Field(repr=False)
    new_password: Password = Field(repr=False)


class Profile(Payload):
    first_name: Name
    last_name: Name
    preferred_language: Literal["FR", "EN"]
