# filepath: app/core/logging.py
"""Structured logging configuration."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import get_settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

# Dedicated audit logger name. Lives below root so it can carry its own
# handlers and level — used for events that MUST appear regardless of the
# operator's chosen `LOG_LEVEL` (e.g. OCR cache hit/miss auditing).
CACHE_AUDIT_LOGGER_NAME = "app.audit.cache"


def configure_logging() -> None:
    """Configure root logger with console + rotating file handlers."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.handlers.clear()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler (rotating)
    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers
    for noisy in ("uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Always-on audit channel for cache hit/miss. Idempotent: only set up
    # if no handlers exist yet so we don't blow away test capture handlers
    # already attached to this logger.
    _configure_cache_audit_logger(settings.ocr_cache_audit_log)


def _configure_cache_audit_logger(log_file: str) -> None:
    """Configure the dedicated cache-audit logger.

    Idempotent: the logger is already wired at import time via
    `get_cache_audit_logger()`. Here we just re-point the file handler if
    the operator configured a different path.
    """
    audit_logger = logging.getLogger(CACHE_AUDIT_LOGGER_NAME)
    audit_logger.setLevel(logging.WARNING)
    audit_logger.propagate = False

    if not audit_logger.handlers:
        _attach_audit_handlers(audit_logger, log_file)
        return

    # If the user-supplied log file differs from the current default
    # file handler, swap it out.
    current_file = next(
        (h for h in audit_logger.handlers if isinstance(h, RotatingFileHandler)), None
    )
    desired_path = Path(log_file).resolve()
    if current_file is not None:
        current_path = Path(current_file.baseFilename).resolve()  # type: ignore[attr-defined]
        if current_path == desired_path:
            return
        audit_logger.removeHandler(current_file)
        current_file.close()
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    desired_path.parent.mkdir(parents=True, exist_ok=True)
    new_handler = RotatingFileHandler(
        desired_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    new_handler.setLevel(logging.WARNING)
    new_handler.setFormatter(formatter)
    audit_logger.addHandler(new_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger."""
    return logging.getLogger(name)


def get_cache_audit_logger() -> logging.Logger:
    """Return the always-on cache audit logger (see CACHE_AUDIT_LOGGER_NAME).

    The audit logger is configured eagerly at module import so that cache
    audit events always have a destination, regardless of whether the
    FastAPI lifespan has run yet (matters for tests, workers, and tools).
    """
    audit_logger = logging.getLogger(CACHE_AUDIT_LOGGER_NAME)
    audit_logger.setLevel(logging.WARNING)
    audit_logger.propagate = False
    if not audit_logger.handlers:
        # Use defaults here; `configure_logging()` may override the log
        # file path once settings are available.
        default_path = "logs/ocr_cache.log"
        _attach_audit_handlers(audit_logger, default_path)
    return audit_logger


def _attach_audit_handlers(audit_logger: logging.Logger, log_file: str) -> None:
    """Attach the default file + console handlers to the audit logger."""
    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(formatter)
    audit_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    audit_logger.addHandler(console_handler)
