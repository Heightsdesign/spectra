"""Replaceable mail adapter. Development links are private local artifacts."""
import json
import os
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.config import Settings


class EmailDelivery(Protocol):
    def send(self, recipient: str, purpose: str, link: str, language: str) -> None: ...


class LocalEmailDelivery:
    def __init__(self, folder: Path):
        self.folder = folder

    def send(self, recipient, purpose, link, language):
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.folder / f"{uuid4().hex}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"recipient": recipient, "purpose": purpose, "language": language, "link": link}, stream)
                stream.flush()
                os.fsync(stream.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise


def get_email_delivery(settings: Settings) -> EmailDelivery:
    if settings.auth_environment != "development":
        raise RuntimeError("Production email provider is not configured")
    root = settings.auth_mail_dir.resolve()
    for other in (settings.card_image_dir.resolve(), settings.boundary_output_dir.resolve()):
        if root == other or root in other.parents or other in root.parents:
            raise RuntimeError("Authentication mail storage must be separate")
    return LocalEmailDelivery(root)
