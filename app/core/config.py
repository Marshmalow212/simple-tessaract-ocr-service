# filepath: app/core/config.py
"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized settings, sourced from .env and environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "simple-ocr-service"
    app_version: str = "1.0.0"
    app_env: str = "development"
    debug: bool = True

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/app.log"

    # Auth
    api_keys: Annotated[list[str], NoDecode] = Field(default_factory=list)
    api_key_header: str = "X-API-Key"

    # CORS
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    # Uploads
    upload_dir: str = "uploads"
    max_upload_size_mb: int = 10
    allowed_image_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["image/png", "image/jpeg", "image/jpg", "image/webp"]
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ocr"
    database_url_sync: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ocr"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout_seconds: int = 10

    # Tesseract
    tesseract_cmd: str | None = None
    tesseract_lang: str = "eng"
    tesseract_oem: str | None = None
    tesseract_psm: str | None = None

    # OCR cache (LRU + optional TTL)
    ocr_cache_enabled: bool = True
    ocr_cache_capacity: int = 128
    ocr_cache_ttl_seconds: int = 0  # 0 = no expiry
    ocr_cache_audit_log: str = "logs/ocr_cache.log"  # dedicated audit log (always-on)

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_api_keys(cls, value: object) -> object:
        """Allow comma-separated string from env (e.g. `key1,key2`)."""
        if isinstance(value, str):
            return [k.strip() for k in value.split(",") if k.strip()]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir).resolve()

    @property
    def log_path(self) -> Path:
        return Path(self.log_file).resolve()


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor (FastAPI dependency-friendly)."""
    return Settings()
