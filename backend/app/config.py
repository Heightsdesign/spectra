from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", extra="ignore")

    database_url: str = "postgresql+psycopg://localhost:5432/spectra"
    card_image_dir: Path = Path(__file__).resolve().parents[1] / "data" / "card_images"
    boundary_output_dir: Path = Path(__file__).resolve().parents[1] / "data" / "boundary_diagnostics"
    max_image_size_bytes: int = Field(default=25 * 1024 * 1024, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
