# filepath: app/db/session.py
"""Async SQLAlchemy engine, session factory, and helpers."""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql import text

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine() -> AsyncEngine:
    """Initialize the global async engine (idempotent)."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine

    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        echo=settings.db_echo,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        future=True,
        connect_args={"server_settings": {"statement_cache_size": 0}},
    )
    _session_factory = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )
    logger.info(
        "database engine initialized: %s (pool_size=%d, max_overflow=%d)",
        _redact(settings.database_url),
        settings.db_pool_size,
        settings.db_max_overflow,
    )
    return _engine


async def dispose_engine() -> None:
    """Dispose of the global engine (called on shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("database engine disposed")
    _engine = None
    _session_factory = None


def get_engine() -> AsyncEngine:
    """Return the active engine, initializing lazily."""
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an async session, commit on success."""
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None

    session = _session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def ping_database() -> bool:
    """Return True iff a trivial query against the DB succeeds."""
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("database ping failed: %s", exc)
        return False


def _redact(url: str) -> str:
    """Hide password in URL for log lines."""
    if "@" not in url:
        return url
    scheme_user, host_part = url.rsplit("@", 1)
    user_part = scheme_user.split("//", 1)[-1]
    if ":" in user_part:
        user, _ = user_part.rsplit(":", 1)
        prefix = scheme_user.split("://", 1)[0]
        return f"{prefix}://{user}:***@{host_part}"
    return url
