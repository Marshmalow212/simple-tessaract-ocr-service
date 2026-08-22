# filepath: app/schemas/ocr.py
"""Pydantic models for the OCR endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


OcrLanguage = Literal["eng", "hin", "fra", "deu", "spa"]


class OcrMetadata(BaseModel):
    """Metadata accompanying an OCR result."""

    filename: str
    content_type: str
    size_bytes: int
    language: OcrLanguage
    processed_at: datetime


class OcrResult(BaseModel):
    """Structured OCR response."""

    text: str = Field(..., description="Extracted text from the image")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Average confidence score")
    word_count: int = Field(..., ge=0)
    metadata: OcrMetadata
