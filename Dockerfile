# ---- builder: install wheels into a relocatable prefix ---------------------
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---- runtime: minimal image with the app code -----------------------------
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOME=/app \
    PORT=8000

# Runtime-only system packages.
# - libpq5: required by asyncpg / psycopg2
# - tesseract-ocr: the OCR engine invoked by pytesseract
# - tesseract-ocr-eng: English language data (add more as needed)
# - curl: used by the container healthcheck
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 \
        tesseract-ocr \
        tesseract-ocr-eng \
        curl \
 && rm -rf /var/lib/apt/lists/*

# Bring wheels from the builder stage
COPY --from=builder /install /usr/local

WORKDIR ${APP_HOME}
COPY --chown=app:app . ${APP_HOME}

# Persistent dirs
RUN mkdir -p ${APP_HOME}/logs ${APP_HOME}/uploads

EXPOSE 8000

# Container-level healthcheck (liveness).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/api/v1/health/ping || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
