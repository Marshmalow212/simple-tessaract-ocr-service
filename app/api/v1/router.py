# filepath: app/api/v1/router.py
"""Version 1 API aggregator."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.endpoints import health, ocr

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(ocr.router)
