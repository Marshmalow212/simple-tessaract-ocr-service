# filepath: app/main.py
"""
FastAPI application factory.

Wires together:
- Lifespan (startup/shutdown)
- CORS + request-logging ASGI middleware
- Global exception handlers
- Versioned routers (/api/v1)
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router as v1_router
from app.core.config import get_settings
from app.core.exception_handlers import register_exception_handlers
from app.core.lifespan import lifespan


def create_app() -> FastAPI:
    """Application factory (production-friendly, testable)."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # --- CORS -------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "X-Response-Time-ms"],
    )

    # --- Versioned routes -------------------------------------------------
    app.include_router(v1_router, prefix="/api/v1")

    # --- Root redirect ----------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "service": settings.app_name,
            "version": settings.app_version,
            "docs": "/docs",
            "health": "/api/v1/health",
        }

    # --- Error handling ---------------------------------------------------
    register_exception_handlers(app)

    return app


# uvicorn entry-point: `uvicorn app.main:app --reload`
app = create_app()
