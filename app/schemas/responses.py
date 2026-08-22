# filepath: app/schemas/responses.py
"""Common response schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """Health status of a single dependency."""

    name: str
    status: str = Field(description="ok | degraded | down")
    detail: str | None = None
    latency_ms: float | None = None


class HealthResponse(BaseModel):
    """Health check payload.

    `status` is `ok` only when every component is `ok`. Otherwise `degraded`.
    """

    status: str = Field(default="ok", description="Overall service status")
    app_name: str
    version: str
    environment: str
    timestamp: datetime
    components: list[ComponentHealth] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standardized error payload."""

    detail: str
    code: str | None = None
