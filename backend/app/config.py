from functools import lru_cache
from pathlib import Path

from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost:5432/spectra"
    card_image_dir: Path = Path(__file__).resolve().parents[1] / "data" / "card_images"
    boundary_output_dir: Path = Path(__file__).resolve().parents[1] / "data" / "boundary_diagnostics"
    boundary_review_enabled: bool = False
    max_image_size_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    auth_origin: str = "http://127.0.0.1:3000"
    auth_environment: Literal["development", "production"] = "development"
    auth_session_hours: int = Field(default=24, ge=1, le=720)
    auth_verification_hours: int = Field(default=24, ge=1, le=72)
    auth_reset_minutes: int = Field(default=30, ge=1, le=60)
    auth_rate_limit: int = Field(default=10, ge=1)
    auth_rate_window_seconds: int = Field(default=900, ge=1)
    auth_mail_dir: Path = Path(__file__).resolve().parents[1] / "data" / "auth_mail"

    @model_validator(mode="after")
    def auth_settings(self):
        from urllib.parse import urlsplit
        url = urlsplit(self.auth_origin)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.path or url.query or url.fragment:
            raise ValueError("AUTH_ORIGIN must be a bare HTTP(S) origin without trailing slash")
        if self.auth_environment == "production" and url.scheme != "https":
            raise ValueError("Production authentication requires HTTPS")
        if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("HTTP authentication is limited to local development")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
