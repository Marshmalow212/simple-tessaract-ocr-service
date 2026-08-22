# filepath: app/core/lifespan.py
"""Application lifespan (startup/shutdown) context manager."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, init_engine, ping_database
from app.services.ocr_cache import init_default_cache

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and tear down application resources."""
    configure_logging()
    settings = get_settings()

    logger.info(
        "startup: %s v%s (env=%s)", settings.app_name, settings.app_version, settings.app_env
    )

    # File uploads
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    logger.info("upload directory ready: %s", settings.upload_path)

    # Database
    try:
        init_engine()
        if await ping_database():
            logger.info("database reachable")
        else:
            logger.warning("database NOT reachable on startup (will retry on demand)")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("database init failed: %s", exc)

    # OCR cache
    if settings.ocr_cache_enabled:
        init_default_cache(
            capacity=settings.ocr_cache_capacity,
            ttl_seconds=settings.ocr_cache_ttl_seconds,
        )
    else:
        logger.info("ocr cache disabled by config")

    yield

    logger.info("shutdown: %s", settings.app_name)
    await dispose_engine()
