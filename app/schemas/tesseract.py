# filepath: app/schemas/tesseract.py
"""Pydantic schemas for the Tesseract OCR endpoint."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


JpegContentType = Literal["image/jpeg", "image/jpg"]


class TesseractOcrResponse(BaseModel):
    """Final OCR response shape for the Tesseract endpoint."""

    success: bool = Field(default=True, description="Whether OCR completed successfully")
    text: str = Field(default="", description="Extracted plain text")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Average confidence score in [0, 1] (Tesseract mean / 100)",
    )
    processing_time_ms: int = Field(
        default=0, ge=0, description="Total processing time in milliseconds"
    )
    # NOTE: cache_hit is intentionally NOT exposed on the API response.
    # It is always recorded in the dedicated cache audit log instead, so
    # callers don't see the value but operators still get a guaranteed
    # hit/miss trail regardless of LOG_LEVEL.


class TesseractErrorResponse(BaseModel):
    """Error response shape (mirrors the success shape for clients)."""

    success: bool = False
    text: str = ""
    confidence: float = 0.0
    processing_time_ms: int = 0
    detail: str | None = None


class OcrCacheStats(BaseModel):
    """Cache observability payload."""

    hits: int = 0
    misses: int = 0
    stores: int = 0
    evictions: int = 0
    expirations: int = 0
    size: int = 0
    capacity: int = 0
    ttl_seconds: int = 0
    hit_ratio: float = 0.0


class OcrCachePurgeResponse(BaseModel):
    """Response after a cache purge."""

    purged: int
    stats: OcrCacheStats
