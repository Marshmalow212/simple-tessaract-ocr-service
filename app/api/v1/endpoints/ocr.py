# filepath: app/api/v1/endpoints/ocr.py
"""OCR endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.security import verify_api_key
from app.middleware.decorators import audit_log_middleware, request_log_middleware, timing_middleware, middleware
from app.schemas.ocr import OcrLanguage, OcrResult
from app.schemas.tesseract import (
    OcrCachePurgeResponse,
    OcrCacheStats,
    TesseractOcrResponse,
)
from app.services.ocr_cache import get_default_cache
from app.services.ocr_service import OcrService, TesseractOcrService, get_ocr_service, get_tesseract_ocr_service

logger = get_logger(__name__)

router = APIRouter(prefix="/ocr", tags=["ocr"])

_ALLOWED_JPEG_TYPES = {"image/jpeg", "image/jpg", "image/png"}


@router.post(
    "/extract",
    response_model=OcrResult,
    status_code=status.HTTP_200_OK,
    summary="Extract text from an uploaded image (legacy stub)",
    responses={
        200: {"description": "OCR completed"},
        400: {"description": "Invalid file"},
        401: {"description": "Missing API key"},
        403: {"description": "Invalid API key"},
        413: {"description": "File too large"},
    },
)
@middleware(
    request_log_middleware,
    timing_middleware,
    audit_log_middleware("ocr.extract"),
)
async def extract_text(
    request: Request,
    response: Response,
    file: UploadFile = File(..., description="Image to OCR (PNG/JPEG)"),
    language: OcrLanguage = Form(default="eng", description="OCR language code"),
    api_key: str = Depends(verify_api_key),
    service: OcrService = Depends(get_ocr_service),
) -> OcrResult:
    """Validate the upload, hand it to the OCR service, return structured text."""
    if not file.content_type or not file.content_type.startswith("image/"):
        logger.warning("rejecting non-image upload type=%s", file.content_type)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected an image upload, got content_type={file.content_type!r}.",
        )

    try:
        return await service.process_image(upload=file, language=language)
    except ValueError as exc:
        logger.warning("OCR validation error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/tesseract",
    response_model=TesseractOcrResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract text from an uploaded JPG/JPEG via Tesseract (in-memory)",
    responses={
        200: {"description": "OCR completed"},
        400: {"description": "Invalid file or unsupported content type"},
        401: {"description": "Missing API key"},
        403: {"description": "Invalid API key"},
        413: {"description": "File too large"},
        500: {"description": "Tesseract engine failed"},
    },
)
@middleware(
    request_log_middleware,
    timing_middleware,
    audit_log_middleware("ocr.tesseract"),
)
async def tesseract_extract(
    request: Request,
    response: Response,
    file: UploadFile = File(..., description="JPEG image (image/jpeg or image/jpg)"),
    api_key: str = Depends(verify_api_key),
    settings: Settings = Depends(get_settings),
    service: TesseractOcrService = Depends(get_tesseract_ocr_service),
) -> TesseractOcrResponse:
    """Run Tesseract OCR on an uploaded JPEG, entirely in memory.

    The image bytes are never written to disk; they are decoded by Pillow and
    handed straight to pytesseract.
    """
    # Hard gate on jpeg content-types so we fail fast.
    ctype = (file.content_type or "").lower()
    if ctype not in _ALLOWED_JPEG_TYPES:
        logger.warning("tesseract: rejecting non-jpeg upload type=%s", ctype)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Expected image/jpeg or image/jpg, got content_type={file.content_type!r}.",
        )

    try:
        result = await service.process_image_with_tesseract(
            upload=file, language=settings.tesseract_lang
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # Cache hit/miss is recorded by the service in the dedicated audit log;
    # it is intentionally NOT exposed on the API response.
    return result


@router.get(
    "/tesseract/cache/stats",
    response_model=OcrCacheStats,
    summary="OCR cache stats (hits, misses, size)",
)
async def tesseract_cache_stats() -> OcrCacheStats:
    """Return current cache counters."""
    cache = get_default_cache()
    return OcrCacheStats(**cache.stats_snapshot())


@router.post(
    "/tesseract/cache/purge",
    response_model=OcrCachePurgeResponse,
    summary="Purge all entries from the OCR cache",
    responses={200: {"description": "Cache purged"}},
)
@middleware(
    request_log_middleware,
    timing_middleware,
    audit_log_middleware("ocr.tesseract.cache.purge"),
)
async def tesseract_cache_purge(
    api_key: str = Depends(verify_api_key),
) -> OcrCachePurgeResponse:
    """Drop every cached entry. Returns the number of entries removed."""
    cache = get_default_cache()
    removed = await cache.purge()
    logger.info("ocr cache purged by api_key=%s removed=%d", api_key, removed)
    return OcrCachePurgeResponse(
        purged=removed, stats=OcrCacheStats(**cache.stats_snapshot())
    )
