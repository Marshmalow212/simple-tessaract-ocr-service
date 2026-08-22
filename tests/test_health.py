# filepath: tests/test_health.py
"""Smoke tests for the health endpoint."""
from __future__ import annotations

import os

os.environ.setdefault("API_KEYS", "test-key")
# Point DB at an obviously unreachable host so the test exercises the
# "down" branch without requiring a running Postgres.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nope:nope@127.0.0.1:1/nope")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_ping_returns_pong() -> None:
    response = client.get("/api/v1/health/ping")
    assert response.status_code == 200
    assert response.json() == {"pong": "true"}


def test_health_endpoint_includes_db_component() -> None:
    response = client.get("/api/v1/health")
    payload = response.json()
    # The endpoint always reports components; without a real DB it must be `down`.
    assert "components" in payload
    assert isinstance(payload["components"], list)
    assert any(c["name"] == "postgres" for c in payload["components"])
    db_component = next(c for c in payload["components"] if c["name"] == "postgres")
    assert db_component["status"] in ("ok", "down")
    # When the DB is unreachable the overall status flips to "degraded" + 503.
    if db_component["status"] == "down":
        assert payload["status"] == "degraded"
        assert response.status_code == 503
    else:
        assert payload["status"] == "ok"
        assert response.status_code == 200


def test_ocr_requires_api_key() -> None:
    response = client.post("/api/v1/ocr/extract")
    assert response.status_code in (401, 422)
