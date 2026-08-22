# Simple OCR Service

Production-grade FastAPI microservice scaffold with API-key auth, versioned
routers, middleware-as-decorators, structured logging, async Postgres
integration, Dockerized dev environment, and uvicorn ASGI server.

## Quick start (local Python)

```bash
# 1. Create venv
uv venv venv --python python3.14

# 2. Install deps
uv pip install --python venv/bin/python -r requirements.txt

# 3. Configure
cp .env.example .env
# edit .env to set API_KEYS

# 4. Run
./run.sh
# or: uvicorn app.main:app --reload
```

## Quick start (Docker)

```bash
docker compose up --build
# API:        http://localhost:8000
# Swagger UI: http://localhost:8000/docs
# Postgres:   localhost:5432 (user/pw/db = ocr/ocr/ocr)

docker compose down -v   # stop + wipe DB volume
```

## Layout

```
app/
├── api/v1/
│   ├── endpoints/
│   │   ├── health.py        # /api/v1/health (incl. DB check)
│   │   └── ocr.py           # /api/v1/ocr/extract (file upload)
│   └── router.py            # v1 aggregator
├── core/
│   ├── config.py            # pydantic-settings
│   ├── logging.py           # rotating-file + console logging
│   ├── lifespan.py          # startup/shutdown (also DB init)
│   ├── security.py          # API-key dependency
│   └── exception_handlers.py
├── db/
│   ├── base.py              # SQLAlchemy declarative base
│   └── session.py           # async engine, session, ping_database()
├── middleware/
│   └── decorators.py        # @middleware / @request_log_middleware / @timing_middleware
├── repositories/
│   └── ocr_repository.py    # data access (in-memory; swap for DB)
├── schemas/
│   ├── ocr.py               # request/response Pydantic models
│   └── responses.py         # HealthResponse, ComponentHealth, ErrorResponse
├── services/
│   └── ocr_service.py       # business logic
└── main.py                  # FastAPI app factory
```

## Endpoints

| Method | Path                                  | Auth   | Description                                              |
| ------ | ------------------------------------- | ------ | -------------------------------------------------------- |
| GET    | `/`                                   | none   | Service banner                                           |
| GET    | `/api/v1/health`                      | none   | Health probe (app + DB). 503 when degraded.              |
| GET    | `/api/v1/health/ping`                 | none   | Lightweight liveness probe                               |          |
| POST   | `/api/v1/ocr/tesseract`               | API-key| Tesseract OCR for JPG/JPEG (multipart/form, in-memory, cached) |
| GET    | `/api/v1/ocr/tesseract/cache/stats`   | none   | OCR cache counters (hits, misses, size, …)               |
| POST   | `/api/v1/ocr/tesseract/cache/purge`   | API-key| Drop all cached OCR entries                              |
| GET    | `/docs`                               | none   | Swagger UI                                               |
| GET    | `/redoc`                              | none   | ReDoc UI                                                 |

### Tesseract OCR (`/api/v1/ocr/tesseract`)

Accepts a `multipart/form-data` upload of an `image/jpeg` (or `image/jpg`).
The bytes are read into memory, decoded by Pillow, and handed straight to
`pytesseract.image_to_string` / `image_to_data` — **the application never
writes the upload to disk**. (pytesseract itself uses a temp file under
`/tmp` to invoke the binary; that file is removed immediately after the call.)

Request:

```bash
curl -X POST http://localhost:8000/api/v1/ocr/tesseract \
  -H "X-API-Key: api-test-55441133" \
  -F "file=@/path/to/image.jpg"
```

Response (success):

```json
{
  "success": true,
  "text": "extracted text content here",
  "confidence": 0.95,
  "processing_time_ms": 1234
}
```

Errors:

- **400** — invalid content type, corrupt/unsupported image, engine error.
- **401** / **403** — missing/invalid API key.
- **500** — unexpected server error.

### Health response

```json
{
  "status": "ok",
  "app_name": "simple-ocr-service",
  "version": "1.0.0",
  "environment": "docker",
  "timestamp": "2026-08-21T...",
  "components": [
    { "name": "postgres", "status": "ok", "detail": "reachable", "latency_ms": 1.42 }
  ]
}
```

## Auth

Send `X-API-Key: <one-of-your-keys>` on protected routes. Configure allowed keys
via `API_KEYS=key1,key2` in `.env`.

## Database

Configured via `DATABASE_URL` (async, used by the app) and `DATABASE_URL_SYNC`
(sync, used by migrations). Defaults:

```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ocr
```

The DB engine is initialized in the FastAPI lifespan; `GET /api/v1/health`
pings `SELECT 1` and reports latency + status per component.

## Middleware-as-decorators

Apply to any FastAPI route handler:

```python
from app.middleware.decorators import (
    middleware, request_log_middleware, timing_middleware, audit_log_middleware,
)

@router.post("/something")
@middleware(request_log_middleware, timing_middleware, audit_log_middleware("do_something"))
async def handler(...):
    ...
```
