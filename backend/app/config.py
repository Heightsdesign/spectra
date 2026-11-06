from functools import lru_cache
from pathlib import Path

from typing import Literal
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")

    stripe_enabled: bool = False
    stripe_fictitious_enabled: bool = False
    stripe_mode: Literal["test", "live"] = "test"
    stripe_secret_key: str = Field(default="", repr=False)
    stripe_webhook_secret: str = Field(default="", repr=False)
    stripe_account_id: str = ""
    stripe_api_version: str = "2025-02-24.acacia"
    logistics_enabled: bool = False  # Foundation/preview only; no C1-B Checkout activation.

    database_url: str = "postgresql+psycopg://localhost:5432/spectra"
    card_image_dir: Path = Path(__file__).resolve().parents[1] / "data" / "card_images"
    boundary_output_dir: Path = Path(__file__).resolve().parents[1] / "data" / "boundary_diagnostics"
    boundary_review_enabled: bool = False
    dispatch_reminder_lead_days: int | None = Field(default=None, ge=1, le=30)
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
        if self.stripe_enabled and (
            self.stripe_mode != "test"
            or self.auth_environment == "production"
            or not self.stripe_secret_key.startswith("sk_test_")
            or not self.stripe_webhook_secret.startswith("whsec_")
            or not self.stripe_account_id.startswith("acct_")
        ):
            raise ValueError("Stripe requires TEST credentials in a non-production environment; live release is gated")
        if self.stripe_fictitious_enabled and (self.auth_environment != "development" or not self.stripe_enabled or self.stripe_mode != "test"):
            raise ValueError("Fictitious checkout requires development and enabled Stripe TEST")
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
