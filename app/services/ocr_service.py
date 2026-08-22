# filepath: app/services/ocr_service.py
"""
OCR service: orchestrates the engine + repository.

Two flavours:
- `process_image(...)`                — generic, currently a stub (legacy).
- `process_image_with_tesseract(...)` — real Tesseract, in-memory only,
  returns a `TesseractOcrResponse` with the shape the API contract requires.

`TesseractOcrService` is cache-aware: identical image bytes (same language)
are served from an in-memory LRU cache instead of being re-OCR'd.
"""
from __future__ import annotations

import time

from fastapi import UploadFile

from app.core.logging import get_cache_audit_logger, get_logger
from app.repositories.ocr_repository import OcrRepository, build_metadata
from app.schemas.ocr import OcrLanguage, OcrResult
from app.schemas.tesseract import TesseractOcrResponse
from app.services.ocr_cache import OcrCache, make_cache_key
from app.services.tesseract_engine import TesseractEngine, TesseractEngineError

logger = get_logger(__name__)
audit = get_cache_audit_logger()


# ---------------------------------------------------------------------------
# Legacy / stub OCR (kept for the original /ocr/extract endpoint).
# ---------------------------------------------------------------------------

_OCR_PLACEHOLDER_TEXT = "[OCR stub] Replace with real OCR engine output."
_OCR_PLACEHOLDER_CONFIDENCE = 0.92


class OcrService:
    """Encapsulates OCR business rules (legacy stub)."""

    def __init__(self, repository: OcrRepository) -> None:
        self._repository = repository

    async def process_image(
        self,
        *,
        upload: UploadFile,
        language: OcrLanguage = "eng",
    ) -> OcrResult:
        contents = await upload.read()
        size_bytes = len(contents)
        logger.info(
            "OCR processing file=%s type=%s size=%d lang=%s",
            upload.filename, upload.content_type, size_bytes, language,
        )

        text, confidence = await self._run_ocr(contents, language)

        metadata = build_metadata(
            filename=upload.filename or "unknown",
            content_type=upload.content_type or "application/octet-stream",
            size_bytes=size_bytes,
            language=language,
        )
        result = OcrResult(
            text=text,
            confidence=confidence,
            word_count=len(text.split()),
            metadata=metadata,
        )
        self._repository.save(result)
        return result

    @staticmethod
    async def _run_ocr(_contents: bytes, _language: OcrLanguage) -> tuple[str, float]:
        return _OCR_PLACEHOLDER_TEXT, _OCR_PLACEHOLDER_CONFIDENCE


def get_ocr_service() -> OcrService:
    from app.repositories.ocr_repository import InMemoryOcrRepository
    return OcrService(InMemoryOcrRepository())


# ---------------------------------------------------------------------------
# Real Tesseract pipeline (in-memory, no disk writes).
# ---------------------------------------------------------------------------


class TesseractOcrService:
    """Real OCR pipeline backed by `TesseractEngine`.

    Reads the upload fully into memory, decodes via Pillow, runs Tesseract, and
    returns a flat response with timing. No intermediate files are written.

    If a cache is provided, identical image bytes (under the same language) are
    served from the cache instead of being re-OCR'd. Each hit/miss is also
    emitted to the dedicated cache audit logger so the trail is preserved
    regardless of the root log level.
    """

    def __init__(
        self,
        engine: TesseractEngine | None = None,
        cache: OcrCache | None = None,
    ) -> None:
        self._engine = engine or TesseractEngine()
        self._cache = cache  # may be None to disable caching

    async def process_image_with_tesseract(
        self,
        *,
        upload: UploadFile,
        language: str | None = None,
    ) -> TesseractOcrResponse:
        """Run OCR (with caching). Returns a `TesseractOcrResponse`.

        Cache hit/miss is recorded via the dedicated audit logger so the
        event is always captured regardless of LOG_LEVEL. It is NOT
        surfaced on the API response.
        """
        start = time.perf_counter()

        engine = self._engine
        if language and language != engine.lang:
            engine = TesseractEngine(
                lang=language,
                oem=engine.oem,
                psm=engine.psm,
                cmd=pytesseract.tesseract_cmd or None,
            )

        contents = await upload.read()
        elapsed_read_ms = int((time.perf_counter() - start) * 1000)

        cache_key = make_cache_key(contents, engine.lang) if self._cache else ""

        # Cache lookup
        if self._cache is not None:
            cached = await self._cache.get(cache_key)
            if cached is not None:
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                # Always-on audit: independent of LOG_LEVEL.
                audit.warning(
                    "ocr cache HIT file=%s key=%s size=%d lang=%s ms=%d",
                    upload.filename, cache_key, len(contents), engine.lang, elapsed_ms,
                )
                return cached.model_copy(update={"processing_time_ms": elapsed_ms})

        logger.info(
            "tesseract request file=%s type=%s size=%d lang=%s key=%s…",
            upload.filename, upload.content_type, len(contents), engine.lang, cache_key[:10],
        )

        try:
            outcome = engine.extract(contents)
        except TesseractEngineError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            logger.warning("tesseract error after %dms: %s", elapsed_ms, exc)
            raise ValueError(str(exc)) from exc

        total_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "tesseract done in %dms (read=%dms, ocr=%dms) conf=%.2f chars=%d",
            total_ms, elapsed_read_ms, total_ms - elapsed_read_ms,
            outcome.confidence, len(outcome.text),
        )
        final_text = process_outcome_text(outcome)
        result = TesseractOcrResponse(
            success=True,
            text=final_text,
            confidence=outcome.confidence,
            processing_time_ms=total_ms,
        )

        # Cache store + miss audit (best-effort store; never fail the request).
        if self._cache is not None:
            try:
                await self._cache.put(cache_key, result)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("cache put failed: %s", exc)
            # Always-on audit: independent of LOG_LEVEL.
            audit.warning(
                "ocr cache MISS file=%s key=%s size=%d lang=%s ms=%d "
                "text_chars=%d conf=%.2f",
                upload.filename, cache_key, len(contents), engine.lang, total_ms,
                len(outcome.text), outcome.confidence,
            )

        return result


def get_tesseract_ocr_service() -> TesseractOcrService:
    """FastAPI dependency: build a Tesseract OCR service from settings."""
    from app.core.config import get_settings
    from app.services.ocr_cache import get_default_cache

    settings = get_settings()
    engine = TesseractEngine(
        lang=settings.tesseract_lang,
        oem=settings.tesseract_oem or None,
        psm=settings.tesseract_psm or None,
        cmd=settings.tesseract_cmd or None,
    )
    cache = get_default_cache() if settings.ocr_cache_enabled else None
    return TesseractOcrService(engine=engine, cache=cache)

def process_outcome_text(outcome: TesseractOcrOutcome) -> str:
    """Process the OCR outcome text to remove unwanted characters and whitespace."""
    # Remove non-printable characters
    cleaned_text = ''.join(c for c in outcome.text if c.isprintable())
    # Normalize whitespace (replace multiple spaces with a single space)
    cleaned_text = ' '.join(cleaned_text.split())

    # Normalize other characters (e.g., replace fancy quotes with standard quotes, replace \n with new line)
    cleaned_text = cleaned_text.replace('“', '"').replace('”', '"').replace("‘", "'").replace("’", "'")


    return cleaned_text
