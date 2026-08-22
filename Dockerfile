# ---- builder: install wheels into a relocatable prefix ---------------------
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_HOME=/app \
    PORT=8000

WORKDIR ${APP_HOME}

RUN apt-get update \
        && apt-get install -y --no-install-recommends build-essential gcc libpq-dev \
        libpq5 \
        tesseract-ocr \
        tesseract-ocr-eng \
        curl \
        && rm -rf /var/lib/apt/lists/*

COPY . ./
RUN pip install --no-cache-dir -r requirements.txt

# Persistent dirs
RUN mkdir -p ${APP_HOME}/logs ${APP_HOME}/uploads

EXPOSE 8000

# Container-level healthcheck (liveness).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${PORT}/api/v1/health/ping || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
