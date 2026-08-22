# filepath: app/services/ocr_cache.py
"""
In-memory cache for OCR results keyed by content hash.

Design:
- Key = `sha256(bytes + ":" + lang)` (hex digest).
- Value = full TesseractOcrResponse (frozen copy).
- Bounded LRU via OrderedDict.move_to_end().
- Optional TTL (0 = no expiry).
- Single asyncio.Lock guards mutations (FastAPI is async; requests can race).

This module is deliberately infra-light: no Redis, no disk. If you need
multi-process sharing, swap `OcrCache` for a Redis-backed implementation that
exposes the same surface (`get`, `put`, `purge`, `stats`).
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.schemas.tesseract import TesseractOcrResponse

logger = get_logger(__name__)


@dataclass(slots=True)
class CacheStats:
    """Counters surfaced for observability and tests."""

    hits: int = 0
    misses: int = 0
    stores: int = 0
    evictions: int = 0
    expirations: int = 0

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "stores": self.stores,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "size": 0,  # caller patches `size` from the cache itself
            "capacity": 0,
            "hit_ratio": round(self.hit_ratio, 4),
        }


def make_cache_key(image_bytes: bytes, lang: str) -> str:
    """Return a stable, collision-resistant key for the given input."""
    h = hashlib.sha256()
    h.update(image_bytes)
    h.update(b"\x00")
    h.update(lang.encode("utf-8"))
    return h.hexdigest()


class OcrCache:
    """Bounded LRU cache for OCR responses, keyed by content hash."""

    def __init__(self, *, capacity: int = 128, ttl_seconds: int = 0) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be >= 0")
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._store: OrderedDict[str, tuple[float, TesseractOcrResponse]] = OrderedDict()
        self._lock = asyncio.Lock()
        self.stats = CacheStats()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def size(self) -> int:
        return len(self._store)

    def _is_expired(self, stored_at: float) -> bool:
        return self._ttl > 0 and (time.monotonic() - stored_at) > self._ttl

    async def get(self, key: str) -> TesseractOcrResponse | None:
        """Return the cached response for `key` or None on miss/expired."""
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.stats.misses += 1
                return None
            stored_at, value = entry
            if self._is_expired(stored_at):
                # Drop expired entry; counts as a miss.
                self._store.pop(key, None)
                self.stats.expirations += 1
                self.stats.misses += 1
                return None
            # Mark as recently used.
            self._store.move_to_end(key)
            self.stats.hits += 1
            return value

    async def put(self, key: str, value: TesseractOcrResponse) -> None:
        """Store `value` under `key`, evicting the LRU entry if at capacity."""
        async with self._lock:
            if key in self._store:
                # Refresh in place.
                self._store.move_to_end(key)
                self._store[key] = (time.monotonic(), value)
                self.stats.stores += 1
                return
            self._store[key] = (time.monotonic(), value)
            self.stats.stores += 1
            while len(self._store) > self._capacity:
                self._store.popitem(last=False)  # FIFO end = oldest insertion
                self.stats.evictions += 1
            logger.debug(
                "ocr cache put key=%s… size=%d/%d",
                key[:10], len(self._store), self._capacity,
            )

    async def purge(self) -> int:
        """Drop every entry. Returns the number of entries removed."""
        async with self._lock:
            n = len(self._store)
            self._store.clear()
            return n

    def stats_snapshot(self) -> dict[str, Any]:
        snap = self.stats.snapshot()
        snap["size"] = self.size
        snap["capacity"] = self._capacity
        snap["ttl_seconds"] = self._ttl
        return snap


# ---------------------------------------------------------------------------
# Module-level singleton + dependency factory.
# ---------------------------------------------------------------------------

_default_cache: OcrCache | None = None


def init_default_cache(*, capacity: int, ttl_seconds: int) -> OcrCache:
    """(Re)initialize the default cache (called once at startup)."""
    global _default_cache
    _default_cache = OcrCache(capacity=capacity, ttl_seconds=ttl_seconds)
    logger.info("ocr cache initialized capacity=%d ttl=%ds", capacity, ttl_seconds)
    return _default_cache


def get_default_cache() -> OcrCache:
    """Return the default cache, creating a sane default if init wasn't called."""
    global _default_cache
    if _default_cache is None:
        _default_cache = OcrCache(capacity=128, ttl_seconds=0)
    return _default_cache


def reset_default_cache_for_tests() -> None:
    """Test-only: drop the default cache so a fresh one is created on next access."""
    global _default_cache
    _default_cache = None


@dataclass(slots=True)
class CachedOcrResult:
    """Wraps a TesseractOcrResponse with hit/miss info for the endpoint."""

    result: TesseractOcrResponse
    cache_hit: bool = False
    cache_key: str = ""
