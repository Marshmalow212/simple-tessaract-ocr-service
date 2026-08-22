# filepath: app/middleware/decorators.py
"""
Middleware-as-decorators.

These decorators wrap FastAPI route handlers to inject cross-cutting concerns
such as timing, request logging, and lightweight audit logging. They can be
stacked and composed like ordinary Python decorators.

Header injection works by looking up a `Response` parameter (or one named
`response`) in the handler signature — FastAPI provides this automatically
when declared. If no Response is found, headers are silently skipped.
"""
from __future__ import annotations

import functools
import inspect
import time
import uuid
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-Id"
RESPONSE_TIME_HEADER = "X-Response-Time-ms"


# --- Header helpers ---------------------------------------------------------

def _extract_request_id(headers: dict[str, str]) -> str:
    """Return client-supplied request ID or generate a new one."""
    incoming = headers.get(REQUEST_ID_HEADER.lower()) or headers.get(REQUEST_ID_HEADER)
    return incoming or uuid.uuid4().hex


# --- Decorator factory ------------------------------------------------------

def middleware(*decorators: Callable[[Callable[..., Any]], Callable[..., Any]]) -> Callable[
    [Callable[..., Any]], Callable[..., Any]
]:
    """Compose multiple middleware decorators into a single decorator.

    Usage:
        @middleware(timing_middleware, request_log_middleware)
        async def endpoint(...): ...
    """
    def wrap(func: Callable[..., Any]) -> Callable[..., Any]:
        wrapped = func
        for dec in reversed(decorators):
            wrapped = dec(wrapped)
        return functools.wraps(func)(wrapped)
    return wrap


# --- Individual middleware decorators --------------------------------------

def request_log_middleware(func: Callable[..., Any]) -> Callable[..., Any]:
    """Log each request with method, path, status, and duration."""

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        request = kwargs.get("request") or _find_request(args)
        request_id = _extract_request_id(request.headers) if request else "n/a"
        method = request.method if request else "?"
        path = request.url.path if request else "?"

        logger.info("→ %s %s [rid=%s]", method, path, request_id)
        start = time.perf_counter()
        try:
            response = await func(*args, **kwargs)
            elapsed_ms = (time.perf_counter() - start) * 1000
            status_code = _response_status(response)
            logger.info(
                "← %s %s -> %s in %.2fms [rid=%s]",
                method, path, status_code, elapsed_ms, request_id,
            )
            _safe_set_header(kwargs.get("response"), REQUEST_ID_HEADER, request_id)
            return response
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "✗ %s %s failed in %.2fms [rid=%s]: %s",
                method, path, elapsed_ms, request_id, exc,
            )
            raise

    return async_wrapper


def timing_middleware(func: Callable[..., Any]) -> Callable[..., Any]:
    """Attach an X-Response-Time-ms header to the response (if injectable)."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        try:
            response = await func(*args, **kwargs)
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            _safe_set_header(kwargs.get("response"), RESPONSE_TIME_HEADER, f"{elapsed_ms:.2f}")
        return response

    return wrapper


def audit_log_middleware(action: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory: log who triggered an auditable action."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            api_key = kwargs.get("api_key") or kwargs.get("current_api_key")
            actor = api_key or "anonymous"
            logger.info("AUDIT action=%s actor=%s", action, actor)
            return await func(*args, **kwargs)
        return wrapper
    return decorator


def validate_content_type(allowed: list[str]) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory: enforce an allowed set of Content-Type values."""

    allowed_lower = {ct.lower() for ct in allowed}

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request") or _find_request(args)
            if request is None:
                return await func(*args, **kwargs)
            content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
            if content_type and content_type not in allowed_lower:
                from fastapi import HTTPException, status
                raise HTTPException(
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                    detail=f"Unsupported Content-Type '{content_type}'. Allowed: {sorted(allowed_lower)}",
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# --- Helpers ----------------------------------------------------------------

def _find_request(args: tuple[Any, ...]) -> Any | None:
    """Locate the FastAPI `Request` object among positional args."""
    from fastapi import Request
    for arg in args:
        if isinstance(arg, Request):
            return arg
    return None


def _safe_set_header(response_obj: Any, key: str, value: str) -> None:
    """Set a header on a Response-like object, silently skipping if absent."""
    if response_obj is None:
        return
    headers = getattr(response_obj, "headers", None)
    if headers is None:
        return
    try:
        headers[key] = value
    except Exception:  # pragma: no cover - defensive
        pass


def _response_status(response: Any) -> int:
    """Best-effort status extraction for logging."""
    if response is None:
        return 500
    if hasattr(response, "status_code") and isinstance(response.status_code, int):
        return response.status_code
    # Pydantic model path: FastAPI defaults to 200 for response_model
    return 200
