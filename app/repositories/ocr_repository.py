# filepath: app/repositories/ocr_repository.py
"""
OCR repository: encapsulates persistence of OCR results.

Currently an in-memory store; designed to be swapped for a DB-backed
implementation without affecting the service layer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from app.schemas.ocr import OcrMetadata, OcrResult


class OcrRepository(Protocol):
    """Repository interface for OCR results."""

    def save(self, result: OcrResult) -> None: ...
    def get_by_filename(self, filename: str) -> OcrResult | None: ...
    def list_all(self) -> list[OcrResult]: ...


class InMemoryOcrRepository:
    """Thread-safe-ish in-memory store (sufficient for single-process dev)."""

    def __init__(self) -> None:
        self._store: dict[str, OcrResult] = {}

    def save(self, result: OcrResult) -> None:
        self._store[result.metadata.filename] = result

    def get_by_filename(self, filename: str) -> OcrResult | None:
        return self._store.get(filename)

    def list_all(self) -> list[OcrResult]:
        return list(self._store.values())


def build_metadata(
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
    language: str = "eng",
) -> OcrMetadata:
    """Convenience factory for OcrMetadata."""
    return OcrMetadata(
        filename=filename,
        content_type=content_type,
        size_bytes=size_bytes,
        language=language,  # type: ignore[arg-type]
        processed_at=datetime.utcnow(),
    )
