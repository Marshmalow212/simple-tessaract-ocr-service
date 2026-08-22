# filepath: tests/test_ocr_cache.py
"""Tests for the OCR cache + cache-aware /api/v1/ocr/tesseract endpoint.

Verifies:
- Cache key derivation is stable and language-aware.
- LRU + TTL eviction work.
- Hit/miss are NOT exposed on the API response.
- Hit/miss ARE always written to the dedicated cache audit log,
  even when the root logger is set to CRITICAL.
"""
from __future__ import annotations

import io
import logging
import os
from typing import Any

os.environ.setdefault("API_KEYS", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope:nope@127.0.0.1:1/nope")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.core.logging import CACHE_AUDIT_LOGGER_NAME  # noqa: E402
from app.main import app  # noqa: E402
from app.services import tesseract_engine  # noqa: E402
from app.services.ocr_cache import (  # noqa: E402
    OcrCache,
    init_default_cache,
    make_cache_key,
    reset_default_cache_for_tests,
)

client = TestClient(app)
API_KEY = "test-key"
AUTH = {"X-API-Key": API_KEY}


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _make_jpeg_bytes(color: tuple[int, int, int] = (255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color=color).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    reset_default_cache_for_tests()
    init_default_cache(capacity=4, ttl_seconds=0)
    yield
    reset_default_cache_for_tests()


@pytest.fixture
def patched_tesseract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_image_to_string(image: Any, lang: str = "", config: str = "", **_: Any) -> str:
        return "FAKE OCR OUTPUT"

    def fake_image_to_data(image: Any, lang: str = "", config: str = "", output_type: Any = None, **_: Any) -> dict:
        return {"text": ["FAKE", "OCR", "OUTPUT"], "conf": [80, 90, 95]}

    monkeypatch.setattr(tesseract_engine.pytesseract, "image_to_string", fake_image_to_string)
    monkeypatch.setattr(tesseract_engine.pytesseract, "image_to_data", fake_image_to_data)


class _AuditCapture:
    """Capture records emitted to the dedicated cache-audit logger."""

    def __init__(self) -> None:
        self.records: list[logging.LogRecord] = []
        self._handler: logging.Handler | None = None

    def __enter__(self) -> "_AuditCapture":
        logger = logging.getLogger(CACHE_AUDIT_LOGGER_NAME)

        def _emit(record: logging.LogRecord) -> None:
            self.records.append(record)

        self._handler = logging.Handler(level=logging.NOTSET)
        self._handler.emit = _emit  # type: ignore[method-assign]
        logger.addHandler(self._handler)
        return self

    def __exit__(self, *_: Any) -> None:
        if self._handler is not None:
            logging.getLogger(CACHE_AUDIT_LOGGER_NAME).removeHandler(self._handler)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


@pytest.fixture
def audit_capture() -> Any:
    return _AuditCapture()


# ---------------------------------------------------------------------------
# Pure-cache unit tests
# ---------------------------------------------------------------------------


def test_make_cache_key_is_deterministic_and_separates_lang() -> None:
    payload = b"hello-image-bytes"
    k1 = make_cache_key(payload, "eng")
    k2 = make_cache_key(payload, "eng")
    k3 = make_cache_key(payload, "hin")
    assert k1 == k2
    assert k1 != k3
    assert len(k1) == 64  # sha256 hex


def test_cache_put_and_get_roundtrip() -> None:
    from app.schemas.tesseract import TesseractOcrResponse

    cache = OcrCache(capacity=4, ttl_seconds=0)
    response = TesseractOcrResponse(text="x", confidence=0.5, processing_time_ms=10)
    import asyncio

    async def _run() -> None:
        await cache.put("k1", response)
        hit = await cache.get("k1")
        assert hit is not None
        assert hit.text == "x"

    asyncio.run(_run())
    assert cache.stats.hits == 1
    assert cache.stats.stores == 1
    assert cache.stats.misses == 0


def test_cache_lru_evicts_oldest_entry() -> None:
    from app.schemas.tesseract import TesseractOcrResponse
    import asyncio

    cache = OcrCache(capacity=2, ttl_seconds=0)
    resp = TesseractOcrResponse(text="x", confidence=0.1, processing_time_ms=1)

    async def _run() -> None:
        await cache.put("a", resp)
        await cache.put("b", resp)
        await cache.put("c", resp)
        assert (await cache.get("a")) is None
        assert (await cache.get("b")) is not None
        assert (await cache.get("c")) is not None
        assert cache.stats.evictions == 1

    asyncio.run(_run())


def test_cache_ttl_expiration() -> None:
    from app.schemas.tesseract import TesseractOcrResponse
    import asyncio

    cache = OcrCache(capacity=4, ttl_seconds=1)
    resp = TesseractOcrResponse(text="x", confidence=0.1, processing_time_ms=1)

    async def _run() -> None:
        await cache.put("k", resp)
        assert (await cache.get("k")) is not None
        stored_at, value = cache._store["k"]  # type: ignore[attr-defined]
        cache._store["k"] = (stored_at - 5, value)  # type: ignore[attr-defined]
        assert (await cache.get("k")) is None
        assert cache.stats.expirations == 1

    asyncio.run(_run())


def test_cache_purge_drops_everything() -> None:
    from app.schemas.tesseract import TesseractOcrResponse
    import asyncio

    cache = OcrCache(capacity=4, ttl_seconds=0)
    resp = TesseractOcrResponse(text="x", confidence=0.1, processing_time_ms=1)

    async def _run() -> None:
        for k in ("a", "b", "c"):
            await cache.put(k, resp)
        assert cache.size == 3
        removed = await cache.purge()
        assert removed == 3
        assert cache.size == 0

    asyncio.run(_run())


def test_cache_rejects_invalid_construction() -> None:
    with pytest.raises(ValueError):
        OcrCache(capacity=0)
    with pytest.raises(ValueError):
        OcrCache(capacity=4, ttl_seconds=-1)


# ---------------------------------------------------------------------------
# Endpoint integration tests
# ---------------------------------------------------------------------------


def _post_tesseract(payload: bytes, name: str = "a.jpg") -> Any:
    return client.post(
        "/api/v1/ocr/tesseract",
        files={"file": (name, payload, "image/jpeg")},
        headers=AUTH,
    )


def test_response_does_not_contain_cache_hit(patched_tesseract: None) -> None:
    payload = _make_jpeg_bytes()
    r1 = _post_tesseract(payload)
    assert r1.status_code == 200, r1.text
    assert "cache_hit" not in r1.json()

    r2 = _post_tesseract(payload)
    assert r2.status_code == 200
    assert "cache_hit" not in r2.json()


def test_audit_log_records_miss_then_hit(patched_tesseract: None, audit_capture: _AuditCapture) -> None:
    payload = _make_jpeg_bytes()
    with audit_capture:
        assert _post_tesseract(payload).status_code == 200
        assert _post_tesseract(payload).status_code == 200

    msgs = audit_capture.messages()
    assert len(msgs) == 2
    assert any("ocr cache MISS" in m for m in msgs)
    assert any("ocr cache HIT" in m for m in msgs)


def test_audit_log_writes_even_at_log_level_critical(
    patched_tesseract: None, audit_capture: _AuditCapture
) -> None:
    """Even if the operator sets LOG_LEVEL=CRITICAL, cache audit lines must land."""
    root = logging.getLogger()
    original_level = root.level
    root.setLevel(logging.CRITICAL)
    try:
        with audit_capture:
            assert _post_tesseract(_make_jpeg_bytes()).status_code == 200
            assert _post_tesseract(_make_jpeg_bytes()).status_code == 200
    finally:
        root.setLevel(original_level)

    msgs = audit_capture.messages()
    assert len(msgs) == 2
    assert any("ocr cache MISS" in m for m in msgs)
    assert any("ocr cache HIT" in m for m in msgs)


def test_different_images_each_miss_then_one_hit(
    patched_tesseract: None, audit_capture: _AuditCapture
) -> None:
    p1 = _make_jpeg_bytes((255, 0, 0))
    p2 = _make_jpeg_bytes((0, 255, 0))
    p3 = _make_jpeg_bytes((0, 0, 255))

    with audit_capture:
        for p in (p1, p2, p3):
            assert _post_tesseract(p).status_code == 200
        assert _post_tesseract(p2).status_code == 200  # hit

    msgs = audit_capture.messages()
    misses = sum(1 for m in msgs if "ocr cache MISS" in m)
    hits = sum(1 for m in msgs if "ocr cache HIT" in m)
    assert misses == 3
    assert hits == 1


def test_cache_stats_endpoint_reports_hits_and_misses(patched_tesseract: None) -> None:
    payload = _make_jpeg_bytes()
    _post_tesseract(payload)
    _post_tesseract(payload)
    _post_tesseract(payload)

    r = client.get("/api/v1/ocr/tesseract/cache/stats")
    assert r.status_code == 200
    stats = r.json()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["stores"] == 1
    assert stats["size"] == 1
    assert stats["capacity"] == 4
    assert stats["hit_ratio"] == pytest.approx(2 / 3, abs=1e-3)


def test_cache_purge_endpoint_clears_entries(
    patched_tesseract: None, audit_capture: _AuditCapture
) -> None:
    p1 = _make_jpeg_bytes((1, 1, 1))
    p2 = _make_jpeg_bytes((2, 2, 2))
    with audit_capture:
        for p in (p1, p2):
            _post_tesseract(p)

    r = client.post("/api/v1/ocr/tesseract/cache/purge", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["purged"] == 2
    assert body["stats"]["size"] == 0

    # After purge, next request is a fresh MISS.
    with audit_capture:
        r = _post_tesseract(p1)
        assert r.status_code == 200
    assert any("ocr cache MISS" in m for m in audit_capture.messages())


def test_cache_purge_requires_api_key(patched_tesseract: None) -> None:
    r = client.post("/api/v1/ocr/tesseract/cache/purge")
    assert r.status_code == 401
