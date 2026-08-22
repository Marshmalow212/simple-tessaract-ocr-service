# filepath: app/api/v1/endpoints/health.py
"""Health check endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response

from app.core.config import Settings, get_settings
from app.db.session import ping_database
from app.middleware.decorators import request_log_middleware, timing_middleware, middleware
from app.schemas.responses import ComponentHealth, HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


async def _check_db() -> ComponentHealth:
    """Probe the database and report latency + status."""
    import time

    start = time.perf_counter()
    try:
        ok = await ping_database()
        latency_ms = (time.perf_counter() - start) * 1000
        if ok:
            return ComponentHealth(
                name="postgres", status="ok", detail="reachable", latency_ms=latency_ms
            )
        return ComponentHealth(
            name="postgres", status="down", detail="ping returned false", latency_ms=latency_ms
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return ComponentHealth(
            name="postgres", status="down", detail=str(exc), latency_ms=latency_ms
        )


@router.get(
    "",
    response_model=HealthResponse,
    summary="Service liveness/readiness probe (includes DB check)",
    responses={
        200: {"description": "Service is healthy"},
        503: {"description": "Service degraded"},
    },
)
@middleware(request_log_middleware, timing_middleware)
async def health_check(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Aggregate health: app metadata + dependency probes (DB, ...)."""
    db_component = await _check_db()
    components = [db_component]
    overall = "ok" if all(c.status == "ok" for c in components) else "degraded"

    if overall != "ok":
        # Surface degraded state via status code so orchestrators can react.
        from fastapi import status

        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status=overall,
        app_name=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        timestamp=datetime.utcnow(),
        components=components,
    )


@router.get("/ping", summary="Lightweight liveness probe")
async def ping(response: Response) -> dict[str, str]:
    response.headers["X-Service"] = "simple-ocr-service"
    return {"pong": "true"}
